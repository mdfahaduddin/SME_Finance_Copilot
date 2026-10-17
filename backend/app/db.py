from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
        return engine
    # PostgreSQL: a small pool per worker; pre-ping drops connections the server closed.
    return create_engine(url, pool_size=5, max_overflow=10, pool_pre_ping=True, pool_recycle=1800)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def schema_problems(bind=None) -> list[str]:
    """Tables/columns the code expects but the database lacks (e.g. an old local DB after an upgrade)."""
    from sqlalchemy import inspect

    from app import models  # noqa: F401  (registers tables)

    insp = inspect(bind or engine)
    existing = set(insp.get_table_names())
    problems = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            problems.append(f"table {table.name}")
            continue
        cols = {c["name"] for c in insp.get_columns(table.name)}
        problems += [f"{table.name}.{c.name}" for c in table.columns if c.name not in cols]
    return problems


SCHEMA_FIX = ("Run `alembic upgrade head` (production / PostgreSQL), or for a local demo database "
              "`python -m seed.seed` (recreates it with demo data).")


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
