"""Read-only / advisory endpoints (tier T0-T1): dashboard, analysis, forecast, scenarios, alerts, financing."""
from __future__ import annotations

from typing import Annotated, Literal, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, fx, models
from app.api.deps import CamelModel, buffer_weeks, mask_account, user_ledger
from app.auth import CurrentUser, any_user, staff
from app.db import get_db
from app.engines import alerts as alert_engine
from app.engines.analysis import analyze
from app.engines.forecast import forecast
from app.engines.matching import FinancingNeed, match, need_from_forecast
from app.engines.scenario import Change, run_scenario

router = APIRouter(prefix="/api", tags=["insights"])

# Upper bound for any amount typed in, in the business's own currency: generous enough for currencies like BDT
# where everyday figures run into the millions. It only rejects absurd input; real limits come from the data.
MAX_AMOUNT = 100_000_000_000

SEVERITY_RANK = alert_engine.SEVERITY_ORDER


def _alert_dict(a: models.SmeAlert) -> dict:
    return {"id": a.Id, "type": a.AlertType, "severity": a.Severity, "title": a.Title, "detail": a.Detail,
            "suggestedAction": a.SuggestedAction, "status": a.Status,
            "createdAt": a.CreatedAt.isoformat(timespec="seconds") + "Z"}


def refresh_alerts(db: Session, user: CurrentUser, analysis: dict, fc: dict) -> list[models.SmeAlert]:
    rows = alert_engine.sync_alerts(db, user.business_id, alert_engine.evaluate(analysis, fc))
    return sorted(rows, key=lambda a: (SEVERITY_RANK.get(a.Severity, 9), a.Id))


@router.get("/dashboard/summary")
def dashboard(db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> dict:
    ledger = user_ledger(db, user)
    a = analyze(ledger)
    fc = forecast(ledger, buffer_weeks=buffer_weeks())
    open_alerts = [x for x in refresh_alerts(db, user, a, fc) if x.Status == "open"]
    pending = db.scalar(select(func.count()).select_from(models.AgentActionRequest).where(
        models.AgentActionRequest.BusinessId == user.business_id, models.AgentActionRequest.Status == "pending"))
    return {
        "asOf": a["asOf"],
        "business": a["business"],
        "accounts": [{"name": r.Name, "type": r.AccountType, "number": mask_account(r.AccountNumber),
                      "balance": r.Balance} for r in ledger.accounts.itertuples()],
        "healthScore": a["healthScore"],
        "kpis": {
            "operatingCash": a["liquidity"]["operatingCash"],
            "totalCash": a["liquidity"]["totalCash"],
            "cashCoverMonths": a["liquidity"]["cashCoverMonths"],
            "revenue12m": a["pnl12m"]["revenue"],
            "revenueGrowthYoY": a["growth"]["revenueGrowthYoY"],
            "netMargin": a["pnl12m"]["netMargin"],
            "dso": a["receivables"]["dso"],
            "overdueReceivables": a["receivables"]["overdueTotal"],
        },
        "forecast": {
            "summary": fc["summary"],
            "weeks": [{k: w[k] for k in ("week", "start", "closing", "p10", "p90", "inflows", "outflows")}
                      for w in fc["weeks"]],
        },
        "monthly": a["monthly"],
        "alerts": [_alert_dict(x) for x in open_alerts[:5]],
        "openAlertCount": len(open_alerts),
        "pendingApprovals": pending,
    }


@router.get("/analysis")
def analysis(db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> dict:
    return analyze(user_ledger(db, user))


@router.get("/cashflow/forecast")
def cashflow_forecast(
    weeks: int = Query(13, ge=4, le=26),
    items: bool = Query(False, description="Include every projected item"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(any_user),
) -> dict:
    return forecast(user_ledger(db, user), weeks=weeks, buffer_weeks=buffer_weeks(), include_items=items)


# ---------------------------------------------------------------- scenarios

class DelayCustomer(CamelModel):
    type: Literal["delay_customer"]
    customer: str = Field(min_length=1, max_length=200)
    days: int = Field(ge=1, le=120)


class LoseCustomer(CamelModel):
    type: Literal["lose_customer"]
    customer: str = Field(min_length=1, max_length=200)


class RevenueChange(CamelModel):
    type: Literal["revenue_change"]
    pct: float = Field(ge=-0.9, le=2.0)


class OneOffExpense(CamelModel):
    type: Literal["one_off_expense"]
    amount: float = Field(gt=0, le=MAX_AMOUNT)
    week: int = Field(1, ge=1, le=26)
    label: str = Field("One-off expense", max_length=100)


class NewLoan(CamelModel):
    type: Literal["new_loan"]
    amount: float = Field(gt=0, le=MAX_AMOUNT)
    apr: float = Field(0.12, ge=0, le=1.5)
    term_months: int = Field(24, ge=1, le=120)
    week: int = Field(1, ge=1, le=26)


class DeferBill(CamelModel):
    type: Literal["defer_bill"]
    vendor: str = Field(min_length=1, max_length=200)
    days: int = Field(ge=1, le=90)


class NewHire(CamelModel):
    type: Literal["new_hire"]
    monthly_cost: float = Field(gt=0, le=MAX_AMOUNT)
    start_week: int = Field(1, ge=1, le=26)


ScenarioChange = Annotated[
    Union[DelayCustomer, LoseCustomer, RevenueChange, OneOffExpense, NewLoan, DeferBill, NewHire],
    Field(discriminator="type"),
]


class ScenarioRequest(CamelModel):
    changes: list[ScenarioChange] = Field(max_length=10)
    weeks: int = Field(13, ge=4, le=26)


@router.post("/scenarios/run")
def scenarios_run(body: ScenarioRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> dict:
    changes = [Change(c.type, c.model_dump(exclude={"type"})) for c in body.changes]
    result = run_scenario(user_ledger(db, user), changes, weeks=body.weeks, buffer_weeks=buffer_weeks())
    audit.record(db, action="insight.scenario", actor=user.label, actor_type="user", business_id=user.business_id,
                 tool="run_scenario", tier="T1", params=body.model_dump(), result=result["verdict"])
    return result


# ---------------------------------------------------------------- alerts

@router.get("/alerts")
def list_alerts(
    status: Literal["open", "acknowledged", "active"] = "active",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(any_user),
) -> list[dict]:
    ledger = user_ledger(db, user)
    rows = refresh_alerts(db, user, analyze(ledger), forecast(ledger, buffer_weeks=buffer_weeks()))
    if status != "active":
        rows = [r for r in rows if r.Status == status]
    return [_alert_dict(r) for r in rows]


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(staff)) -> dict:
    row = db.get(models.SmeAlert, alert_id)
    if row is None or row.BusinessId != user.business_id:
        raise HTTPException(404, "Alert not found")
    row.Status = "acknowledged"
    audit.record(db, action="alert.acknowledged", actor=user.label, actor_type="user",
                 business_id=user.business_id, result=row.Title, commit=False)
    db.commit()
    return _alert_dict(row)


# ---------------------------------------------------------------- financing

class MatchRequest(CamelModel):
    use_forecast: bool = False
    amount: float | None = Field(None, gt=0, le=MAX_AMOUNT)
    purpose: Literal["working_capital", "bridge", "equipment", "expansion", "refinance"] = "working_capital"
    term_months: int | None = Field(None, ge=1, le=120)
    needed_within_days: int | None = Field(None, ge=1, le=365)


@router.get("/financing/products")
def products(db: Session = Depends(get_db), _: CurrentUser = Depends(any_user)) -> list[dict]:
    rows = db.scalars(select(models.FinProduct).order_by(models.FinProduct.Id)).all()
    return [{"id": p.Id, "lender": p.Lender, "name": p.Name, "type": p.ProductType, "description": p.Description,
             "amountRange": [p.MinAmount, p.MaxAmount], "aprRange": [p.AprMin, p.AprMax],
             "termRange": [p.TermMonthsMin, p.TermMonthsMax], "fundingDays": p.FundingDays,
             "purposes": p.Purposes.split(","), "currency": p.Currency} for p in rows]


@router.post("/financing/match")
def financing_match(body: MatchRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> dict:
    ledger = user_ledger(db, user)
    a = analyze(ledger)
    if body.use_forecast:
        need = need_from_forecast(forecast(ledger, buffer_weeks=buffer_weeks()))
        if need is None:
            return {"need": None, "eligible": [], "ineligible": [],
                    "message": "No cash shortfall is forecast, so no bridge financing is needed."}
    else:
        if body.amount is None:
            raise HTTPException(422, "amount is required unless useForecast is true")
        need = FinancingNeed(body.amount, body.purpose, body.term_months, body.needed_within_days)
    try:
        result = match(ledger, a, need)
    except fx.UnknownCurrency as e:
        raise HTTPException(422, f"Financing comparison is not available in {ledger.business.Currency} yet: {e}") from None
    top = result["eligible"][0] if result["eligible"] else None
    audit.record(db, action="insight.financing_match", actor=user.label, actor_type="user",
                 business_id=user.business_id, tool="match_financing", tier="T1", params=result["need"],
                 result=f"{len(result['eligible'])} eligible; top: {top['lender'] + ' ' + top['name'] if top else 'none'}")
    return result
