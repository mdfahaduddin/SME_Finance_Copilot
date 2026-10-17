from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.ratelimit import ALL_LIMITERS
from seed.seed import reset_and_seed

AS_OF = date(2026, 10, 13)


@pytest.fixture(autouse=True, scope="session")
def _no_network_llm():
    """Never call the real LLM provider from tests (even if backend/.env has a key)."""
    from app.agent.llm import force_offline, set_llm_override
    force_offline(True)
    yield
    set_llm_override(None)


PASSWORDS = {"owner": "Owner#2026", "accountant": "Accountant#2026", "viewer": "Viewer#2026"}


def seeded_engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    reset_and_seed(as_of=AS_OF, bind=eng)
    return eng


@pytest.fixture(scope="session")
def engine():
    """Read-only seeded database shared by engine tests. Do not mutate."""
    return seeded_engine()


@pytest.fixture()
def db(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture(scope="session")
def ledger(engine):
    """The seeded demo business loaded for the engines."""
    from app.engines.ledger import load_ledger
    with Session(engine) as s:
        return load_ledger(s, 1)


class ApiClient(TestClient):
    """TestClient bound to its own fresh database, with role login helpers."""

    def __init__(self, eng):
        super().__init__(app)
        self.engine = eng
        self._tokens: dict[str, str] = {}

    def as_role(self, role: str) -> dict:
        if role not in self._tokens:
            r = self.post("/api/auth/login", json={"email": f"{role}@lotusbakery.example", "password": PASSWORDS[role]})
            assert r.status_code == 200, r.text
            # The session token arrives only as an HttpOnly cookie; tests send it as a bearer token so
            # several roles can be used side by side (bearer requests need no CSRF header).
            self._tokens[role] = r.cookies["sme_session"]
            self.cookies.clear()
        return {"Authorization": f"Bearer {self._tokens[role]}"}

    def session(self) -> Session:
        return Session(self.engine)


def _client_for(eng):
    factory = sessionmaker(bind=eng, expire_on_commit=False)

    def _get_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db
    for limiter in ALL_LIMITERS:
        limiter.reset()
    return ApiClient(eng)


@pytest.fixture()
def client():
    """Fresh database per test: safe for tests that approve actions or tamper with data."""
    c = _client_for(seeded_engine())
    yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def ro_client():
    """One database per module, for read-only API tests (faster)."""
    c = _client_for(seeded_engine())
    yield c
    app.dependency_overrides.clear()
