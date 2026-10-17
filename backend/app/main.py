import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import models
from app.actions import ActionError
from app.api import auth, chat, data_import, governance, insights, ledger, onboarding, reports
from app.auth import CSRF_HEADER
from app.config import get_settings
from app.db import SCHEMA_FIX, get_db, schema_problems
from app.logging_setup import configure_logging, request_id_var

settings = get_settings()
configure_logging(settings.log_level, bool(settings.log_json))
log = logging.getLogger("smecopilot.http")

if settings.sentry_dsn:
    import sentry_sdk

    # send_default_pii=False: no cookies, headers or user emails leave the server.
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_env, traces_sample_rate=0.05,
                    send_default_pii=False)

MAX_BODY_BYTES = 256 * 1024
UPLOAD_PATHS = ("/api/import/",)


def check_database_schema() -> None:
    # An out-of-date database otherwise shows up later as a vague 500 on the first write.
    try:
        missing = schema_problems()
    except Exception:  # noqa: BLE001 - database unreachable; /api/ready reports it
        log.exception("Could not inspect the database schema")
        return
    if missing:
        log.error("DATABASE SCHEMA IS OUT OF DATE - missing: %s. %s", ", ".join(missing[:10]), SCHEMA_FIX)


@asynccontextmanager
async def lifespan(_: FastAPI):
    check_database_schema()
    yield


app = FastAPI(
    title="SME Finance Copilot API",
    version="1.0.0",
    description="AI finance copilot for small businesses.",
    # Interactive docs help in development but expose the whole API surface in production.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,  # session cookie
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", CSRF_HEADER, "X-Request-ID"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    rid = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex
    token = request_id_var.set(rid)
    started = time.perf_counter()
    try:
        limit = settings.max_upload_mb * 1024 * 1024 if request.url.path.startswith(UPLOAD_PATHS) else MAX_BODY_BYTES
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > limit:
            response = JSONResponse({"detail": "Request body too large"}, status_code=413)
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path not in ("/api/health", "/api/ready"):
            log.info("%s %s %s", request.method, request.url.path, response.status_code, extra={
                "method": request.method, "path": request.url.path, "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1)})
        return response
    finally:
        request_id_var.reset(token)


@app.exception_handler(ActionError)
async def action_error_handler(_: Request, exc: ActionError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    # Never leak internals; the request id lets support find the log line.
    return JSONResponse({"detail": "Internal server error", "requestId": request_id_var.get()}, status_code=500)


for module in (auth, onboarding, data_import, insights, ledger, governance, chat, reports):
    app.include_router(module.router)


@app.get("/api/health", tags=["system"])
def health() -> dict:
    """Liveness: the process is up (no dependencies checked)."""
    return {"status": "ok", "llmMode": "online" if settings.llm_enabled else "offline"}


@app.get("/api/ready", tags=["system"])
def ready(db: Session = Depends(get_db)) -> JSONResponse:
    """Readiness: the database answers. Used by Docker health checks."""
    try:
        db.execute(text("SELECT 1"))
        missing = schema_problems(db.get_bind())
        if missing:
            return JSONResponse({"status": "schema_outdated", "missing": missing[:20], "fix": SCHEMA_FIX},
                                status_code=503)
        catalog = db.scalar(select(func.count()).select_from(models.FinProduct)) > 0
    except Exception:  # noqa: BLE001
        log.exception("Readiness check failed")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ready", "productCatalog": catalog, "env": settings.app_env})
