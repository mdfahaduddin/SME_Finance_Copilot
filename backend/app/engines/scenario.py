"""What-if simulator: modify the projected cash-flow items and compare with the baseline.

Supported changes (combinable):
  delay_customer   {"customer": str, "days": int}             a customer pays N days later
  lose_customer    {"customer": str}                           no new invoices from a customer
  revenue_change   {"pct": float}                              retail + new B2B sales up/down (0.1 = +10%)
  one_off_expense  {"amount": float, "week": int, "label": str} e.g. buying equipment outright
  new_loan         {"amount": float, "apr": float, "term_months": int, "week": int}
  defer_bill       {"vendor": str, "days": int}                ask a supplier to accept later payment
  new_hire         {"monthly_cost": float, "start_week": int}  fully loaded salary, paid bi-weekly
"""
from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field

import pandas as pd

from app.engines.forecast import ProjectedItem, aggregate, build_context, build_items
from app.engines.ledger import Ledger, fmt_money
from app.engines.ledger import fmt_money as _fmt

CHANGE_TYPES = {"delay_customer", "lose_customer", "revenue_change", "one_off_expense", "new_loan",
                "defer_bill", "new_hire"}


@dataclass
class Change:
    type: str
    params: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.type not in CHANGE_TYPES:
            raise ValueError(f"Unknown change type '{self.type}'. Use one of {sorted(CHANGE_TYPES)}")


def _week_start(as_of: pd.Timestamp, week: int) -> pd.Timestamp:
    return as_of + pd.Timedelta(days=7 * (max(1, week) - 1) + 1)


def apply_change(items: list[ProjectedItem], change: Change, as_of: pd.Timestamp, horizon_end: pd.Timestamp,
                 currency: str = "USD") -> tuple[list[ProjectedItem], str]:
    p = change.params
    t = change.type
    if t == "delay_customer":
        days = int(p["days"])
        out = []
        for i in items:
            if i.direction == "in" and i.counterparty == p["customer"] and i.source in {"open_invoice", "b2b_baseline"}:
                i = copy(i)
                i.date = i.date + pd.Timedelta(days=days)
                if i.date > horizon_end:
                    continue  # pushed out of the forecast window
            out.append(i)
        return out, f"{p['customer']} pays {days} days later"
    if t == "lose_customer":
        out = [i for i in items if not (i.source == "b2b_baseline" and i.counterparty == p["customer"])]
        return out, f"No new orders from {p['customer']}"
    if t == "revenue_change":
        pct = float(p["pct"])
        out = []
        for i in items:
            if i.source in {"retail_baseline", "b2b_baseline"}:
                i = copy(i)
                i.amount *= 1 + pct
            out.append(i)
        return out, f"Sales {pct:+.0%}"
    if t == "one_off_expense":
        d = _week_start(as_of, int(p.get("week", 1)))
        label = p.get("label", "One-off expense")
        return items + [ProjectedItem(d, float(p["amount"]), "out", "scenario", label, category="Scenario")], \
            f"{label} {fmt_money(float(p['amount']), currency)} in week {p.get('week', 1)}"
    if t == "new_loan":
        amount, apr, term = float(p["amount"]), float(p.get("apr", 0.12)), int(p.get("term_months", 24))
        start = _week_start(as_of, int(p.get("week", 1)))
        r = apr / 12
        pay = amount / term if r == 0 else amount * r / (1 - (1 + r) ** -term)
        new = [ProjectedItem(start, amount, "in", "scenario", "Loan funds received", category="Financing")]
        for m in range(1, term + 1):
            d = start + pd.DateOffset(months=m)
            if d > horizon_end:
                break
            new.append(ProjectedItem(d, pay, "out", "scenario", "New loan repayment", category="Loan Repayment"))
        return items + new, f"New {fmt_money(amount, currency)} loan at {apr:.1%} over {term} months"
    if t == "defer_bill":
        days = int(p["days"])
        out = []
        for i in items:
            if i.source == "open_bill" and i.counterparty == p["vendor"]:
                i = copy(i)
                i.date = i.date + pd.Timedelta(days=days)
                if i.date > horizon_end:
                    continue
            out.append(i)
        return out, f"Pay {p['vendor']} bills {days} days later"
    if t == "new_hire":
        per_run = float(p["monthly_cost"]) * 12 / 26
        d = _week_start(as_of, int(p.get("start_week", 1)))
        new = []
        while d <= horizon_end:
            new.append(ProjectedItem(d, per_run, "out", "scenario", "New hire payroll", category="Payroll"))
            d += pd.Timedelta(days=14)
        return items + new, f"New hire costing {fmt_money(float(p['monthly_cost']), currency)}/month"
    raise ValueError(t)


def run_scenario(ledger: Ledger, changes: list[Change], weeks: int = 13, buffer_weeks: float = 1.0) -> dict:
    ctx = build_context(ledger, weeks, buffer_weeks)
    items = build_items(ledger, ctx)
    baseline = aggregate(items, ctx)

    modified = items
    descriptions = []
    for c in changes:
        modified, desc = apply_change(modified, c, ctx.as_of, ctx.horizon_end, ledger.business.Currency)
        descriptions.append(desc)
    scenario = aggregate(modified, ctx)

    b, s = baseline["summary"], scenario["summary"]
    return {
        "asOf": baseline["asOf"],
        "changes": [{"type": c.type, "params": c.params, "description": d} for c, d in zip(changes, descriptions)],
        "baseline": b,
        "scenario": s,
        "delta": {
            "lowestBalance": round(s["lowestBalance"] - b["lowestBalance"], 2),
            "endingBalance": round(s["endingBalance"] - b["endingBalance"], 2),
            "weeksBelowBuffer": s["weeksBelowBuffer"] - b["weeksBelowBuffer"],
        },
        "weeks": [
            {"week": bw["week"], "start": bw["start"], "baseline": bw["closing"], "scenario": sw["closing"],
             "scenarioP10": sw["p10"], "scenarioP90": sw["p90"]}
            for bw, sw in zip(baseline["weeks"], scenario["weeks"])
        ],
        "verdict": _verdict(s, ledger.business.Currency),
    }


def _verdict(s: dict, currency: str = "USD") -> str:
    def fmt_money(x: float) -> str:
        return _fmt(x, currency)

    if s["firstNegativeWeek"]:
        return (f"Not affordable as-is: cash goes negative in week {s['firstNegativeWeek']} "
                f"(lowest {fmt_money(s['lowestBalance'])}).")
    if s["firstBelowBufferWeek"]:
        return (f"Tight: cash stays positive but drops below the safety buffer in week "
                f"{s['firstBelowBufferWeek']} (lowest {fmt_money(s['lowestBalance'])}).")
    return f"Comfortable: cash stays above the safety buffer (lowest {fmt_money(s['lowestBalance'])})."
