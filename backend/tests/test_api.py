"""Read-only API behaviour: authentication, response shapes, validation. (Shared database per module.)"""
import pytest


PROTECTED = [
    ("get", "/api/dashboard/summary"), ("get", "/api/analysis"), ("get", "/api/cashflow/forecast"),
    ("get", "/api/alerts"), ("get", "/api/financing/products"), ("get", "/api/ledger/transactions"),
    ("get", "/api/ledger/invoices"), ("get", "/api/approvals"), ("get", "/api/audit"),
    ("post", "/api/scenarios/run"), ("post", "/api/financing/match"), ("post", "/api/approvals"),
]


def test_health_is_public(ro_client):
    assert ro_client.get("/api/health").json()["status"] == "ok"
    ready = ro_client.get("/api/ready").json()
    assert ready["status"] == "ready" and ready["productCatalog"] is True


@pytest.mark.parametrize("method,path", PROTECTED)
def test_endpoints_require_authentication(ro_client, method, path):
    assert getattr(ro_client, method)(path).status_code == 401


def test_login_and_me(ro_client):
    r = ro_client.post("/api/auth/login", json={"email": "Owner@LotusBakery.example", "password": "Owner#2026"})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "owner" and body["mfaRequired"] is False
    assert "accessToken" not in body  # the session token never appears in a response body
    me = ro_client.get("/api/auth/me")  # cookie sent automatically
    assert me.status_code == 200 and me.json()["email"] == "owner@lotusbakery.example"
    ro_client.cookies.clear()


def test_login_failure_does_not_reveal_which_part_was_wrong(ro_client):
    wrong_pw = ro_client.post("/api/auth/login", json={"email": "viewer@lotusbakery.example", "password": "nope"})
    no_user = ro_client.post("/api/auth/login", json={"email": "ghost@lotusbakery.example", "password": "nope"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


def test_unknown_and_tampered_tokens_rejected(ro_client):
    good = ro_client.as_role("viewer")["Authorization"].split()[1]
    for bad in (good[:-4] + ("AAAA" if not good.endswith("AAAA") else "BBBB"), "x" * 43, ""):
        assert ro_client.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_dashboard_summary(ro_client):
    r = ro_client.get("/api/dashboard/summary", headers=ro_client.as_role("viewer"))
    assert r.status_code == 200
    d = r.json()
    assert 0 <= d["healthScore"]["score"] <= 100
    assert len(d["forecast"]["weeks"]) == 13
    assert d["forecast"]["summary"]["lowestWeek"] == 7
    assert d["alerts"] and d["alerts"][0]["severity"] in {"critical", "high"}
    # Account numbers are masked.
    assert all(a["number"].startswith("****") for a in d["accounts"])
    assert "4401-2093" not in r.text


def test_forecast_parameter_validation(ro_client):
    h = ro_client.as_role("viewer")
    assert ro_client.get("/api/cashflow/forecast?weeks=26", headers=h).status_code == 200
    assert ro_client.get("/api/cashflow/forecast?weeks=200", headers=h).status_code == 422
    items = ro_client.get("/api/cashflow/forecast?items=true", headers=h).json()["items"]
    assert {"open_invoice", "open_bill", "recurring", "retail_baseline"} <= {i["source"] for i in items}


def test_scenario_endpoint(ro_client):
    h = ro_client.as_role("viewer")
    body = {"changes": [{"type": "one_off_expense", "amount": 45000, "week": 6, "label": "Oven"}]}
    r = ro_client.post("/api/scenarios/run", json=body, headers=h)
    assert r.status_code == 200 and r.json()["verdict"].startswith("Not affordable")
    loan = {"type": "new_loan", "amount": 45000, "apr": 0.095, "termMonths": 60, "week": 6}  # camelCase accepted
    r = ro_client.post("/api/scenarios/run", json={"changes": [body["changes"][0], loan]}, headers=h)
    assert r.json()["scenario"]["firstNegativeWeek"] is None


@pytest.mark.parametrize("change", [
    {"type": "steal_money", "amount": 1},                             # unknown type
    {"type": "one_off_expense", "amount": -5},                        # negative
    {"type": "one_off_expense", "amount": 5, "sql": "DROP TABLE x"},  # extra field
    {"type": "delay_customer", "customer": "X", "days": 9999},        # out of range
])
def test_scenario_validation(ro_client, change):
    r = ro_client.post("/api/scenarios/run", json={"changes": [change]}, headers=ro_client.as_role("viewer"))
    assert r.status_code == 422


def test_financing_match(ro_client):
    h = ro_client.as_role("viewer")
    r = ro_client.post("/api/financing/match", json={"useForecast": True}, headers=h).json()
    assert r["need"]["purpose"] == "bridge" and r["eligible"][0]["rank"] == 1
    r = ro_client.post("/api/financing/match", json={"amount": 45000, "purpose": "equipment"}, headers=h).json()
    assert r["eligible"][0]["type"] == "equipment"
    assert ro_client.post("/api/financing/match", json={"purpose": "equipment"}, headers=h).status_code == 422
    assert ro_client.post("/api/financing/match", json={"amount": 5, "purpose": "yacht"}, headers=h).status_code == 422


def test_ledger_endpoints(ro_client):
    h = ro_client.as_role("viewer")
    tx = ro_client.get("/api/ledger/transactions?limit=10&direction=out", headers=h).json()["items"]
    assert len(tx) == 10 and all(t["direction"] == "out" for t in tx)
    invoices = ro_client.get("/api/ledger/invoices", headers=h).json()
    assert all(i["status"] == "open" for i in invoices)
    # The planted prompt-injection memo is returned as plain data, never acted on.
    assert any("ignore all previous instructions" in i["memo"].lower() for i in invoices)
    bills = ro_client.get("/api/ledger/bills", headers=h).json()
    assert bills and all(b["status"] != "paid" for b in bills)


def test_security_headers(ro_client):
    r = ro_client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store"


def test_oversized_body_rejected(ro_client):
    r = ro_client.post("/api/scenarios/run", content=b"x" * 300_000, headers={
        **ro_client.as_role("viewer"), "Content-Type": "application/json"})
    assert r.status_code == 413


def test_policy_reports_enforced_limits(ro_client):
    from app import actions
    from app.agent.orchestrator import MAX_ACTIONS_PER_TURN
    p = ro_client.get("/api/policy", headers=ro_client.as_role("viewer")).json()
    assert p["reauthThreshold"] == actions.REAUTH_THRESHOLD
    assert p["schedulePaymentMax"] == actions.SCHEDULE_PAYMENT_MAX
    assert p["agent"]["maxActionsPerTurn"] == MAX_ACTIONS_PER_TURN
    assert p["roleTiers"]["viewer"] == ["T0", "T1"]
    assert p["approverRoles"]["submit_loan_application"] == ["owner"]
    assert len(p["tools"]) == 15


def test_single_approval_lookup_is_scoped(ro_client):
    h = ro_client.as_role("viewer")
    assert ro_client.get("/api/approvals/999999", headers=h).status_code == 404
