import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import models
from app.db import Base
from app.engines import alerts
from app.engines.analysis import analyze
from app.engines.forecast import forecast
from app.engines.matching import FinancingNeed, match, need_from_forecast, payment_and_cost
from app.engines.scenario import Change, run_scenario
from tests.factories import LedgerBuilder, daily_retail


# ---- alerts ----------------------------------------------------------------

def _fake_inputs(closing: list[float], buffer: float = 5_000) -> tuple[dict, dict]:
    weeks = [{"week": i + 1, "start": f"2026-07-{i + 1:02d}", "closing": c, "p10": c - 1_000, "drivers": []}
             for i, c in enumerate(closing)]
    neg = next((w["week"] for w in weeks if w["closing"] < 0), None)
    below = next((w["week"] for w in weeks if w["closing"] < buffer), None)
    low = min(weeks, key=lambda w: w["closing"])
    fc = {"weeks": weeks, "summary": {
        "firstNegativeWeek": neg, "firstBelowBufferWeek": below, "firstP10NegativeWeek": None,
        "lowestBalance": low["closing"], "lowestWeek": low["week"], "safetyBuffer": buffer,
        "shortfallAmount": max(0, buffer - low["closing"]), "lowestP10": low["p10"], "atRiskReceivables": 0}}
    analysis = {
        "receivables": {"overdueInvoices": []}, "customerPayments": [], "expenseAnomalies": [],
        "concentration": {"topCustomer": None}, "liquidity": {"runwayMonths": None, "netMonthlyBurn": 0},
        "debt": {"loans": []},
    }
    return analysis, fc


def test_negative_forecast_raises_critical_alert_first():
    analysis, fc = _fake_inputs([3_000, -2_000, 1_000])
    result = alerts.evaluate(analysis, fc)
    assert result[0].severity == "critical" and result[0].alert_type == "cash_shortfall"
    assert "week 2" in result[0].title


def test_healthy_forecast_raises_no_cash_alert():
    analysis, fc = _fake_inputs([20_000, 25_000, 30_000])
    assert alerts.evaluate(analysis, fc) == []


def test_loan_payment_risk():
    analysis, fc = _fake_inputs([500, 20_000])
    analysis["debt"]["loans"] = [{"monthlyPayment": 2_000}]
    types = [a.alert_type for a in alerts.evaluate(analysis, fc)]
    assert "loan_payment_risk" in types


def test_sync_alerts_upserts_and_resolves():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    a1 = alerts.AlertCandidate("low_cash", "high", "t1", "d", "s", "low_cash")
    a2 = alerts.AlertCandidate("concentration", "low", "t2", "d", "s", "concentration")
    with Session(eng) as s:
        s.add(models.SmeBusiness(Id=1, Name="x", Industry="x", Region="x", FoundedDate=pd.Timestamp("2020-01-01"),
                                 Employees=1, AnnualRevenue=1, CreditScore=700, DataAsOf=pd.Timestamp("2026-01-01")))
        s.commit()
        assert len(alerts.sync_alerts(s, 1, [a1, a2])) == 2
        a1.title = "updated"
        open_rows = alerts.sync_alerts(s, 1, [a1])  # concentration cleared
        assert [r.Title for r in open_rows] == ["updated"]
        assert s.scalar(select(models.SmeAlert.Status).where(models.SmeAlert.Fingerprint == "concentration")) == "resolved"
        assert len(s.scalars(select(models.SmeAlert)).all()) == 2  # no duplicates


def test_seeded_alerts(ledger):
    types = {a.alert_type for a in alerts.evaluate(analyze(ledger), forecast(ledger))}
    assert {"low_cash", "downside_risk", "overdue_receivable", "slipping_payer", "expense_anomaly"} <= types
    assert "cash_shortfall" not in types


# ---- matching --------------------------------------------------------------

def test_amortized_payment_matches_formula():
    b = LedgerBuilder().product(ProductType="term_loan")
    pay, cost = payment_and_cost(b.products[0], 10_000, 0.12, 12)
    assert pay == pytest.approx(888.49, abs=0.01)
    assert cost == pytest.approx(888.49 * 12 - 10_000, abs=0.1)


def _match_ledger():
    b = LedgerBuilder(cash=20_000)
    daily_retail(b, 120, 1_000)
    b.loan(outstanding=20_000, payment=500)
    b.product(Name="Cheap line", ProductType="credit_line", AprMin=0.10, AprMax=0.12, FundingDays=7)
    b.product(Name="Pricey advance", ProductType="merchant_advance", AprMin=0.6, AprMax=0.8, TermMonthsMin=3,
              TermMonthsMax=12, FundingDays=1)
    b.product(Name="Needs collateral", RequiresCollateral=True)
    b.product(Name="Needs 750 credit", MinCreditScore=750)
    b.product(Name="Excludes food", ExcludedIndustries="Food & Beverage")
    b.product(Name="Small grant", ProductType="gov_grant", MaxAmount=5_000, AprMin=0, AprMax=0,
              TermMonthsMin=0, TermMonthsMax=0, Purposes="equipment")
    return b.build()


def test_matcher_ranks_and_explains_ineligibility():
    ledger = _match_ledger()
    result = match(ledger, analyze(ledger), FinancingNeed(10_000, "bridge", term_months=3))
    names = [r["name"] for r in result["eligible"]]
    assert names[0] == "Cheap line"
    assert names.index("Cheap line") < names.index("Pricey advance")
    reasons = {r["name"]: r["ineligibleReasons"] for r in result["ineligible"]}
    assert any("collateral" in x for x in reasons["Needs collateral"])
    assert any("credit score 750" in x for x in reasons["Needs 750 credit"])
    assert any("industry" in x for x in reasons["Excludes food"])
    pricey = next(r for r in result["eligible"] if r["name"] == "Pricey advance")
    assert any("expensive" in w.lower() for w in pricey["watchOuts"])
    assert "Not financial advice" in result["disclaimer"]


def test_grant_capped_below_need_is_offered_as_partial():
    ledger = _match_ledger()
    result = match(ledger, analyze(ledger), FinancingNeed(20_000, "equipment"))
    grant = next(r for r in result["ineligible"] if r["name"] == "Small grant")
    assert grant["partialAmount"] == 5_000


def test_need_validation_and_forecast_sizing():
    with pytest.raises(ValueError):
        FinancingNeed(1_000, "yacht")
    with pytest.raises(ValueError):
        FinancingNeed(0, "bridge")
    assert need_from_forecast({"summary": {"shortfallAmount": 0}}) is None


def test_seeded_matching(ledger):
    a = analyze(ledger)
    bridge = match(ledger, a, need_from_forecast(forecast(ledger)))
    assert bridge["need"]["source"] == "forecast" and bridge["need"]["amount"] >= 19_000
    assert bridge["eligible"][0]["type"] in {"credit_line", "invoice_finance"}
    oven = match(ledger, a, FinancingNeed(45_000, "equipment"))
    assert oven["eligible"][0]["type"] == "equipment"
    assert any(r.get("partialAmount") for r in oven["ineligible"])  # the city grant


# ---- scenarios -------------------------------------------------------------

def test_no_changes_means_no_delta(ledger):
    r = run_scenario(ledger, [])
    assert r["delta"] == {"lowestBalance": 0, "endingBalance": 0, "weeksBelowBuffer": 0}


def test_one_off_expense_and_financing_it(ledger):
    oven = Change("one_off_expense", {"amount": 45_000, "week": 6, "label": "Oven"})
    cash = run_scenario(ledger, [oven])
    assert cash["delta"]["endingBalance"] == pytest.approx(-45_000)
    assert cash["scenario"]["firstNegativeWeek"] == 6
    assert cash["verdict"].startswith("Not affordable")
    loan = Change("new_loan", {"amount": 45_000, "apr": 0.095, "term_months": 60, "week": 6})
    financed = run_scenario(ledger, [oven, loan])
    assert financed["scenario"]["firstNegativeWeek"] is None


def test_customer_delay_and_bill_deferral_move_cash(ledger):
    late = run_scenario(ledger, [Change("delay_customer", {"customer": "Northwind Corporate Offices", "days": 30})])
    assert late["delta"]["lowestBalance"] < 0
    defer = run_scenario(ledger, [Change("defer_bill", {"vendor": "Golden Mill Flour Co.", "days": 14})])
    assert defer["delta"]["lowestBalance"] > 0


def test_revenue_drop_and_new_hire_reduce_cash(ledger):
    r = run_scenario(ledger, [Change("revenue_change", {"pct": -0.1}), Change("new_hire", {"monthly_cost": 4_000})])
    assert r["delta"]["endingBalance"] < -20_000
    assert len(r["changes"]) == 2


def test_unknown_change_rejected():
    with pytest.raises(ValueError):
        Change("buy_lottery_ticket")
