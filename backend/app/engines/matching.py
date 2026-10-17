"""Financing matcher: eligibility filters + transparent weighted scoring.

Step 1  Need: an explicit request (amount, purpose, term) or one derived from the
        cash-flow forecast's shortfall.
Step 2  Hard eligibility rules per product. Every failed rule is reported, so the owner
        sees why a product is not available (fair-lending style transparency).
Step 3  Eligible products are scored 0-100:
            cost of credit          35%  APR incl. fees, estimated for the business's credit score
            fit to purpose          20%  e.g. credit line for a short gap, equipment loan for an asset
            approval likelihood     20%  margin above the lender's minimums
            repayment affordability 15%  DSCR after adding the new payment (lenders want >= 1.25x)
            speed                   10%  days to funds, vs. when the money is needed
Step 4  Ranked results with monthly payment, total cost, reasons and watch-outs.

Currencies: everything is computed and reported in the business's own currency. A product's amount and revenue
limits are set in the product's currency and converted at indicative rates (app/fx.py) before comparison.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app import fx
from app.engines.ledger import Ledger, linear_score
from app.models import FinProduct

WEIGHTS = {"cost": 0.35, "fit": 0.20, "approval": 0.20, "affordability": 0.15, "speed": 0.10}
PURPOSES = {"working_capital", "bridge", "equipment", "expansion", "refinance"}
AMORTIZING = {"term_loan", "equipment"}

# How well each product type suits each purpose (0-100).
FIT = {
    "bridge":          {"credit_line": 100, "invoice_finance": 90, "term_loan": 55, "merchant_advance": 40},
    "working_capital": {"credit_line": 90, "term_loan": 80, "invoice_finance": 75, "merchant_advance": 35},
    "equipment":       {"equipment": 100, "gov_grant": 100, "term_loan": 70},
    "expansion":       {"term_loan": 100, "gov_grant": 80, "equipment": 60, "credit_line": 40},
    "refinance":       {"term_loan": 100},
}


@dataclass
class FinancingNeed:
    amount: float
    purpose: str = "working_capital"
    term_months: int | None = None
    needed_within_days: int | None = None
    source: str = "user"  # user | forecast

    def __post_init__(self):
        if self.purpose not in PURPOSES:
            raise ValueError(f"purpose must be one of {sorted(PURPOSES)}")
        if self.amount <= 0:
            raise ValueError("amount must be positive")


@dataclass
class Limits:
    """A product's amount and revenue limits converted into the business's currency."""
    min_amount: float
    max_amount: float
    min_revenue: float
    max_revenue: float | None

    @classmethod
    def of(cls, p: FinProduct, currency: str) -> "Limits":
        r = fx.rate(p.Currency or "USD", currency)
        return cls(p.MinAmount * r, p.MaxAmount * r, (p.MinAnnualRevenue or 0) * r,
                   None if p.MaxAnnualRevenue is None else p.MaxAnnualRevenue * r)


def need_from_forecast(fc: dict) -> FinancingNeed | None:
    """Size a bridge facility to lift the forecast's lowest point back to the safety buffer (+10%)."""
    s = fc["summary"]
    if not s["shortfallAmount"]:
        return None
    amount = math.ceil(s["shortfallAmount"] * 1.10 / 1000) * 1000
    weeks_below = max(1, s["weeksBelowBuffer"])
    return FinancingNeed(
        amount=amount, purpose="bridge", term_months=max(3, math.ceil(weeks_below / 4.33) + 2),
        needed_within_days=max(1, (s["lowestWeek"] - 1) * 7), source="forecast",
    )


def estimate_apr(p: FinProduct, credit_score: int) -> float:
    """Place the business within the lender's APR range by credit score (760+ -> best rate, 580- -> worst)."""
    t = min(1.0, max(0.0, (760 - credit_score) / (760 - 580)))
    return p.AprMin + t * (p.AprMax - p.AprMin)


def payment_and_cost(p: FinProduct, amount: float, apr: float, months: int) -> tuple[float, float]:
    """Return (monthly payment, total cost of credit incl. fees)."""
    fee = amount * (p.OriginationFeePct or 0.0)
    if p.ProductType == "gov_grant" or months == 0:
        return 0.0, 0.0
    r = apr / 12
    if p.ProductType in AMORTIZING:
        pay = amount / months if r == 0 else amount * r / (1 - (1 + r) ** -months)
        return pay, pay * months - amount + fee
    # Credit lines, invoice finance, cash advances: interest on the drawn amount, principal repaid over the term.
    interest = amount * apr * months / 12
    return (amount + interest) / months, interest + fee


def _max_amount_reason(lim: Limits, cur: str) -> str:
    return f"Maximum amount is {fx.fmt(lim.max_amount, cur)}"


def _eligibility(p: FinProduct, need: FinancingNeed, ledger: Ledger, lim: Limits) -> list[str]:
    b = ledger.business
    cur = b.Currency
    revenue = b.AnnualRevenue
    years = ledger.years_in_business
    reasons = []
    if need.amount < lim.min_amount:
        reasons.append(f"Minimum amount is {fx.fmt(lim.min_amount, cur)}")
    if need.amount > lim.max_amount:
        reasons.append(_max_amount_reason(lim, cur))
    if revenue < lim.min_revenue:
        reasons.append(f"Requires {fx.fmt(lim.min_revenue, cur)}+ annual revenue (you: {fx.fmt(revenue, cur)})")
    if lim.max_revenue is not None and revenue > lim.max_revenue:
        reasons.append(f"Only for businesses under {fx.fmt(lim.max_revenue, cur)} revenue")
    if years < p.MinYearsInBusiness:
        reasons.append(f"Requires {p.MinYearsInBusiness:g}+ years trading (you: {years:.1f})")
    if ledger.credit_score < p.MinCreditScore:
        you = "not provided" if ledger.credit_score_assumed else str(ledger.credit_score)
        reasons.append(f"Requires credit score {p.MinCreditScore}+ (you: {you})")
    if p.RequiresCollateral and not b.HasCollateral:
        reasons.append("Requires collateral (property or other pledged assets)")
    excluded = {s.strip() for s in p.ExcludedIndustries.split(",") if s.strip()}
    eligible = {s.strip() for s in p.EligibleIndustries.split(",") if s.strip()}
    if b.Industry in excluded or (eligible and b.Industry not in eligible):
        reasons.append(f"Not available to the {b.Industry} industry")
    if need.purpose not in {s.strip() for s in p.Purposes.split(",")}:
        reasons.append(f"Not designed for {need.purpose.replace('_', ' ')}")
    return reasons


def _approval_score(p: FinProduct, ledger: Ledger, lim: Limits) -> float:
    b = ledger.business
    margins = [
        min(1.0, (ledger.credit_score - p.MinCreditScore) / 100) if p.MinCreditScore else 1.0,
        min(1.0, b.AnnualRevenue / lim.min_revenue - 1) if lim.min_revenue else 1.0,
        min(1.0, (ledger.years_in_business - p.MinYearsInBusiness) / 3),
    ]
    score = 40 + 60 * sum(max(0.0, m) for m in margins) / len(margins)
    if p.ProductType == "gov_grant":
        score = min(score, 50)  # grants are competitive regardless of eligibility
    return score


def match(ledger: Ledger, analysis: dict, need: FinancingNeed) -> dict:
    debt = analysis["debt"]
    cash_for_debt = debt["cashAvailableForDebtService"]
    existing_service = debt["annualDebtService"]
    receivables_open = analysis["receivables"]["openTotal"]
    cur = ledger.business.Currency
    converted = {}  # product currency -> rate into the business currency, for the disclosure

    eligible, ineligible = [], []
    for p in ledger.products:
        lim = Limits.of(p, cur)
        if (p.Currency or "USD") != cur:
            converted[p.Currency or "USD"] = fx.rate(p.Currency or "USD", cur)
        base = {
            "productId": p.Id, "lender": p.Lender, "name": p.Name, "type": p.ProductType,
            "description": p.Description, "fundingDays": p.FundingDays,
            "aprRange": [p.AprMin, p.AprMax], "amountRange": [round(lim.min_amount, 2), round(lim.max_amount, 2)],
        }
        reasons = _eligibility(p, need, ledger, lim)
        if reasons:
            row = {**base, "eligible": False, "ineligibleReasons": reasons}
            if reasons == [_max_amount_reason(lim, cur)]:
                row["partialAmount"] = round(lim.max_amount, 2)  # could still fund part of the need
            ineligible.append(row)
            continue

        months = need.term_months or (p.TermMonthsMax if p.ProductType in AMORTIZING else p.TermMonthsMin)
        revolving = p.ProductType == "credit_line"
        if p.ProductType == "gov_grant":
            months = 0
        elif not revolving:  # a revolving line can be repaid early, so cost the period actually needed
            months = min(max(months, p.TermMonthsMin), p.TermMonthsMax)
        apr = estimate_apr(p, ledger.credit_score)
        monthly, total_cost = payment_and_cost(p, need.amount, apr, months)
        effective_apr = apr + ((p.OriginationFeePct or 0) / (months / 12) if months else 0)

        why, watch = [], []
        fit = FIT.get(need.purpose, {}).get(p.ProductType, 30)
        if p.ProductType == "invoice_finance":
            if receivables_open >= need.amount * 1.2:
                why.append(f"You have {fx.fmt(receivables_open, cur)} in open invoices to borrow against")
            else:
                fit -= 40
                watch.append(f"Only {fx.fmt(receivables_open, cur)} of open invoices; may not support the full amount")
        if (need.term_months and not revolving and months
                and not (p.TermMonthsMin <= need.term_months <= p.TermMonthsMax)):
            fit -= 20
            watch.append(f"Term adjusted to {months} months (product range {p.TermMonthsMin}-{p.TermMonthsMax})")

        new_service = monthly * 12 if p.ProductType in AMORTIZING else total_cost * 12 / max(months, 1)
        dscr_after = cash_for_debt / (existing_service + new_service) if (existing_service + new_service) else 9.99
        affordability = linear_score(dscr_after, 1.0, 2.0)
        if dscr_after < 1.25:
            watch.append(f"Debt service coverage would fall to {dscr_after:.2f}x (lenders want 1.25x+)")

        if ledger.credit_score_assumed and p.ProductType != "gov_grant":
            watch.append(f"Rate assumes a credit score of {ledger.credit_score}; add yours in Settings for a sharper estimate")

        speed = linear_score(p.FundingDays, 60, 2)
        if need.needed_within_days and p.FundingDays > need.needed_within_days:
            speed = 0.0
            watch.append(f"Typically funds in {p.FundingDays} days; you need it within {need.needed_within_days}")

        cost = 100.0 if p.ProductType == "gov_grant" else linear_score(effective_apr, 0.40, 0.0)
        approval = _approval_score(p, ledger, lim)

        if p.ProductType == "gov_grant":
            why.append("Non-repayable grant: no interest or repayments")
            watch.append("Competitive application; decision takes about 2 months")
        elif effective_apr <= 0.12:
            why.append(f"Low cost: about {apr:.1%} APR for your credit profile")
        elif effective_apr >= 0.35:
            watch.append(f"Very expensive: effective APR about {effective_apr:.0%}")
        if revolving:
            why.append("Revolving: draw only what you need and pay interest only on that")
            if months < p.TermMonthsMax:
                why.append(f"Costed for {months} months of use; the facility stays open for {p.TermMonthsMax}")
        if p.ProductType == "merchant_advance":
            watch.append("Repaid from daily card sales; reduces cash every day")
        if p.FundingDays <= 3:
            why.append(f"Fast: funds in about {p.FundingDays} day(s)")
        if fit >= 90:
            why.append(f"Well suited to {need.purpose.replace('_', ' ')}")

        scores = {"cost": cost, "fit": max(0.0, fit), "approval": approval,
                  "affordability": affordability, "speed": speed}
        total = sum(scores[k] * w for k, w in WEIGHTS.items())
        eligible.append({
            **base, "eligible": True,
            "score": round(total, 1),
            "scores": {k: round(v, 1) for k, v in scores.items()},
            "estimatedApr": round(apr, 4),
            "effectiveApr": round(effective_apr, 4),
            "termMonths": months,
            "monthlyPayment": round(monthly, 2),
            "totalCost": round(total_cost, 2),
            "dscrAfter": round(dscr_after, 2),
            "reasons": why,
            "watchOuts": watch,
        })

    eligible.sort(key=lambda r: -r["score"])
    for i, r in enumerate(eligible, 1):
        r["rank"] = i
    disclaimer = ("Estimates for comparison only, based on indicative lender criteria. "
                  "Actual rates and approval depend on the lender's assessment. Not financial advice.")
    if converted:
        disclaimer += " Lender limits set in " + ", ".join(
            f"{c} were converted at 1 {c} = {r:,.4g} {cur}" for c, r in sorted(converted.items())) + " (indicative rate)."
    return {
        "currency": cur,
        "fx": [{"from": c, "to": cur, "rate": r} for c, r in sorted(converted.items())],
        "need": {"amount": need.amount, "purpose": need.purpose, "termMonths": need.term_months,
                 "neededWithinDays": need.needed_within_days, "source": need.source},
        "profile": {
            "annualRevenue": ledger.business.AnnualRevenue, "yearsInBusiness": round(ledger.years_in_business, 1),
            "creditScore": ledger.business.CreditScore, "creditScoreAssumed": ledger.credit_score_assumed,
            "creditScoreUsed": ledger.credit_score, "hasCollateral": ledger.business.HasCollateral,
            "industry": ledger.business.Industry,
        },
        "weights": WEIGHTS,
        "eligible": eligible,
        "ineligible": ineligible,
        "disclaimer": disclaimer,
    }
