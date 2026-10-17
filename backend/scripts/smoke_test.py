"""End-to-end smoke test against the configured database (e.g. PostgreSQL after `alembic upgrade head`).

    DATABASE_URL=postgresql://... python -m scripts.smoke_test

Registers a throwaway business, adds an account, imports transactions, loads the dashboard and
financing, signs out. Exits non-zero on the first failure. Safe on a real database: it only creates
one uniquely named test business (delete it afterwards if you run this against production).
"""
from __future__ import annotations

import sys
import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app


def main() -> None:
    c = TestClient(app)
    tag = uuid.uuid4().hex[:8]

    def check(label: str, r, status: int = 200):
        ok = r.status_code == status
        print(f"[{'PASS' if ok else 'FAIL'}] {label} -> {r.status_code}")
        if not ok:
            print(r.text[:500])
            sys.exit(1)
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text

    check("ready", c.get("/api/ready"))
    check("register", c.post("/api/auth/register", json={
        "businessName": f"Smoke Test {tag}", "industry": "Retail", "region": "", "foundedDate": "2021-01-01",
        "employees": 3, "currency": "USD", "fullName": "Smoke Tester", "email": f"smoke-{tag}@example.com",
        "password": "a long smoke test password", "acceptTerms": True}), 201)
    h = {"X-CSRF-Token": c.cookies.get("sme_csrf")}
    check("add account", c.post("/api/business/accounts", json={"name": "Main", "accountType": "checking",
                                                                 "last4": "1234", "balance": 12000}, headers=h), 201)
    end = date.today() - timedelta(days=1)
    rows = ["date,description,amount"] + [
        f"{(end - timedelta(days=7 * i)).isoformat()},Card sales,{1800 + i * 3}" for i in range(30)] + [
        f"{(end - timedelta(days=30 * i)).replace(day=1).isoformat()},Rent,-1500" for i in range(7)]
    report = check("import transactions", c.post("/api/import/transactions", headers=h, data={"dry_run": "false"},
                                                 files={"file": ("bank.csv", "\n".join(rows).encode())}))
    assert report["imported"] == 37, report
    dash = check("dashboard", c.get("/api/dashboard/summary"))
    assert dash["healthScore"]["score"] is not None
    check("financing", c.post("/api/financing/match", json={"amount": 20000, "purpose": "working_capital"}, headers=h))
    check("audit verify", c.get("/api/audit/verify"))
    check("logout", c.post("/api/auth/logout", headers=h))
    check("signed out", c.get("/api/auth/me"), 401)
    print("Smoke test passed.")


if __name__ == "__main__":
    main()
