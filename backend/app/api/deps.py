"""Shared helpers for API routers."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.config import get_settings
from app.engines.ledger import Ledger, load_ledger


class CamelModel(BaseModel):
    """Request bodies accept camelCase (frontend) or snake_case."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


def user_ledger(db: Session, user: CurrentUser) -> Ledger:
    # Always scoped to the caller's own business - never taken from the request.
    return load_ledger(db, user.business_id)


def buffer_weeks() -> float:
    return get_settings().safety_buffer_weeks


def mask_account(number: str) -> str:
    digits = number.replace("-", "")
    return f"****{digits[-4:]}" if len(digits) >= 4 else "****"
