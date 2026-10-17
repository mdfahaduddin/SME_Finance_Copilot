import pandas as pd
import pytest

from app.engines.forecast import aggregate, build_context, build_items, forecast
from tests.factories import AS_OF, LedgerBuilder, daily_retail


def _items(b: LedgerBuilder, source: str | None = None):
    ledger = b.build()
    ctx = build_context(ledger)
    items = build_items(ledger, ctx)
    return [i for i in items if source is None or i.source == source], ctx


def test_open_invoice_expected_on_due_date_plus_customer_delay():
    b = LedgerBuilder()
    for k in range(4):  # history: always pays 10 days late
        due = AS_OF - pd.Timedelta(days=200 - 30 * k)
        b.invoice("Acme", due - pd.Timedelta(days=30), due, 500, "paid", due + pd.Timedelta(days=10))
    b.invoice("Acme", AS_OF - pd.Timedelta(days=10), AS_OF + pd.Timedelta(days=20), 2_000)
    items, _ = _items(b, "open_invoice")
    assert len(items) == 1
    assert items[0].date == AS_OF + pd.Timedelta(days=30)
    assert not items[0].at_risk


def test_invoice_later_than_usual_is_moved_to_next_week_and_flagged():
    b = LedgerBuilder()
    b.invoice("Late Co", AS_OF - pd.Timedelta(days=80), AS_OF - pd.Timedelta(days=50), 3_000)
    items, _ = _items(b, "open_invoice")
    assert items[0].date == AS_OF + pd.Timedelta(days=7)
    assert items[0].at_risk and items[0].confidence == "low"


def test_open_bills_on_due_date_overdue_paid_next_day():
    b = LedgerBuilder()
    b.bill("Vendor", AS_OF + pd.Timedelta(days=9), 700)
    b.bill("Vendor", AS_OF - pd.Timedelta(days=3), 400)
    items, _ = _items(b, "open_bill")
    assert sorted((i.date, i.amount) for i in items) == [
        (AS_OF + pd.Timedelta(days=1), 400), (AS_OF + pd.Timedelta(days=9), 700)]


def test_weekly_recurring_continues_after_open_bills_without_double_counting():
    b = LedgerBuilder()
    b.every(AS_OF - pd.Timedelta(days=70), 7, 10, 1_000, "out", "Ingredients", "Flour Co")  # last paid AS_OF-7
    b.bill("Flour Co", AS_OF + pd.Timedelta(days=7), 1_000)  # next one already billed
    b.bill("Flour Co", AS_OF + pd.Timedelta(days=40), 9_000)  # one-off bulk order must not hide the pattern
    items, ctx = _items(b, "recurring")
    dates = [i.date for i in items if i.counterparty == "Flour Co"]
    assert dates[0] == AS_OF + pd.Timedelta(days=14)
    assert all((d2 - d1).days == 7 for d1, d2 in zip(dates, dates[1:]))
    assert dates[-1] <= ctx.horizon_end
    assert len(dates) == 12  # weeks 2..13


def test_monthly_recurring_keeps_day_of_month():
    b = LedgerBuilder()
    for m in range(6, 0, -1):
        b.txn((AS_OF - pd.DateOffset(months=m)).replace(day=1), 4_000, "out", "Rent", "Landlord")
    items, _ = _items(b, "recurring")
    rent = [i.date for i in items if i.counterparty == "Landlord"]
    assert rent and all(d.day == 1 for d in rent)
    assert len(rent) == 3


def test_annual_payment_repeated_unless_already_billed():
    b = LedgerBuilder()
    b.txn(AS_OF - pd.Timedelta(days=365 - 20), 5_000, "out", "Insurance", "Annual Insurer")
    b.txn(AS_OF - pd.Timedelta(days=365 - 30), 2_000, "out", "Taxes", "Tax Office")
    b.bill("Tax Office", AS_OF + pd.Timedelta(days=35), 2_100, "Taxes")
    items, _ = _items(b, "annual")
    assert [(i.counterparty, i.date) for i in items] == [("Annual Insurer", AS_OF + pd.Timedelta(days=20))]


def test_balances_chain_and_bands():
    b = LedgerBuilder(cash=10_000)
    daily_retail(b, 120, 1_000)
    b.every(AS_OF - pd.Timedelta(days=110), 14, 8, 6_000, "out", "Payroll", "PayCo")
    f = forecast(b.build())
    weeks = f["weeks"]
    assert weeks[0]["opening"] == 10_000
    for prev, w in zip(weeks, weeks[1:]):
        assert w["opening"] == prev["closing"]
    for w in weeks:
        assert w["closing"] == pytest.approx(w["opening"] + w["inflows"] - w["outflows"], abs=0.02)
        assert w["p10"] <= w["closing"] <= w["p90"]
    # Retail ~7,000/week vs payroll ~3,000/week -> balance grows.
    assert f["summary"]["endingBalance"] > 10_000
    assert len(weeks) == 13


def test_scenario_items_aggregate_consistently():
    b = LedgerBuilder(cash=5_000)
    daily_retail(b, 60, 500)
    ledger = b.build()
    ctx = build_context(ledger)
    items = build_items(ledger, ctx)
    assert aggregate(items, ctx)["summary"] == forecast(ledger)["summary"]


# ---- seeded demo business --------------------------------------------------

def test_seeded_forecast_finds_late_november_squeeze(ledger):
    f = forecast(ledger, include_items=True)
    s = f["summary"]
    assert s["openingBalance"] == 40_000
    assert s["lowestWeek"] == 7
    assert 0 < s["lowestBalance"] < s["safetyBuffer"]
    assert s["firstNegativeWeek"] is None
    assert s["lowestP10"] < 0
    labels = " ".join(d["label"] for d in f["weeks"][6]["drivers"])
    assert "Golden Mill" in labels and "Payroll" in labels
    # Every recurring payee in the ledger is detected.
    recurring = {i["counterparty"] for i in f["items"] if i["source"] == "recurring"}
    assert {"Payroll - PayDay Services", "Parkview Properties", "Metro Community Bank", "Golden Mill Flour Co.",
            "CardPay Settlements"} <= recurring
    assert s["atRiskReceivables"] > 8_000  # Riverside's overdue invoices
