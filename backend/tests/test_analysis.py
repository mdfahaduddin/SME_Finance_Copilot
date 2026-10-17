import pandas as pd
import pytest

from app.engines import analysis
from app.engines.ledger import fmt_money, linear_score
from tests.factories import AS_OF, LedgerBuilder, daily_retail


def test_linear_score_bounds_and_direction():
    assert linear_score(5, 0, 10) == 50
    assert linear_score(-1, 0, 10) == 0
    assert linear_score(99, 0, 10) == 100
    assert linear_score(30, 90, 30) == 100  # lower is better (e.g. DSO)
    assert linear_score(60, 90, 30) == 50


def test_fmt_money_puts_sign_first():
    assert fmt_money(1234.4) == "$1,234"
    assert fmt_money(-8600) == "-$8,600"


def test_profit_and_loss_exact_figures():
    b = LedgerBuilder()
    d = AS_OF - pd.Timedelta(days=10)
    (b.txn(d, 10_000, "in", "Sales - Retail")
      .txn(d, 3_000, "out", "Ingredients")
      .txn(d, 4_000, "out", "Payroll")
      .txn(d, 500, "out", "Taxes")
      .txn(d, 1_000, "out", "Owner Draw")
      .txn(d, 800, "out", "Loan Repayment")
      .txn(d, 99_999, "in", "Opening Balance"))  # ignored
    pnl = analysis.profit_and_loss(b.build(), 30)
    assert pnl["revenue"] == 10_000
    assert pnl["grossProfit"] == 7_000
    assert pnl["operatingProfit"] == 3_000
    assert pnl["netProfit"] == 3_000 - 500 - 1_000  # no loans -> no interest
    assert pnl["debtService"] == 800
    assert pnl["grossMargin"] == 0.7


def test_receivables_aging_and_dso():
    b = LedgerBuilder()
    b.invoice("A", AS_OF - pd.Timedelta(days=20), AS_OF + pd.Timedelta(days=10), 1_000)   # current
    b.invoice("B", AS_OF - pd.Timedelta(days=45), AS_OF - pd.Timedelta(days=15), 2_000)   # 1-30
    b.invoice("C", AS_OF - pd.Timedelta(days=80), AS_OF - pd.Timedelta(days=50), 3_000)   # 31-60
    ar = analysis.receivables(b.build())
    assert ar["aging"] == {"current": 1_000, "1-30": 2_000, "31-60": 3_000, "61-90": 0, "90+": 0}
    assert ar["overdueTotal"] == 5_000
    assert ar["dso"] == 90.0  # all 6,000 open vs 6,000 billed in 90 days
    assert ar["overdueInvoices"][0]["customer"] == "C"  # oldest first


def test_liquidity_runway_only_when_burning():
    profitable = LedgerBuilder(cash=30_000)
    daily_retail(profitable, 90, 1_000).every(AS_OF - pd.Timedelta(days=80), 14, 6, 5_000, "out", "Payroll", "P")
    assert analysis.liquidity(profitable.build())["runwayMonths"] is None

    burning = LedgerBuilder(cash=30_000)
    daily_retail(burning, 90, 100).every(AS_OF - pd.Timedelta(days=80), 14, 6, 10_000, "out", "Payroll", "P")
    liq = analysis.liquidity(burning.build())
    assert liq["netMonthlyBurn"] > 0
    assert liq["runwayMonths"] == pytest.approx(30_000 / liq["netMonthlyBurn"], abs=0.1)


def test_expense_anomaly_flags_spike_but_not_extra_pay_run():
    b = LedgerBuilder()
    # 14 months of bi-weekly payroll (some months have 3 runs) and small monthly maintenance.
    b.every(AS_OF - pd.Timedelta(days=420), 14, 30, 5_000, "out", "Payroll", "PayCo")
    for m in range(1, 14):
        b.txn(AS_OF - pd.DateOffset(months=m), 300, "out", "Maintenance", "Fixer")
    b.txn(AS_OF - pd.DateOffset(months=2), 5_000, "out", "Maintenance", "Fixer")
    found = analysis.expense_anomalies(b.build())
    assert [a["category"] for a in found] == ["Maintenance"]
    assert found[0]["excess"] > 4_000


def test_customer_payment_trend_detects_worsening_payer():
    b = LedgerBuilder()
    for k, delay in enumerate([2, 3, 2, 3, 2, 20, 25, 30]):
        due = AS_OF - pd.Timedelta(days=300 - 30 * k)
        b.invoice("Slow Co", due - pd.Timedelta(days=30), due, 1_000, "paid", due + pd.Timedelta(days=delay))
    rows = analysis.customer_payment_behaviour(b.build())
    assert rows[0]["customer"] == "Slow Co"
    assert rows[0]["trend"] == "worsening"
    assert rows[0]["recentDaysLate"] == 25


def test_health_score_weights_and_bounds():
    assert sum(analysis.HEALTH_WEIGHTS.values()) == pytest.approx(1.0)
    strong = analysis.health_score(
        {"cashCoverMonths": 6}, {"netMargin": 0.2}, {"revenueGrowthYoY": 0.3, "revenueVolatility": 0.01},
        {"dso": 20}, {"dscr": 3.0}, {"topCustomerShareOfTotal": 0.05})
    weak = analysis.health_score(
        {"cashCoverMonths": 0}, {"netMargin": -0.2}, {"revenueGrowthYoY": -0.3, "revenueVolatility": 0.9},
        {"dso": 120}, {"dscr": 0.5}, {"topCustomerShareOfTotal": 0.9})
    assert strong["score"] == 100 and strong["grade"] == "Excellent"
    assert weak["score"] == 0 and weak["grade"] == "Critical"
    assert sum(c["contribution"] for c in strong["components"]) == pytest.approx(100, abs=0.5)


# ---- seeded demo business --------------------------------------------------

def test_seeded_analysis_story(ledger):
    a = analysis.analyze(ledger)
    hs = a["healthScore"]
    assert 0 <= hs["score"] <= 100
    assert hs["weakestArea"] == "Liquidity"  # thin cash cover is the bakery's core problem
    assert a["pnl12m"]["revenue"] > 1_000_000
    assert 0 < a["pnl12m"]["netMargin"] < 0.10
    riverside = next(c for c in a["customerPayments"] if c["customer"] == "Riverside Hotel Group")
    assert riverside["trend"] == "worsening"
    assert {x["category"] for x in a["expenseAnomalies"]} == {"Utilities", "Maintenance"}
    assert a["concentration"]["topCustomer"] == "Northwind Corporate Offices"
    assert len(a["monthly"]) == 12 and a["monthly"][-1]["partial"]
