"""Operational commands.

    python -m app.cli seed-products     load / update the lender product catalogue (idempotent)
    python -m app.cli prune             delete expired sessions and one-time tokens (run daily)
    python -m app.cli check             print configuration and database status (no secrets)
"""
from __future__ import annotations

import argparse
from datetime import timedelta

from sqlalchemy import delete, or_, select, text
from sqlalchemy.orm import Session

from app import models, ocr
from app.config import get_settings
from app.db import engine
from app.models import utcnow
from seed.products import PRODUCTS


def seed_products(session: Session) -> tuple[int, int]:
    """Insert new products and update existing ones, matched by (Lender, Name)."""
    existing = {(p.Lender, p.Name): p for p in session.scalars(select(models.FinProduct))}
    added = updated = 0
    for data in PRODUCTS:
        row = existing.get((data["Lender"], data["Name"]))
        if row is None:
            session.add(models.FinProduct(**data))
            added += 1
        else:
            for k, v in data.items():
                setattr(row, k, v)
            updated += 1
    session.commit()
    return added, updated


def prune(session: Session) -> tuple[int, int]:
    now = utcnow()
    s = session.execute(delete(models.UserSession).where(or_(
        models.UserSession.ExpiresAt < now - timedelta(days=1),
        models.UserSession.RevokedAt < now - timedelta(days=30)))).rowcount
    t = session.execute(delete(models.AuthToken).where(models.AuthToken.ExpiresAt < now - timedelta(days=30))).rowcount
    session.commit()
    return s or 0, t or 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["seed-products", "prune", "check"])
    args = parser.parse_args()
    with Session(engine) as session:
        if args.command == "seed-products":
            added, updated = seed_products(session)
            print(f"Product catalogue: {added} added, {updated} updated")
        elif args.command == "prune":
            s, t = prune(session)
            print(f"Pruned {s} sessions and {t} tokens")
        else:
            st = get_settings()
            session.execute(text("SELECT 1"))
            print(f"env={st.app_env} db={engine.url.render_as_string(hide_password=True)} "
                  f"redis={'on' if st.redis_url else 'off'} llm={'on' if st.llm_enabled else 'off'} "
                  f"email={'smtp' if st.email_enabled else 'log'} sentry={'on' if st.sentry_dsn else 'off'} "
                  f"ocr={'on' if ocr.available() else 'off'}")


if __name__ == "__main__":
    main()
