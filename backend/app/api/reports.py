"""Reports: view on screen (JSON) or download as CSV / Excel, plus the lender-ready PDF summary.

Every role may read reports (they show the business's own data). Downloads are written to the audit log.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, models, reports_export
from app.api.deps import buffer_weeks, user_ledger
from app.auth import CurrentUser, any_user
from app.db import get_db
from app.engines import reports
from app.engines.analysis import analyze, monthly_series
from app.engines.forecast import forecast
from app.engines.ledger import Ledger

router = APIRouter(prefix="/api/reports", tags=["reports"])

Format = Literal["json", "csv", "xlsx"]
MEDIA = {"csv": "text/csv; charset=utf-8",
         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "pdf": "application/pdf"}


def _range(ledger: Ledger, start: date | None, end: date | None) -> tuple[date, date]:
    d_start, d_end = reports.default_range(ledger)
    start, end = start or d_start, end or d_end
    try:
        reports.check_range(start, end)
    except reports.ReportError as e:
        raise HTTPException(422, str(e)) from None
    return start, end


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "business"


def _meta(ledger: Ledger, period: str) -> list[str]:
    b = ledger.business
    return [f"{b.Name} · {period} · amounts in {b.Currency}",
            f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by SME Finance Copilot from the business's own records"]


def _file(db: Session, user: CurrentUser, kind: str, fmt: str, table: reports_export.Table, name: str) -> Response:
    body = reports_export.to_csv(table) if fmt == "csv" else reports_export.to_xlsx(table)
    audit.record(db, action="report.downloaded", actor=user.label, actor_type="user", business_id=user.business_id,
                 result=f"{kind} as {fmt} ({len(table.rows)} rows)")
    return Response(body, media_type=MEDIA[fmt], headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})


@router.get("/options")
def options(db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> dict:
    """What the filters can offer: accounts, categories in use, the default period and the data's date range."""
    ledger = user_ledger(db, user)
    start, end = reports.default_range(ledger)
    accounts = db.scalars(select(models.SmeBankAccount).where(models.SmeBankAccount.BusinessId == user.business_id)
                          .order_by(models.SmeBankAccount.Id)).all()
    t = ledger.txns
    return {
        "currency": ledger.business.Currency,
        "defaultStart": start.isoformat(), "defaultEnd": end.isoformat(),
        "firstDate": t["TxnDate"].min().date().isoformat() if not t.empty else None,
        "lastDate": ledger.as_of.date().isoformat(),
        "accounts": [{"id": a.Id, "name": a.Name, "number": reports._last4(a.AccountNumber)} for a in accounts],
        "categories": sorted(t["Category"].unique().tolist()) if not t.empty else [],
    }


@router.get("/pnl")
def pnl(start: date | None = None, end: date | None = None, format: Format = "json",
        db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)):
    ledger = user_ledger(db, user)
    start, end = _range(ledger, start, end)
    report = reports.profit_and_loss(ledger, start, end)
    if format == "json":
        return {"currency": ledger.business.Currency, **report}
    table = reports_export.pnl_table(report, _meta(ledger, f"{start} to {end}"), ledger.business.Currency)
    return _file(db, user, "profit and loss", format, table, f"{_slug(ledger.business.Name)}-profit-and-loss-{start}-{end}")


@router.get("/receivables")
def aged_receivables(format: Format = "json", db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)):
    ledger = user_ledger(db, user)
    report = reports.aged_receivables(ledger)
    if format == "json":
        return {"currency": ledger.business.Currency, **report}
    table = reports_export.receivables_table(report, _meta(ledger, f"as of {report['asOf']}"), ledger.business.Currency)
    return _file(db, user, "aged receivables", format, table,
                 f"{_slug(ledger.business.Name)}-aged-receivables-{report['asOf']}")


@router.get("/forecast")
def cash_forecast(format: Format = "json", db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)):
    ledger = user_ledger(db, user)
    report = reports.forecast_table(forecast(ledger, buffer_weeks=buffer_weeks()))
    if format == "json":
        return {"currency": ledger.business.Currency, **report}
    table = reports_export.forecast_table(report, _meta(ledger, f"13 weeks from {report['asOf']}"),
                                          ledger.business.Currency)
    return _file(db, user, "cash-flow forecast", format, table,
                 f"{_slug(ledger.business.Name)}-cash-flow-forecast-{report['asOf']}")


@router.get("/transactions")
def transactions(start: date | None = None, end: date | None = None, account_id: int | None = Query(None, alias="accountId"),
                 category: str | None = Query(None, max_length=50), direction: Literal["in", "out"] | None = None,
                 q: str = Query("", max_length=100), format: Format = "json",
                 db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)):
    ledger = user_ledger(db, user)
    start, end = _range(ledger, start, end)
    # The preview shows the newest 500 rows; downloads carry every matching row (up to the export cap).
    report = reports.transactions(db, user.business_id, start, end, account_id=account_id, category=category,
                                  direction=direction, search=q, limit=500 if format == "json" else reports.MAX_EXPORT_ROWS)
    if format == "json":
        return {"currency": ledger.business.Currency, **report}
    table = reports_export.transactions_table(report, _meta(ledger, f"{start} to {end}"), ledger.business.Currency)
    return _file(db, user, "transactions", format, table, f"{_slug(ledger.business.Name)}-transactions-{start}-{end}")


@router.get("/summary.pdf")
def lender_summary(db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> Response:
    """A two-page financial summary to share with a lender, accountant or investor."""
    ledger = user_ledger(db, user)
    a = analyze(ledger)
    fc = forecast(ledger, buffer_weeks=buffer_weeks())
    b = ledger.business
    data = {
        "currency": b.Currency, "asOf": a["asOf"], "generated": f"{datetime.now(timezone.utc):%Y-%m-%d}",
        "business": {"name": b.Name, "industry": b.Industry, "region": b.Region, "founded": b.FoundedDate.isoformat(),
                     "employees": b.Employees},
        "operatingCash": ledger.operating_cash,
        "pnl": {**a["pnl12m"], "start": (ledger.as_of.date() - timedelta(days=364)).isoformat(), "end": a["asOf"]},
        "monthly": monthly_series(ledger, 12),
        "health": a["healthScore"],
        "forecast": reports.forecast_table(fc),
        "receivables": reports.aged_receivables(ledger),
        "loans": [{"lender": r.Lender, "type": r.LoanType.replace("_", " "), "outstanding": float(r.Outstanding),
                   "rate": float(r.AnnualRate), "monthlyPayment": float(r.MonthlyPayment)}
                  for r in ledger.loans.itertuples()],
    }
    body = reports_export.summary_pdf(data)
    audit.record(db, action="report.downloaded", actor=user.label, actor_type="user", business_id=user.business_id,
                 result="lender summary as pdf")
    return Response(body, media_type=MEDIA["pdf"], headers={
        "Content-Disposition": f'attachment; filename="{_slug(b.Name)}-financial-summary-{a["asOf"]}.pdf"'})
