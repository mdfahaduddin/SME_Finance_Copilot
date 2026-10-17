"""Reports: profit & loss by month, aged receivables, cash-flow forecast table and filtered transactions.

Pure functions over a Ledger (plus a query for transactions, which need account names). The definitions are
the analysis engine's, so a report always agrees with the dashboard and the copilot: revenue is "Sales - *"
inflows, cost of goods and operating expenses use the same category groups, and net profit subtracts the
same estimated interest, taxes and owner compensation.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import models
from app.engines.analysis import receivables
from app.engines.ledger import COGS, OPEX, OWNER, REVENUE_PREFIX, TAXES, Ledger

MAX_RANGE_DAYS = 3 * 366
MAX_EXPORT_ROWS = 20_000
AGING = ("current", "1-30", "31-60", "61-90", "90+")


class ReportError(ValueError):
    pass


def default_range(ledger: Ledger) -> tuple[date, date]:
    """The last 12 calendar months, ending on the data's reference date."""
    end = ledger.as_of.date()
    start = (end.replace(day=1) - pd.DateOffset(months=11)).date()
    return start, end


def check_range(start: date, end: date) -> None:
    if start > end:
        raise ReportError("The start date must be on or before the end date")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ReportError("Choose a period of at most 3 years")


def _months(start: date, end: date) -> list[tuple[str, date, date]]:
    """Calendar months touching [start, end], each clipped to the range: (label, first day, last day)."""
    out = []
    cur = start.replace(day=1)
    while cur <= end:
        nxt = (pd.Timestamp(cur) + pd.DateOffset(months=1)).date()
        out.append((cur.strftime("%Y-%m"), max(cur, start), min(nxt - timedelta(days=1), end)))
        cur = nxt
    return out


def _monthly_interest(ledger: Ledger) -> float:
    if ledger.loans.empty:
        return 0.0
    return float((ledger.loans["Outstanding"] * ledger.loans["AnnualRate"] / 12).sum())


def profit_and_loss(ledger: Ledger, start: date, end: date) -> dict:
    """Monthly P&L for the period: one column per month plus a total; rows are line items and subtotals."""
    check_range(start, end)
    t = ledger.operating_txns()
    t = t[(t["TxnDate"] >= pd.Timestamp(start)) & (t["TxnDate"] <= pd.Timestamp(end))]
    months = _months(start, end)
    labels = [m[0] for m in months]
    t = t.assign(Month=t["TxnDate"].dt.strftime("%Y-%m"))

    def by_month(mask) -> list[float]:
        sums = t[mask].groupby("Month")["Amount"].sum()
        values = [round(float(sums.get(m, 0.0)), 2) for m in labels]
        return values + [round(sum(values), 2)]

    def lines(mask, categories) -> list[dict]:
        return [{"label": c, "kind": "item", "values": by_month(mask & (t["Category"] == c))} for c in categories]

    inflow, outflow = t["Direction"] == "in", t["Direction"] == "out"
    revenue_mask = inflow & t["Category"].str.startswith(REVENUE_PREFIX)
    used = lambda mask: sorted(t.loc[mask, "Category"].unique())  # noqa: E731
    cogs_mask, opex_mask = outflow & t["Category"].isin(COGS), outflow & t["Category"].isin(OPEX)

    revenue = by_month(revenue_mask)
    cogs = by_month(cogs_mask)
    opex = by_month(opex_mask)
    gross = [round(r - c, 2) for r, c in zip(revenue, cogs)]
    operating = [round(g - o, 2) for g, o in zip(gross, opex)]
    monthly_interest = _monthly_interest(ledger)
    interest = [round(monthly_interest * ((last - first).days + 1) / 30.4375, 2) for _, first, last in months]
    interest.append(round(sum(interest), 2))
    taxes = by_month(outflow & t["Category"].isin(TAXES))
    owner = by_month(outflow & t["Category"].isin(OWNER))
    net = [round(o - i - x - w, 2) for o, i, x, w in zip(operating, interest, taxes, owner)]

    rows = [
        {"label": "Revenue", "kind": "header", "values": None},
        *lines(revenue_mask, used(revenue_mask)),
        {"label": "Total revenue", "kind": "subtotal", "values": revenue},
        {"label": "Cost of goods sold", "kind": "header", "values": None},
        *lines(cogs_mask, used(cogs_mask)),
        {"label": "Total cost of goods sold", "kind": "subtotal", "values": cogs},
        {"label": "Gross profit", "kind": "total", "values": gross},
        {"label": "Operating expenses", "kind": "header", "values": None},
        *lines(opex_mask, used(opex_mask)),
        {"label": "Total operating expenses", "kind": "subtotal", "values": opex},
        {"label": "Operating profit", "kind": "total", "values": operating},
        {"label": "Interest (estimated from loan balances)", "kind": "item", "values": interest},
        {"label": "Taxes", "kind": "item", "values": taxes},
        {"label": "Owner compensation", "kind": "item", "values": owner},
        {"label": "Net profit", "kind": "total", "values": net},
    ]
    total_revenue = revenue[-1]
    return {
        "start": start.isoformat(), "end": end.isoformat(), "columns": labels + ["Total"], "rows": rows,
        "summary": {
            "revenue": total_revenue, "grossProfit": gross[-1], "operatingProfit": operating[-1], "netProfit": net[-1],
            "grossMargin": round(gross[-1] / total_revenue, 4) if total_revenue else 0.0,
            "netMargin": round(net[-1] / total_revenue, 4) if total_revenue else 0.0,
        },
        "partialMonths": [m[0] for m in months if m[1].day != 1 or (m[2] + timedelta(days=1)).day != 1],
    }


def aged_receivables(ledger: Ledger) -> dict:
    """Open invoices by customer and age (days past due on the reference date)."""
    inv = ledger.invoices
    open_inv = inv[inv["Status"] == "open"].copy()
    open_inv["DaysPastDue"] = (ledger.as_of - open_inv["DueDate"]).dt.days

    def bucket(d: int) -> str:
        return "current" if d <= 0 else "1-30" if d <= 30 else "31-60" if d <= 60 else "61-90" if d <= 90 else "90+"

    customers: dict[str, dict] = {}
    for r in open_inv.itertuples():
        row = customers.setdefault(r.Customer, {"customer": r.Customer, **{k: 0.0 for k in AGING}, "total": 0.0,
                                               "invoices": 0, "oldestDaysPastDue": 0})
        row[bucket(int(r.DaysPastDue))] += float(r.Amount)
        row["total"] += float(r.Amount)
        row["invoices"] += 1
        row["oldestDaysPastDue"] = max(row["oldestDaysPastDue"], int(r.DaysPastDue))
    rows = sorted(customers.values(), key=lambda c: (-c["oldestDaysPastDue"], -c["total"]))
    for c in rows:
        for k in (*AGING, "total"):
            c[k] = round(c[k], 2)
    totals = {k: round(sum(c[k] for c in rows), 2) for k in (*AGING, "total")}
    summary = receivables(ledger)
    return {
        "asOf": ledger.as_of.date().isoformat(), "customers": rows, "totals": totals, "dso": summary["dso"],
        "invoices": [
            {"invoiceNo": r.InvoiceNo, "customer": r.Customer, "issueDate": r.IssueDate.date().isoformat(),
             "dueDate": r.DueDate.date().isoformat(), "amount": round(float(r.Amount), 2),
             "daysPastDue": max(0, int(r.DaysPastDue)), "bucket": bucket(int(r.DaysPastDue))}
            for r in open_inv.sort_values("DaysPastDue", ascending=False).itertuples()
        ],
    }


def forecast_table(fc: dict) -> dict:
    """The 13-week forecast as report rows."""
    return {
        "asOf": fc["asOf"], "summary": fc["summary"],
        "weeks": [{"week": w["week"], "start": w["start"], "opening": w["opening"], "inflows": w["inflows"],
                   "outflows": w["outflows"], "net": w["net"], "closing": w["closing"], "p10": w["p10"],
                   "p90": w["p90"], "belowBuffer": w["closing"] < fc["summary"]["safetyBuffer"]}
                  for w in fc["weeks"]],
    }


def transactions(db: Session, business_id: int, start: date, end: date, *, account_id: int | None = None,
                 category: str | None = None, direction: str | None = None, search: str = "",
                 limit: int = MAX_EXPORT_ROWS) -> dict:
    """Ledger rows in the period, newest first, with optional filters. Totals cover every matching row."""
    check_range(start, end)
    T, A = models.SmeTransaction, models.SmeBankAccount
    stmt = (select(T, A.Name, A.AccountNumber).join(A, A.Id == T.AccountId)
            .where(A.BusinessId == business_id, T.TxnDate >= start, T.TxnDate <= end))
    if account_id is not None:
        stmt = stmt.where(A.Id == account_id)
    if category:
        stmt = stmt.where(T.Category == category)
    if direction in ("in", "out"):
        stmt = stmt.where(T.Direction == direction)
    term = " ".join(search.split())
    if term:
        like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(or_(T.Description.ilike(like, escape="\\"), T.Counterparty.ilike(like, escape="\\")))
    rows = db.execute(stmt.order_by(T.TxnDate.desc(), T.Id.desc())).all()
    money_in = round(sum(float(t.Amount) for t, *_ in rows if t.Direction == "in"), 2)
    money_out = round(sum(float(t.Amount) for t, *_ in rows if t.Direction == "out"), 2)
    return {
        "start": start.isoformat(), "end": end.isoformat(), "count": len(rows), "truncated": len(rows) > limit,
        "totals": {"in": money_in, "out": money_out, "net": round(money_in - money_out, 2)},
        "rows": [
            {"date": t.TxnDate.isoformat(), "account": f"{name} {_last4(number)}".strip(), "description": t.Description,
             "counterparty": t.Counterparty, "category": t.Category, "direction": t.Direction,
             "amount": round(float(t.Amount), 2),
             "signed": round(float(t.Amount) if t.Direction == "in" else -float(t.Amount), 2)}
            for t, name, number in rows[:limit]
        ],
    }


def _last4(number: str | None) -> str:
    """Exports never carry more than the last 4 digits of an account number."""
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    return f"****{digits[-4:]}" if digits else ""
