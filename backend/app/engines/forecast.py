"""13-week cash-flow forecast.

Hybrid model, chosen to be explainable and robust with only ~18 months of history:

1. Known items (deterministic)
   - Open invoices: expected on due date + that customer's recent average payment delay.
     Invoices already later than that are assumed to arrive next week but flagged at-risk.
   - Open bills: on their due date (overdue bills are paid next day).
2. Recurring items detected from the ledger
   - Any counterparty paid on a regular weekly / bi-weekly / monthly / bi-monthly cadence
     (payroll, rent, suppliers, loan payments, card fees, owner draws, ...) is projected
     forward from its last payment or last open bill. Ingredient and packaging costs are
     scaled by the seasonal index.
   - Counterparties paid at most 4 times a year repeat last year's payments that fall in
     the horizon (e.g. annual premiums), unless an open bill already covers them.
3. Statistical baseline
   - Retail card sales: level from simple exponential smoothing (statsmodels) over the last
     26 weeks x a seasonal index from the same weeks last year.
   - New B2B invoices: each customer's recent weekly billing rate, collected from
     today + 30-day terms + their usual delay onward.
4. Uncertainty
   - P10/P90 bands from the volatility of weekly retail sales (and +/-25% on projected new
     B2B billing), accumulated over the horizon. P10 also assumes at-risk receivables slip
     out of the forecast window.
"""
from __future__ import annotations

import math
import warnings
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import SimpleExpSmoothing

from app.engines.analysis import customer_payment_behaviour
from app.engines.ledger import COGS, Ledger, fmt_money

Z_80 = 1.2816  # P10/P90 z-score

CADENCES = [  # (name, min interval days, max interval days, step days or None for calendar month)
    ("weekly", 6, 8, 7),
    ("biweekly", 13, 15, 14),
    ("monthly", 26, 35, None),
    ("bimonthly", 55, 66, None),
]


@dataclass
class ProjectedItem:
    date: pd.Timestamp
    amount: float
    direction: str          # in | out
    source: str             # open_invoice | open_bill | recurring | annual | retail_baseline | b2b_baseline | scenario
    label: str
    counterparty: str = ""
    category: str = ""
    ref: str = ""
    confidence: str = "medium"  # high | medium | low
    at_risk: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.date().isoformat()
        d["amount"] = round(self.amount, 2)
        return d


@dataclass
class ForecastContext:
    as_of: pd.Timestamp
    weeks: int
    opening_balance: float
    buffer: float
    retail_sigma: float
    assumptions: list[str] = field(default_factory=list)

    @property
    def horizon_end(self) -> pd.Timestamp:
        return self.as_of + pd.Timedelta(days=7 * self.weeks)

    def week_of(self, d: pd.Timestamp) -> int:
        return max(1, min(self.weeks, math.ceil((d - self.as_of).days / 7)))


# ---------------------------------------------------------------- seasonality

def _weekly_retail(ledger: Ledger) -> pd.Series:
    r = ledger.walk_in_revenue()
    # Weeks ending on the as_of weekday so the last bucket is a full week.
    s = r.set_index("TxnDate")["Amount"].resample(f"W-{ledger.as_of.day_name()[:3].upper()}").sum()
    return s[s.index <= ledger.as_of]


def seasonal_index(ledger: Ledger, start: pd.Timestamp, days: int = 7) -> float:
    """Ratio of last year's retail sales in [start-365, +days) to the 4 weeks before as_of-365."""
    r = ledger.walk_in_revenue()
    ly = start - pd.Timedelta(days=365)
    base_end = ledger.as_of - pd.Timedelta(days=365)
    base = r[(r["TxnDate"] > base_end - pd.Timedelta(days=28)) & (r["TxnDate"] <= base_end)]["Amount"].sum()
    target = r[(r["TxnDate"] >= ly) & (r["TxnDate"] < ly + pd.Timedelta(days=days))]["Amount"].sum()
    if base <= 0 or target <= 0:
        return 1.0
    return float(target / (base / 28 * days))


# ---------------------------------------------------------------- item builders

def _open_invoices(ledger: Ledger, ctx: ForecastContext) -> list[ProjectedItem]:
    delays = {c["customer"]: c["recentDaysLate"] for c in customer_payment_behaviour(ledger)}
    inv = ledger.invoices[ledger.invoices["Status"] == "open"]
    items = []
    for r in inv.itertuples():
        delay = max(0.0, delays.get(r.Customer, 0.0))
        expected = r.DueDate + pd.Timedelta(days=round(delay))
        days_past_due = (ctx.as_of - r.DueDate).days
        at_risk = False
        if expected <= ctx.as_of:
            expected = ctx.as_of + pd.Timedelta(days=7)
            at_risk = True
        if days_past_due > 30:
            at_risk = True
        if expected > ctx.horizon_end:
            continue
        items.append(ProjectedItem(
            date=expected, amount=float(r.Amount), direction="in", source="open_invoice",
            label=f"{r.InvoiceNo} from {r.Customer}", counterparty=r.Customer, category="Sales - Catering",
            ref=r.InvoiceNo, confidence="low" if at_risk else ("high" if delay < 10 else "medium"),
            at_risk=at_risk,
        ))
    return items


def _open_bills(ledger: Ledger, ctx: ForecastContext) -> list[ProjectedItem]:
    b = ledger.bills[ledger.bills["Status"] != "paid"]
    items = []
    for r in b.itertuples():
        due = r.ScheduledDate if r.Status == "scheduled" and pd.notna(r.ScheduledDate) else r.DueDate
        due = due if due > ctx.as_of else ctx.as_of + pd.Timedelta(days=1)
        if due > ctx.horizon_end:
            continue
        items.append(ProjectedItem(
            date=due, amount=float(r.Amount), direction="out", source="open_bill",
            label=f"{r.Vendor} bill", counterparty=r.Vendor, category=r.Category, ref=f"BILL-{r.Id}",
            confidence="high",
        ))
    return items


def _next_month_day(d: pd.Timestamp, day: int, months: int) -> pd.Timestamp:
    m = d + pd.DateOffset(months=months)
    return m.replace(day=min(day, m.days_in_month))


def _recurring(ledger: Ledger, ctx: ForecastContext) -> list[ProjectedItem]:
    out = ledger.operating_txns()
    out = out[(out["Direction"] == "out") & (out["TxnDate"] > ctx.as_of - pd.Timedelta(days=200))]
    open_bills = ledger.bills[ledger.bills["Status"] != "paid"]
    items: list[ProjectedItem] = []
    for (cp, cat), g in out.groupby(["Counterparty", "Category"]):
        g = g.sort_values("TxnDate")
        dates = g["TxnDate"].drop_duplicates()
        if len(dates) < 3:
            continue
        intervals = dates.diff().dt.days.dropna().tail(8)
        med = float(intervals.median())
        cadence = next((c for c in CADENCES if c[1] <= med <= c[2]), None)
        if cadence is None or float(intervals.std(ddof=0)) > 0.25 * med:
            continue
        name, _, _, step = cadence
        amount = float(g["Amount"].tail(6).median())

        # Continue after the last payment, or after the last *regular-sized* open bill
        # (a one-off bulk order from the same vendor must not hide the weekly pattern).
        last = g["TxnDate"].max()
        vb = open_bills[(open_bills["Vendor"] == cp) & (open_bills["Amount"].between(0.5 * amount, 1.5 * amount))]
        if not vb.empty:
            last = max(last, vb["DueDate"].max())

        day = int(g["TxnDate"].dt.day.tail(6).median())
        k = 1
        while True:
            if step:
                d = last + pd.Timedelta(days=step * k)
            else:
                d = _next_month_day(last, day, (1 if name == "monthly" else 2) * k)
            if d > ctx.horizon_end:
                break
            if d > ctx.as_of:
                amt = amount * (seasonal_index(ledger, d) if cat in COGS else 1.0)
                items.append(ProjectedItem(
                    date=d, amount=amt, direction="out", source="recurring",
                    label=f"{cp} ({name})", counterparty=cp, category=cat,
                    confidence="high" if cat in {"Rent", "Loan Repayment", "Software", "Payroll"} else "medium",
                ))
            k += 1
    return items


def _annual(ledger: Ledger, ctx: ForecastContext, recurring_cps: set[str]) -> list[ProjectedItem]:
    """Repeat last year's payments from infrequent counterparties (<= 4 payments a year)."""
    out = ledger.operating_txns()
    out = out[out["Direction"] == "out"]
    year = out[out["TxnDate"] > ctx.as_of - pd.Timedelta(days=365)]
    counts = year.groupby("Counterparty").size()
    open_bills = ledger.bills[ledger.bills["Status"] != "paid"]
    ly_start, ly_end = ctx.as_of - pd.Timedelta(days=365), ctx.horizon_end - pd.Timedelta(days=365)
    items = []
    for r in out[(out["TxnDate"] > ly_start) & (out["TxnDate"] <= ly_end)].itertuples():
        if r.Counterparty in recurring_cps or counts.get(r.Counterparty, 0) > 4 or r.Category == "Equipment":
            continue
        d = r.TxnDate + pd.Timedelta(days=365)
        covered = open_bills[(open_bills["Vendor"] == r.Counterparty)
                             & ((open_bills["DueDate"] - d).abs() <= pd.Timedelta(days=30))]
        if not covered.empty:
            continue
        items.append(ProjectedItem(
            date=d, amount=float(r.Amount), direction="out", source="annual",
            label=f"{r.Counterparty} (same time last year)", counterparty=r.Counterparty,
            category=r.Category, confidence="low",
        ))
    return items


def _retail_baseline(ledger: Ledger, ctx: ForecastContext) -> tuple[list[ProjectedItem], float]:
    weekly = _weekly_retail(ledger).tail(26)
    if len(weekly) < 4:
        return [], 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = SimpleExpSmoothing(weekly.to_numpy(dtype=float), initialization_method="estimated").fit()
    level = float(fit.forecast(1)[0])
    resid = weekly.to_numpy(dtype=float) - fit.fittedvalues
    sigma = float(np.std(resid[-13:], ddof=1)) if len(resid) > 2 else 0.1 * level
    # The level reflects the recent season; index each future week against the same base period.
    items = []
    for k in range(1, ctx.weeks + 1):
        start = ctx.as_of + pd.Timedelta(days=7 * (k - 1) + 1)
        idx = seasonal_index(ledger, start)
        items.append(ProjectedItem(
            date=start, amount=level * idx, direction="in", source="retail_baseline",
            label="Walk-in / card sales (forecast)", counterparty="Walk-in sales", category="Sales - Retail",
            confidence="medium",
        ))
    ctx.assumptions.append(
        f"Retail sales level {fmt_money(level, ledger.business.Currency)}/week (exponential smoothing of last 26 weeks), "
        "scaled by last year's seasonal pattern.")
    return items, sigma


def _b2b_baseline(ledger: Ledger, ctx: ForecastContext) -> list[ProjectedItem]:
    inv = ledger.invoices
    recent = inv[inv["IssueDate"] > ctx.as_of - pd.Timedelta(days=182)]
    delays = {c["customer"]: max(0.0, c["recentDaysLate"]) for c in customer_payment_behaviour(ledger)}
    items = []
    for customer, g in recent.groupby("Customer"):
        if g["IssueDate"].max() < ctx.as_of - pd.Timedelta(days=90):
            continue  # no recent orders - treat as inactive
        weekly_rate = float(g["Amount"].sum()) / 26
        collect_from = ctx.as_of + pd.Timedelta(days=30 + round(delays.get(customer, 0.0)))
        for k in range(1, ctx.weeks + 1):
            ws = ctx.as_of + pd.Timedelta(days=7 * (k - 1) + 1)
            we = ws + pd.Timedelta(days=6)
            days = (we - max(ws, collect_from)).days + 1
            if days <= 0:
                continue
            items.append(ProjectedItem(
                date=ws, amount=weekly_rate * min(days, 7) / 7, direction="in", source="b2b_baseline",
                label=f"Future invoices: {customer}", counterparty=customer, category="Sales - Catering",
                confidence="low",
            ))
    ctx.assumptions.append(
        "New catering invoices continue at each customer's 6-month billing rate, paid after 30-day terms "
        "plus that customer's recent average delay.")
    return items


# ---------------------------------------------------------------- public API

def build_context(ledger: Ledger, weeks: int = 13, buffer_weeks: float = 1.0) -> ForecastContext:
    t = ledger.window(90)
    weekly_out = float(t.loc[t["Direction"] == "out", "Amount"].sum()) / (90 / 7)
    return ForecastContext(
        as_of=ledger.as_of, weeks=weeks, opening_balance=ledger.operating_cash,
        buffer=round(buffer_weeks * weekly_out, 2), retail_sigma=0.0,
    )


def build_items(ledger: Ledger, ctx: ForecastContext) -> list[ProjectedItem]:
    items = _open_invoices(ledger, ctx) + _open_bills(ledger, ctx)
    recurring = _recurring(ledger, ctx)
    items += recurring + _annual(ledger, ctx, {i.counterparty for i in recurring})
    retail, sigma = _retail_baseline(ledger, ctx)
    ctx.retail_sigma = sigma
    items += retail + _b2b_baseline(ledger, ctx)
    ctx.assumptions += [
        "Open invoices arrive on due date + the customer's recent average delay; "
        "invoices more than 30 days overdue are treated as at-risk.",
        "Open bills are paid on their due date.",
        "Recurring payments (payroll, rent, suppliers, loan, fees, owner draws) continue on their detected cadence.",
        f"Safety buffer = {fmt_money(ctx.buffer, ledger.business.Currency)} (one week of average outgoings).",
        "Savings/reserve accounts are excluded from the operating balance.",
    ]
    return sorted(items, key=lambda i: (i.date, i.direction, -i.amount))


def aggregate(items: list[ProjectedItem], ctx: ForecastContext) -> dict:
    weeks = []
    balance = ctx.opening_balance
    var_cum = 0.0
    at_risk_cum = 0.0
    for k in range(1, ctx.weeks + 1):
        start = ctx.as_of + pd.Timedelta(days=7 * (k - 1) + 1)
        end = start + pd.Timedelta(days=6)
        wk = [i for i in items if ctx.week_of(i.date) == k]
        inflow = sum(i.amount for i in wk if i.direction == "in")
        outflow = sum(i.amount for i in wk if i.direction == "out")
        b2b_new = sum(i.amount for i in wk if i.source == "b2b_baseline")
        at_risk_cum += sum(i.amount for i in wk if i.at_risk)
        var_cum += ctx.retail_sigma ** 2 + (0.25 * b2b_new) ** 2
        sd = math.sqrt(var_cum)
        opening = balance
        balance = opening + inflow - outflow

        def by(direction: str) -> dict[str, float]:
            agg: dict[str, float] = {}
            for i in wk:
                if i.direction == direction:
                    agg[i.category or i.source] = agg.get(i.category or i.source, 0.0) + i.amount
            return {c: round(v, 2) for c, v in sorted(agg.items(), key=lambda kv: -kv[1])}

        drivers = sorted((i for i in wk if i.source not in {"retail_baseline", "b2b_baseline"}),
                         key=lambda i: -i.amount)[:4]
        weeks.append({
            "week": k,
            "start": start.date().isoformat(),
            "end": end.date().isoformat(),
            "opening": round(opening, 2),
            "inflows": round(inflow, 2),
            "outflows": round(outflow, 2),
            "net": round(inflow - outflow, 2),
            "closing": round(balance, 2),
            "p10": round(balance - Z_80 * sd - at_risk_cum, 2),
            "p90": round(balance + Z_80 * sd, 2),
            "inflowsByCategory": by("in"),
            "outflowsByCategory": by("out"),
            "drivers": [{"label": d.label, "amount": round(d.amount, 2), "direction": d.direction,
                         "date": d.date.date().isoformat()} for d in drivers],
        })

    lowest = min(weeks, key=lambda w: w["closing"])
    lowest_p10 = min(weeks, key=lambda w: w["p10"])
    first_negative = next((w["week"] for w in weeks if w["closing"] < 0), None)
    first_below_buffer = next((w["week"] for w in weeks if w["closing"] < ctx.buffer), None)
    first_p10_negative = next((w["week"] for w in weeks if w["p10"] < 0), None)
    return {
        "asOf": ctx.as_of.date().isoformat(),
        "weeks": weeks,
        "summary": {
            "openingBalance": round(ctx.opening_balance, 2),
            "endingBalance": weeks[-1]["closing"],
            "totalInflows": round(sum(w["inflows"] for w in weeks), 2),
            "totalOutflows": round(sum(w["outflows"] for w in weeks), 2),
            "lowestBalance": lowest["closing"],
            "lowestWeek": lowest["week"],
            "lowestWeekStart": lowest["start"],
            "lowestP10": lowest_p10["p10"],
            "safetyBuffer": ctx.buffer,
            "firstNegativeWeek": first_negative,
            "firstBelowBufferWeek": first_below_buffer,
            "firstP10NegativeWeek": first_p10_negative,
            "weeksBelowBuffer": sum(1 for w in weeks if w["closing"] < ctx.buffer),
            "shortfallAmount": round(max(0.0, ctx.buffer - lowest["closing"]), 2),
            "atRiskReceivables": round(sum(i.amount for i in items if i.at_risk), 2),
        },
        "assumptions": ctx.assumptions,
    }


def forecast(ledger: Ledger, weeks: int = 13, buffer_weeks: float = 1.0, include_items: bool = False) -> dict:
    ctx = build_context(ledger, weeks, buffer_weeks)
    items = build_items(ledger, ctx)
    result = aggregate(items, ctx)
    if include_items:
        result["items"] = [i.to_dict() for i in items]
    return result
