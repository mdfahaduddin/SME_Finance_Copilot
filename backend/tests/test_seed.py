"""Sanity checks on the synthetic sandbox data the demo and engines rely on."""
from datetime import timedelta

from sqlalchemy import func, select

from app import models
from app.security import verify_password
from seed.generator import CHECKING_TARGET_BALANCE, INJECTION_MEMO, generate
from tests.conftest import AS_OF


def test_generation_is_deterministic():
    a, b = generate(AS_OF), generate(AS_OF)
    assert len(a.transactions) == len(b.transactions)
    assert [t.Amount for t in a.transactions[:200]] == [t.Amount for t in b.transactions[:200]]


def test_ledger_reconciles_to_account_balance(db):
    signed = db.scalar(
        select(func.sum(
            func.iif(models.SmeTransaction.Direction == "in", models.SmeTransaction.Amount,
                     -models.SmeTransaction.Amount)
        )).where(models.SmeTransaction.AccountId == 1)
    )
    assert round(signed, 2) == CHECKING_TARGET_BALANCE
    assert db.get(models.SmeBankAccount, 1).Balance == CHECKING_TARGET_BALANCE


def test_history_never_overdrawn():
    data = generate(AS_OF)
    balance = 0.0
    for t in data.transactions:
        balance += t.Amount if t.Direction == "in" else -t.Amount
        assert balance >= 0, f"overdrawn on {t.TxnDate}"


def test_no_transactions_after_as_of(db):
    latest = db.scalar(select(func.max(models.SmeTransaction.TxnDate)))
    assert latest <= AS_OF


def test_revenue_is_realistic_sme_scale():
    revenue = generate(AS_OF).business.AnnualRevenue
    assert 900_000 < revenue < 1_500_000


def test_story_points_present(db):
    open_invoices = db.scalars(select(models.SmeInvoice).where(models.SmeInvoice.Status == "open")).all()
    riverside_overdue = [i for i in open_invoices
                         if i.Customer == "Riverside Hotel Group" and (AS_OF - i.DueDate).days > 30]
    assert riverside_overdue, "Riverside should have an invoice more than 30 days overdue"

    upcoming = db.scalars(select(models.SmeBill).where(
        models.SmeBill.Status == "open", models.SmeBill.DueDate <= AS_OF + timedelta(days=60))).all()
    assert any(b.Vendor == "SafeHarbor Insurance" and b.Amount >= 9_000 for b in upcoming)
    assert any(b.Vendor == "Golden Mill Flour Co." and b.Amount >= 10_000 for b in upcoming)

    assert db.scalar(select(func.count()).select_from(models.SmeInvoice)
                     .where(models.SmeInvoice.Memo == INJECTION_MEMO)) == 1


def test_paid_invoices_have_matching_transactions(db):
    paid = db.scalars(select(models.SmeInvoice).where(
        models.SmeInvoice.Status == "paid", models.SmeInvoice.PaidDate >= AS_OF - timedelta(days=365))).all()
    linked = set(db.scalars(select(models.SmeTransaction.InvoiceId)
                            .where(models.SmeTransaction.InvoiceId.is_not(None))).all())
    assert paid and all(i.Id in linked for i in paid)


def test_demo_users_and_roles(db):
    users = {u.Role: u for u in db.scalars(select(models.SmeUser)).all()}
    assert set(users) == {"owner", "accountant", "viewer"}
    assert verify_password("Owner#2026", users["owner"].PasswordHash)
    assert not verify_password("wrong", users["owner"].PasswordHash)


def test_product_catalogue(db):
    products = db.scalars(select(models.FinProduct)).all()
    assert len(products) >= 12
    assert {p.ProductType for p in products} >= {
        "term_loan", "credit_line", "invoice_finance", "equipment", "merchant_advance", "gov_grant"}
    assert all(p.MinAmount <= p.MaxAmount and p.AprMin <= p.AprMax for p in products)


def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
