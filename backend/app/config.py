"""Application settings, read from environment variables (or backend/.env in development).

APP_ENV controls how strict the settings are:
  development  defaults that work out of the box (SQLite, random secret, in-memory rate limits)
  test         like development, used by the test suite
  production   fails fast at startup unless SECRET_KEY, a PostgreSQL DATABASE_URL and the public
               origin are configured; cookies are Secure; logs are JSON
"""
import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"

    # LLM
    openai_api_key: str = ""
    openai_model: str = "gpt-6-luna"

    # Database / cache
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'smecopilot.db').as_posix()}"
    redis_url: str = ""  # empty -> in-memory rate limiting (single process only)

    # Security
    # SECRET_KEY signs CSRF tokens and encrypts MFA secrets. JWT_SECRET is accepted for older .env files.
    secret_key: str = Field("", validation_alias=AliasChoices("SECRET_KEY", "JWT_SECRET"))
    session_idle_minutes: int = 60       # sign out after this much inactivity
    session_absolute_hours: int = 12     # and always after this long
    cookie_secure: bool | None = None    # default: True in production
    password_min_length: int = 10

    # Public URLs
    public_base_url: str = "http://localhost:5500"  # used in emailed links
    cors_origins: str = "http://localhost:5500"

    # Email (password reset, team invites). Empty SMTP_HOST -> emails are written to the log instead.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "SME Finance Copilot <no-reply@localhost>"
    smtp_starttls: bool = True

    # Operations
    log_level: str = "INFO"
    log_json: bool | None = None         # default: True in production
    sentry_dsn: str = ""
    max_upload_mb: int = 5

    # Indicative exchange rates (units per 1 USD) as JSON, merged over the built-in table in app/fx.py.
    fx_rates: str = ""

    # OCR for scanned PDF statements (local Tesseract; installed in the Docker image)
    ocr_enabled: bool = True
    tesseract_cmd: str = "tesseract"     # full path on Windows, e.g. C:/Program Files/Tesseract-OCR/tesseract.exe
    ocr_languages: str = "eng"           # Tesseract language packs, e.g. "eng+ben"
    ocr_concurrency: int = 2             # pages OCR'd at once per API process
    ocr_max_pages: int = 30

    # Finance
    # Minimum cash cushion, in weeks of average operating outflows.
    safety_buffer_weeks: float = 1.0

    @model_validator(mode="after")
    def _harden(self) -> "Settings":
        # Relative SQLite paths resolve against backend/, regardless of the working directory.
        prefix = "sqlite:///./"
        if self.database_url.startswith(prefix):
            self.database_url = f"sqlite:///{(BACKEND_DIR / self.database_url[len(prefix):]).as_posix()}"
        # SQLAlchemy needs the psycopg 3 driver name for PostgreSQL URLs.
        for old in ("postgres://", "postgresql://"):
            if self.database_url.startswith(old):
                self.database_url = "postgresql+psycopg://" + self.database_url[len(old):]

        weak = len(self.secret_key) < 32 or self.secret_key.startswith("change-me")
        if self.is_production:
            problems = []
            if weak:
                problems.append("SECRET_KEY must be at least 32 random characters")
            if not self.database_url.startswith("postgresql"):
                problems.append("DATABASE_URL must point to PostgreSQL")
            if self.public_base_url.startswith("http://"):
                problems.append("PUBLIC_BASE_URL must use https://")
            if problems:
                raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        elif weak:
            logging.getLogger("uvicorn.error").warning(
                "SECRET_KEY missing or shorter than 32 chars - using a random per-process key (development only).")
            self.secret_key = secrets.token_urlsafe(48)

        if self.cookie_secure is None:
            self.cookie_secure = self.is_production
        if self.log_json is None:
            self.log_json = self.is_production
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
