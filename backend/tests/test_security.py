"""Security & compliance: RBAC, human-in-the-loop approvals, limits, audit chain integrity.

Each test gets a fresh database (`client` fixture) because these tests change data.
"""
from datetime import timedelta

from sqlalchemy import select, text, update

from app import models
from app.models import utcnow
from tests.conftest import AS_OF


def _open_invoice(client, h, customer="Riverside Hotel Group"):
    invs = client.get("/api/ledger/invoices", headers=h).json()
    return next(i for i in invs if i["customer"] == customer)


def _bill(client, h, predicate):
    """An open bill not yet due (so its due date is a valid payment date)."""
    bills = client.get("/api/ledger/bills?status=open", headers=h).json()
    return next(b for b in bills if b["dueDate"] > str(AS_OF) and predicate(b))


def _audit_actions(client) -> list[str]:
    with client.session() as s:
        return list(s.scalars(select(models.AuditLog.Action).order_by(models.AuditLog.Id)))


# ---- RBAC --------------------------------------------------------------------

def test_viewer_is_read_only(client):
    v = client.as_role("viewer")
    inv = _open_invoice(client, v)
    r = client.post("/api/approvals", json={"tool": "send_payment_reminder", "params": {"invoiceNo": inv["invoiceNo"]}},
                    headers=v)
    assert r.status_code == 403
    alert_id = client.get("/api/alerts", headers=v).json()[0]["id"]
    assert client.post(f"/api/alerts/{alert_id}/ack", headers=v).status_code == 403
    assert client.get("/api/audit", headers=v).status_code == 403


def test_accountant_can_request_and_approve_reminders(client):
    a = client.as_role("accountant")
    inv = _open_invoice(client, a)
    r = client.post("/api/approvals", json={"tool": "send_payment_reminder",
                                            "params": {"invoice_no": inv["invoiceNo"], "tone": "firm"}}, headers=a)
    assert r.status_code == 201
    req = r.json()
    assert req["status"] == "pending" and req["amount"] == inv["amount"] and not req["requiresReauth"]
    done = client.post(f"/api/approvals/{req['id']}/approve", json={}, headers=a).json()
    assert done["status"] == "executed"
    outbox = client.get("/api/ledger/outbox", headers=a).json()
    assert outbox[0]["subject"] == f"Payment reminder: {inv['invoiceNo']}"
    assert outbox[0]["recipient"].endswith(".example")
    assert ["action.requested", "action.approved", "action.executed"] == \
        [x for x in _audit_actions(client) if x.startswith("action.")]


def test_only_owner_can_approve_payments(client):
    a, o = client.as_role("accountant"), client.as_role("owner")
    bill = _bill(client, a, lambda b: b["amount"] < 5_000)
    req = client.post("/api/approvals", json={"tool": "schedule_payment",
                                              "params": {"billId": bill["id"], "payDate": bill["dueDate"]}},
                      headers=a).json()
    r = client.post(f"/api/approvals/{req['id']}/approve", json={}, headers=a)
    assert r.status_code == 403
    assert "action.approve_denied" in _audit_actions(client)
    done = client.post(f"/api/approvals/{req['id']}/approve", json={}, headers=o).json()
    assert done["status"] == "executed"
    scheduled = client.get("/api/ledger/bills?status=scheduled", headers=o).json()
    assert [b["id"] for b in scheduled] == [bill["id"]]


# ---- Human-in-the-loop safeguards ---------------------------------------------

def test_large_actions_require_password_confirmation(client):
    o = client.as_role("owner")
    product = next(p for p in client.get("/api/financing/products", headers=o).json() if p["type"] == "equipment")
    req = client.post("/api/approvals", json={"tool": "submit_loan_application", "params": {
        "productId": product["id"], "amount": 45_000, "termMonths": 60, "purpose": "New deck oven"}},
        headers=o).json()
    assert req["requiresReauth"] and req["riskLevel"] == "high"
    assert client.post(f"/api/approvals/{req['id']}/approve", json={}, headers=o).status_code == 403
    assert client.post(f"/api/approvals/{req['id']}/approve", json={"password": "wrong"}, headers=o).status_code == 403
    assert _audit_actions(client).count("action.reauth_failed") == 2
    done = client.post(f"/api/approvals/{req['id']}/approve", json={"password": "Owner#2026"}, headers=o).json()
    assert done["status"] == "executed" and done["result"]["referenceNo"]
    apps = client.get("/api/ledger/loan-applications", headers=o).json()
    assert apps[0]["status"] == "submitted" and apps[0]["referenceNo"] == done["result"]["referenceNo"]


def test_request_cannot_be_decided_twice(client):
    o = client.as_role("owner")
    inv = _open_invoice(client, o)
    req = client.post("/api/approvals", json={"tool": "send_payment_reminder", "params": {"invoiceNo": inv["invoiceNo"]}},
                      headers=o).json()
    assert client.post(f"/api/approvals/{req['id']}/approve", json={}, headers=o).status_code == 200
    assert client.post(f"/api/approvals/{req['id']}/approve", json={}, headers=o).status_code == 409
    assert client.post(f"/api/approvals/{req['id']}/reject", json={}, headers=o).status_code == 409
    assert len(client.get("/api/ledger/outbox", headers=o).json()) == 1  # executed exactly once


def test_reject_and_idempotent_requests(client):
    o = client.as_role("owner")
    inv = _open_invoice(client, o)
    body = {"tool": "send_payment_reminder", "params": {"invoiceNo": inv["invoiceNo"]}}
    first = client.post("/api/approvals", json=body, headers=o).json()
    second = client.post("/api/approvals", json=body, headers=o).json()
    assert first["id"] == second["id"]  # duplicate pending request is not created
    r = client.post(f"/api/approvals/{first['id']}/reject", json={"reason": "Will call them"}, headers=o).json()
    assert r["status"] == "rejected" and r["decisionReason"] == "Will call them"
    assert client.get("/api/ledger/outbox", headers=o).json() == []


def test_requests_expire(client):
    o = client.as_role("owner")
    inv = _open_invoice(client, o)
    req = client.post("/api/approvals", json={"tool": "send_payment_reminder", "params": {"invoiceNo": inv["invoiceNo"]}},
                      headers=o).json()
    with client.session() as s:
        s.execute(update(models.AgentActionRequest).values(ExpiresAt=utcnow() - timedelta(minutes=1)))
        s.commit()
    assert client.post(f"/api/approvals/{req['id']}/approve", json={}, headers=o).status_code == 409
    assert client.get("/api/approvals?status=expired", headers=o).json()[0]["id"] == req["id"]


# ---- Limits and validation ------------------------------------------------------

def test_payment_limits(client):
    o = client.as_role("owner")
    big = _bill(client, o, lambda b: b["amount"] > 10_000)  # bulk flour order
    r = client.post("/api/approvals", json={"tool": "schedule_payment",
                                            "params": {"billId": big["id"], "payDate": big["dueDate"]}}, headers=o)
    assert r.status_code == 403 and "limit" in r.json()["detail"]

    total, refused = 0.0, False
    for b in client.get("/api/ledger/bills?status=open", headers=o).json():
        if b["amount"] > 10_000 or b["dueDate"] <= str(AS_OF):
            continue
        r = client.post("/api/approvals", json={"tool": "schedule_payment",
                                                "params": {"billId": b["id"], "payDate": b["dueDate"]}}, headers=o)
        if r.status_code == 403:
            refused = True
            break
        total += b["amount"]
    assert refused and total <= 25_000


def test_action_parameter_validation(client):
    o = client.as_role("owner")
    cases = [
        {"tool": "transfer_funds", "params": {"to": "99887766", "amount": 5000}},  # not an available action
        {"tool": "send_payment_reminder", "params": {"invoiceNo": "'; DROP TABLE SmeInvoice;--"}},
        {"tool": "send_payment_reminder", "params": {"invoiceNo": "INV-999999"}},  # does not exist
        {"tool": "schedule_payment", "params": {"billId": 1, "payDate": "2026-12-01"}},  # already paid
    ]
    for body in cases:
        r = client.post("/api/approvals", json=body, headers=o)
        assert r.status_code in (400, 403, 404), (body, r.status_code, r.text)
    bill = _bill(client, o, lambda b: b["amount"] < 5_000)
    past = client.post("/api/approvals", json={"tool": "schedule_payment",
                                               "params": {"billId": bill["id"], "payDate": "2020-01-01"}}, headers=o)
    assert past.status_code == 400


def test_amount_comes_from_records_not_request(client):
    o = client.as_role("owner")
    bill = _bill(client, o, lambda b: b["amount"] < 5_000)
    r = client.post("/api/approvals", json={"tool": "schedule_payment", "params": {
        "billId": bill["id"], "payDate": bill["dueDate"], "amount": 1}}, headers=o)
    assert r.status_code == 400  # unknown 'amount' parameter is refused, never trusted


def test_login_rate_limited(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "owner@lotusbakery.example", "password": "guess"})
    r = client.post("/api/auth/login", json={"email": "owner@lotusbakery.example", "password": "Owner#2026"})
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert _audit_actions(client).count("auth.login_failed") == 5


# ---- Audit chain -----------------------------------------------------------------

def test_audit_chain_valid_and_detects_tampering(client):
    o = client.as_role("owner")
    inv = _open_invoice(client, o)
    req = client.post("/api/approvals", json={"tool": "send_payment_reminder", "params": {"invoiceNo": inv["invoiceNo"]}},
                      headers=o).json()
    client.post(f"/api/approvals/{req['id']}/approve", json={}, headers=o)
    ok = client.get("/api/audit/verify", headers=o).json()
    assert ok["valid"] and ok["records"] >= 4

    with client.session() as s:
        target_id = s.scalar(select(models.AuditLog.Id).where(models.AuditLog.Action == "action.approved"))
        s.execute(text("UPDATE AuditLog SET Decision = 'rejected' WHERE Id = :id"), {"id": target_id})
        s.commit()
    bad = client.get("/api/audit/verify", headers=o).json()
    assert not bad["valid"] and bad["brokenAtId"] == target_id


def test_audit_detects_deleted_record(client):
    o = client.as_role("owner")
    client.as_role("accountant")  # a second login record
    client.post("/api/scenarios/run", json={"changes": []}, headers=o)
    with client.session() as s:
        first_id = s.scalar(select(models.AuditLog.Id).order_by(models.AuditLog.Id))
        s.execute(text("DELETE FROM AuditLog WHERE Id = :id"), {"id": first_id})
        s.commit()
    assert client.get("/api/audit/verify", headers=o).json()["valid"] is False


def test_audit_log_holds_no_customer_pii(client):
    o = client.as_role("owner")
    inv = _open_invoice(client, o)
    req = client.post("/api/approvals", json={"tool": "send_payment_reminder", "params": {"invoiceNo": inv["invoiceNo"]}},
                      headers=o).json()
    client.post(f"/api/approvals/{req['id']}/approve", json={}, headers=o)
    with client.session() as s:
        emails = set(s.scalars(select(models.SmeInvoice.CustomerEmail)))
        log_text = " ".join(f"{r.ResultSummary} {r.Actor}" for r in s.scalars(select(models.AuditLog)))
    assert not any(e in log_text for e in emails)


def test_audit_export(client):
    o = client.as_role("owner")
    csv_body = client.get("/api/audit/export?format=csv", headers=o)
    assert csv_body.status_code == 200 and csv_body.text.startswith("id,")
    js = client.get("/api/audit/export?format=json", headers=o).json()
    assert js["chain"]["valid"] and js["records"]
