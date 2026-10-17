"""CSV/Excel/PDF-statement import endpoints: templates, preview (dry run), import, history."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, models
from app.auth import CurrentUser, any_user, staff
from app.config import get_settings
from app.db import get_db
from app.importer import (
    DATE_FORMATS, EXPENSE_CATEGORIES, INCOME_CATEGORIES, KINDS, TEMPLATES, ImportFileError, run_import,
)
from app.ratelimit import import_limiter

router = APIRouter(prefix="/api/import", tags=["import"])

Kind = Literal["transactions", "invoices", "bills"]


@router.get("/options")
def options(_: CurrentUser = Depends(any_user)) -> dict:
    from app import ocr

    return {"kinds": list(KINDS), "dateFormats": list(DATE_FORMATS), "maxUploadMb": get_settings().max_upload_mb,
            "categories": {"income": INCOME_CATEGORIES, "expense": EXPENSE_CATEGORIES},
            "pdfScans": ocr.available()}


@router.get("/templates/{kind}.csv")
def template(kind: Kind, _: CurrentUser = Depends(any_user)) -> Response:
    return Response(TEMPLATES[kind], media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={kind}-template.csv"})


@router.post("/{kind}")
async def upload(
    kind: Kind,
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
    date_format: str = Form("auto"),
    password: str = Form("", max_length=200),     # PDF statements only; never stored or logged
    account_id: int | None = Form(None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(staff),
) -> dict:
    import_limiter.check(f"import|{user.id}")
    limit = get_settings().max_upload_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, f"Files are limited to {get_settings().max_upload_mb} MB")
    name = (file.filename or "upload.csv").replace("\\", "/").split("/")[-1]
    try:
        # Parsing (especially PDF) is CPU work: keep it off the event loop.
        report = await run_in_threadpool(run_import, db, user.business_id, user.id, kind, name, content,
                                         dry_run=dry_run, date_format=date_format, password=password,
                                         account_id=account_id)
    except ImportFileError as e:
        raise HTTPException(422, str(e))
    if not dry_run:
        audit.record(db, action="data.imported", actor=user.label, actor_type="user", business_id=user.business_id,
                     tool=kind, params={"file": name, "batch": report.batch_id},
                     result=f"{report.imported} imported, {report.updated} updated, {report.duplicates} duplicates, "
                            f"{report.rejected} rejected")
    return report.to_dict()


@router.get("/history")
def history(db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> list[dict]:
    rows = db.scalars(select(models.ImportBatch).where(models.ImportBatch.BusinessId == user.business_id)
                      .order_by(models.ImportBatch.Id.desc()).limit(50))
    return [{"id": b.Id, "kind": b.Kind, "fileName": b.FileName, "rowsTotal": b.RowsTotal,
             "imported": b.RowsImported, "duplicates": b.RowsDuplicate, "rejected": b.RowsRejected,
             "errors": json.loads(b.ErrorsJson or "[]")[:20],
             "createdAt": b.CreatedAt.isoformat(timespec="seconds") + "Z"} for b in rows]
