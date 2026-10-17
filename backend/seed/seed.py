"""Create the database schema and load the demo SME.

Usage (from backend/):
    python -m seed.seed                    # as_of = today
    python -m seed.seed --as-of 2026-10-13

DEVELOPMENT ONLY. This drops and recreates every table and loads the fictional demo
business with public demo logins. It refuses to run when APP_ENV=production, and
against non-SQLite databases unless --force is given. Production databases are
managed with Alembic (alembic upgrade head) plus `python -m app.cli seed-products`.
"""
import argparse
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models  # noqa: F401  (registers tables)
from app.config import get_settings
from app.db import Base, engine
from seed.generator import SeedData, generate


def load(session: Session, data: SeedData) -> None:
    session.add(data.business)
    session.flush()
    session.add_all(data.users)
    session.add_all(data.accounts)
    session.add_all(data.products)
    session.flush()
    session.add_all(data.invoices)
    session.add_all(data.bills)
    session.flush()
    session.add_all(data.transactions)
    session.add_all(data.loans)
    session.commit()


def stamp_head(bind) -> None:
    """Record the schema as the latest migration, so a later `alembic upgrade head` applies only newer ones.

    create_all builds the current schema directly; without this stamp Alembic would think the database is empty
    and try to create every table again.
    """
    from pathlib import Path

    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")))
    with bind.begin() as conn:
        # The version table is not in the models, so drop_all leaves an old version behind: start it afresh.
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        MigrationContext.configure(conn).stamp(script, "head")


def reset_and_seed(as_of: date | None = None, seed: int = 42, bind=engine) -> SeedData:
    Base.metadata.drop_all(bind)
    Base.metadata.create_all(bind)
    stamp_head(bind)
    data = generate(as_of=as_of, seed=seed)
    with Session(bind, expire_on_commit=False) as session:
        load(session, data)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset and seed the sandbox database.")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None, help="Reference date (YYYY-MM-DD)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true", help="Allow a non-SQLite database URL")
    args = parser.parse_args()

    settings = get_settings()
    url = settings.database_url
    if settings.is_production:
        raise SystemExit("The demo seed wipes the database and is disabled when APP_ENV=production.")
    if not url.startswith("sqlite") and not args.force:
        raise SystemExit("Refusing to reset a non-SQLite database. Use --force if intended (development only).")

    data = reset_and_seed(args.as_of, args.seed)
    print(f"Seeded '{data.business.Name}' into {url}")
    print(f"  transactions: {len(data.transactions)}  invoices: {len(data.invoices)}  "
          f"bills: {len(data.bills)}  products: {len(data.products)}  users: {len(data.users)}")
    print(f"  trailing-12m revenue: ${data.business.AnnualRevenue:,.0f}")


if __name__ == "__main__":
    main()
