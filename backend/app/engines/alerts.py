"""Rule-based alert engine.

Runs after analysis + forecast. Every alert explains *why* it fired and carries a
concrete suggested action the copilot can expand on. Fingerprints let repeated runs
update an existing alert instead of creating duplicates.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.engines.ledger import fmt_money

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class AlertCandidate:
    alert_type: str
    severity: str
    title: str
    detail: str
    suggested_action: str
    fingerprint: str

    def to_dict(self) -> dict:
        return asdict(self)


def _money(analysis: dict):
    currency = analysis.get("business", {}).get("currency", "USD")
    return lambda x: fmt_money(x, currency)


def _chase_list(analysis: dict, limit: int = 3) -> str:
    fmt_money = _money(analysis)
    overdue = analysis["receivables"]["overdueInvoices"][:limit]
    if not overdue:
        return ""
    return "; ".join(f"{i['invoiceNo']} ({i['customer']}, {fmt_money(i['amount'])})" for i in overdue)


def evaluate(analysis: dict, forecast: dict) -> list[AlertCandidate]:
    fmt_money = _money(analysis)
    alerts: list[AlertCandidate] = []
    s = forecast["summary"]
    weeks = {w["week"]: w for w in forecast["weeks"]}
    chase = _chase_list(analysis)

    # 1. Projected negative balance
    if s["firstNegativeWeek"]:
        w = weeks[s["firstNegativeWeek"]]
        alerts.append(AlertCandidate(
            "cash_shortfall", "critical",
            f"Cash projected to go negative in week {w['week']}",
            f"Operating balance is forecast to reach {fmt_money(w['closing'])} in the week of {w['start']}. "
            f"Lowest point: {fmt_money(s['lowestBalance'])} in week {s['lowestWeek']}.",
            "Chase overdue invoices" + (f" ({chase})" if chase else "")
            + ", ask suppliers to move non-urgent bills, or arrange a short-term credit line now.",
            "cash_shortfall",
        ))
    # 2. Below safety buffer (but not negative)
    elif s["firstBelowBufferWeek"]:
        w = weeks[s["lowestWeek"]]
        top = ", ".join(f"{d['label']} {fmt_money(d['amount'])}" for d in w["drivers"][:3] if d["direction"] == "out")
        alerts.append(AlertCandidate(
            "low_cash", "high",
            f"Cash drops below safety buffer in week {s['firstBelowBufferWeek']}",
            f"Balance is forecast to fall to {fmt_money(s['lowestBalance'])} in the week of {w['start']} "
            f"(buffer {fmt_money(s['safetyBuffer'])}). Main outflows that week: {top}.",
            f"Cover the {fmt_money(s['shortfallAmount'])} gap: collect overdue invoices"
            + (f" ({chase})" if chase else "")
            + ", reschedule a large bill, or line up a credit line before then.",
            "low_cash",
        ))

    # 3. Downside scenario
    if s["firstP10NegativeWeek"] and not s["firstNegativeWeek"]:
        alerts.append(AlertCandidate(
            "downside_risk", "medium",
            f"Downside case goes negative in week {s['firstP10NegativeWeek']}",
            f"If sales come in weak and at-risk receivables ({fmt_money(s['atRiskReceivables'])}) slip, "
            f"the balance could reach {fmt_money(s['lowestP10'])}.",
            "Treat the downside as a real possibility: keep a funding option ready and avoid new discretionary spend.",
            "downside_risk",
        ))

    # 4. Overdue invoices (> 30 days), grouped by customer
    by_customer: dict[str, list[dict]] = {}
    for inv in analysis["receivables"]["overdueInvoices"]:
        if inv["daysPastDue"] > 30:
            by_customer.setdefault(inv["customer"], []).append(inv)
    for customer, invs in by_customer.items():
        total = sum(i["amount"] for i in invs)
        oldest = max(i["daysPastDue"] for i in invs)
        alerts.append(AlertCandidate(
            "overdue_receivable", "high" if oldest > 60 else "medium",
            f"{customer} owes {fmt_money(total)} more than 30 days overdue",
            f"{len(invs)} invoice(s): " + ", ".join(f"{i['invoiceNo']} ({i['daysPastDue']} days)" for i in invs) + ".",
            f"Send a payment reminder to {customer} and consider requiring deposits on new orders.",
            f"overdue:{customer}",
        ))

    # 5. Customers paying later and later
    for c in analysis["customerPayments"]:
        if c["trend"] == "worsening":
            alerts.append(AlertCandidate(
                "slipping_payer", "medium",
                f"{c['customer']} is paying later",
                f"Recent invoices were paid {c['recentDaysLate']:.0f} days late on average vs "
                f"{c['avgDaysLate']:.0f} days over the past year.",
                "Discuss payment terms, offer a small early-payment discount, or invoice-finance their receivables.",
                f"slipping:{c['customer']}",
            ))

    # 6. Expense anomalies
    for a in analysis["expenseAnomalies"]:
        alerts.append(AlertCandidate(
            "expense_anomaly", "medium" if a["monthsAgo"] <= 2 else "low",
            f"Unusual {a['category'].lower()} spend in {a['month']}",
            f"{fmt_money(a['amount'])} vs a typical {fmt_money(a['typical'])} per month (+{fmt_money(a['excess'])}).",
            f"Review {a['category'].lower()} costs for {a['month']} and check whether this will recur.",
            f"anomaly:{a['category']}:{a['month']}",
        ))

    # 7. Customer concentration
    conc = analysis["concentration"]
    if conc["topCustomer"] and conc["topCustomerShareOfTotal"] > 0.30:
        sev, share, scope = "medium", conc["topCustomerShareOfTotal"], "total revenue"
    elif conc["topCustomer"] and conc["topCustomerShareOfB2B"] > 0.30:
        sev, share, scope = "low", conc["topCustomerShareOfB2B"], "catering (B2B) revenue"
    else:
        sev = ""
    if sev:
        alerts.append(AlertCandidate(
            "concentration", sev,
            f"{conc['topCustomer']} is {share:.0%} of {scope}",
            f"Losing this customer would remove about {fmt_money(conc['customers'][0]['revenue'])} a year.",
            "Broaden the catering client base and avoid extending this customer more credit.",
            "concentration",
        ))

    # 8. Runway (only when the business is losing cash)
    runway = analysis["liquidity"]["runwayMonths"]
    if runway is not None and runway < 3:
        alerts.append(AlertCandidate(
            "short_runway", "high",
            f"Only {runway:.1f} months of runway",
            f"The business is burning {fmt_money(analysis['liquidity']['netMonthlyBurn'])} a month net.",
            "Cut discretionary costs and secure funding before runway falls below 2 months.",
            "short_runway",
        ))

    # 9. Loan payment at risk within the next week
    if analysis["debt"]["loans"]:
        payment = sum(l["monthlyPayment"] for l in analysis["debt"]["loans"])
        w1 = forecast["weeks"][0]
        if w1["closing"] < payment:
            alerts.append(AlertCandidate(
                "loan_payment_risk", "critical",
                "Not enough cash for next loan payment",
                f"Loan payments of {fmt_money(payment)} are due soon but the balance is forecast at {fmt_money(w1['closing'])}.",
                "Move funds from reserves or contact the lender before the due date to avoid a default.",
                "loan_payment_risk",
            ))

    return sorted(alerts, key=lambda a: SEVERITY_ORDER[a.severity])


def sync_alerts(session: Session, business_id: int, candidates: list[AlertCandidate]) -> list[models.SmeAlert]:
    """Upsert alerts by fingerprint; auto-resolve open alerts whose condition has cleared."""
    existing = {a.Fingerprint: a for a in session.scalars(
        select(models.SmeAlert).where(models.SmeAlert.BusinessId == business_id,
                                      models.SmeAlert.Status != "resolved"))}
    seen = set()
    for c in candidates:
        seen.add(c.fingerprint)
        row = existing.get(c.fingerprint)
        if row is None:
            row = models.SmeAlert(BusinessId=business_id, Fingerprint=c.fingerprint, Status="open")
            session.add(row)
        row.AlertType, row.Severity, row.Title = c.alert_type, c.severity, c.title
        row.Detail, row.SuggestedAction = c.detail, c.suggested_action
    for fp, row in existing.items():
        if fp not in seen:
            row.Status = "resolved"
    session.commit()
    return list(session.scalars(
        select(models.SmeAlert).where(models.SmeAlert.BusinessId == business_id, models.SmeAlert.Status != "resolved")))
