"""Financial analysis engine: KPIs, risk metrics and an explainable health score.

Definitions (trailing windows end on the ledger's as_of date):
  revenue            inflows in "Sales - *" categories
  COGS               ingredients + packaging
  operating profit   revenue - COGS - operating expenses (payroll, rent, utilities, ...)
  net profit         operating profit - interest - taxes - owner compensation (owner draws)
  cash cover         total cash / average monthly cash outflow (months the business could
                     pay all its bills with zero new revenue)
  DSO / DPO          receivables (payables) outstanding / credit sales (vendor bills) per day
  DSCR               (operating profit - owner compensation) / annual debt service
"""
from __future__ import annotations

import pandas as pd

from app.engines.ledger import (
    COGS, DEBT_SERVICE, MIN_MONTHS_FOR_SCORE, OPEX, OWNER, REVENUE_PREFIX, TAXES, Ledger, linear_score,
)

# Health score sub-scores: (key, label, weight)
HEALTH_WEIGHTS = {
    "liquidity": 0.25,
    "profitability": 0.20,
    "growth": 0.15,
    "working_capital": 0.15,
    "debt": 0.15,
    "stability": 0.10,
}


def _sum(df: pd.DataFrame, mask) -> float:
    return float(df.loc[mask, "Amount"].sum())


def _is_revenue(df: pd.DataFrame):
    return (df["Direction"] == "in") & df["Category"].str.startswith(REVENUE_PREFIX)


def profit_and_loss(ledger: Ledger, days: int) -> dict:
    t = ledger.window(days)
    out = t["Direction"] == "out"
    revenue = _sum(t, _is_revenue(t))
    cogs = _sum(t, out & t["Category"].isin(COGS))
    opex = _sum(t, out & t["Category"].isin(OPEX))
    taxes = _sum(t, out & t["Category"].isin(TAXES))
    owner = _sum(t, out & t["Category"].isin(OWNER))
    debt_service = _sum(t, out & t["Category"].isin(DEBT_SERVICE))
    interest = _estimated_interest(ledger, days)
    operating_profit = revenue - cogs - opex
    net_profit = operating_profit - interest - taxes - owner
    return {
        "days": days,
        "revenue": round(revenue, 2),
        "cogs": round(cogs, 2),
        "grossProfit": round(revenue - cogs, 2),
        "operatingExpenses": round(opex, 2),
        "operatingProfit": round(operating_profit, 2),
        "interest": round(interest, 2),
        "taxes": round(taxes, 2),
        "ownerCompensation": round(owner, 2),
        "netProfit": round(net_profit, 2),
        "debtService": round(debt_service, 2),
        "grossMargin": round((revenue - cogs) / revenue, 4) if revenue else 0.0,
        "operatingMargin": round(operating_profit / revenue, 4) if revenue else 0.0,
        "netMargin": round(net_profit / revenue, 4) if revenue else 0.0,
    }


def _estimated_interest(ledger: Ledger, days: int) -> float:
    if ledger.loans.empty:
        return 0.0
    monthly = (ledger.loans["Outstanding"] * ledger.loans["AnnualRate"] / 12).sum()
    return float(monthly * days / 30.4375)


def monthly_series(ledger: Ledger, months: int = 12) -> list[dict]:
    """Calendar-month revenue, costs and net cash flow for charts (current month is partial)."""
    t = ledger.operating_txns().copy()
    t["Month"] = t["TxnDate"].dt.to_period("M")
    last = ledger.as_of.to_period("M")
    periods = pd.period_range(last - (months - 1), last, freq="M")
    rows = []
    for p in periods:
        m = t[t["Month"] == p]
        out = m["Direction"] == "out"
        revenue = _sum(m, _is_revenue(m))
        rows.append({
            "month": str(p),
            "partial": p == last,
            "revenue": round(revenue, 2),
            "cogs": round(_sum(m, out & m["Category"].isin(COGS)), 2),
            "operatingExpenses": round(_sum(m, out & m["Category"].isin(OPEX)), 2),
            "inflows": round(_sum(m, m["Direction"] == "in"), 2),
            "outflows": round(_sum(m, out), 2),
            "netCashFlow": round(float(m["Signed"].sum()), 2),
        })
    return rows


def expense_breakdown(ledger: Ledger, days: int = 365) -> list[dict]:
    t = ledger.window(days)
    t = t[t["Direction"] == "out"]
    total = float(t["Amount"].sum())
    by = t.groupby("Category")["Amount"].sum().sort_values(ascending=False)
    return [{"category": c, "amount": round(float(v), 2), "share": round(float(v) / total, 4)}
            for c, v in by.items()]


def expense_anomalies(ledger: Ledger, lookback_months: int = 6, z: float = 2.0) -> list[dict]:
    """Flag (category, month) spending above the trailing-12-month mean + z * std of that category.

    Categories paid several times a month (payroll, weekly suppliers) are compared on
    average payment size x typical payments per month, so a month that simply contains
    an extra pay run or an extra Monday is not reported as an anomaly.
    """
    t = ledger.operating_txns()
    t = t[(t["Direction"] == "out") & t["Category"].isin(OPEX | COGS)].copy()
    t["Month"] = t["TxnDate"].dt.to_period("M")
    sums = t.pivot_table(index="Month", columns="Category", values="Amount", aggfunc="sum", fill_value=0.0)
    counts = t.pivot_table(index="Month", columns="Category", values="Amount", aggfunc="count", fill_value=0)
    pivot = sums.copy()
    for cat in sums.columns:
        typical_count = float(counts[cat][counts[cat] > 0].median())
        if typical_count >= 2:
            pivot[cat] = (sums[cat] / counts[cat].where(counts[cat] > 0)).fillna(0.0) * typical_count
    last_full = ledger.as_of.to_period("M") - 1  # skip the partial current month
    found = []
    for i in range(lookback_months):
        month = last_full - i
        if month not in pivot.index:
            continue
        history = pivot.loc[(pivot.index < month) & (pivot.index >= month - 12)]
        if len(history) < 6:
            continue
        for cat in pivot.columns:
            value = float(pivot.at[month, cat])
            mean, std = float(history[cat].mean()), float(history[cat].std(ddof=0))
            threshold = mean + z * max(std, 0.05 * mean)  # floor std so flat series aren't over-sensitive
            if value > threshold and value - mean > 500:
                found.append({
                    "category": cat,
                    "month": str(month),
                    "amount": round(value, 2),
                    "typical": round(mean, 2),
                    "excess": round(value - mean, 2),
                    "monthsAgo": i + 1,
                })
    return sorted(found, key=lambda a: a["monthsAgo"])


def receivables(ledger: Ledger) -> dict:
    inv = ledger.invoices
    open_inv = inv[inv["Status"] == "open"].copy()
    open_inv["DaysPastDue"] = (ledger.as_of - open_inv["DueDate"]).dt.days
    buckets = {"current": 0.0, "1-30": 0.0, "31-60": 0.0, "61-90": 0.0, "90+": 0.0}
    for d, amt in zip(open_inv["DaysPastDue"], open_inv["Amount"]):
        key = ("current" if d <= 0 else "1-30" if d <= 30 else "31-60" if d <= 60
               else "61-90" if d <= 90 else "90+")
        buckets[key] += float(amt)
    total_open = float(open_inv["Amount"].sum())
    credit_sales_90 = float(inv[inv["IssueDate"] > ledger.as_of - pd.Timedelta(days=90)]["Amount"].sum())
    dso = total_open / (credit_sales_90 / 90) if credit_sales_90 else 0.0
    overdue = open_inv[open_inv["DaysPastDue"] > 0].sort_values("DaysPastDue", ascending=False)
    return {
        "openTotal": round(total_open, 2),
        "openCount": int(len(open_inv)),
        "overdueTotal": round(float(overdue["Amount"].sum()), 2),
        "aging": {k: round(v, 2) for k, v in buckets.items()},
        "dso": round(dso, 1),
        "overdueInvoices": [
            {"invoiceNo": r.InvoiceNo, "customer": r.Customer, "amount": float(r.Amount),
             "dueDate": r.DueDate.date().isoformat(), "daysPastDue": int(r.DaysPastDue)}
            for r in overdue.itertuples()
        ],
    }


def customer_payment_behaviour(ledger: Ledger, recent: int = 3) -> list[dict]:
    """Average days paid after due date per customer, overall vs. most recent invoices."""
    paid = ledger.invoices[ledger.invoices["Status"] == "paid"].copy()
    paid = paid[paid["PaidDate"] > ledger.as_of - pd.Timedelta(days=365)]
    paid["Delay"] = (paid["PaidDate"] - paid["DueDate"]).dt.days
    rows = []
    for customer, g in paid.sort_values("PaidDate").groupby("Customer"):
        overall = float(g["Delay"].mean())
        latest = float(g["Delay"].tail(recent).mean())
        rows.append({
            "customer": customer,
            "invoicesPaid": int(len(g)),
            "avgDaysLate": round(overall, 1),
            "recentDaysLate": round(latest, 1),
            "trend": "worsening" if latest - overall > 7 else "improving" if overall - latest > 7 else "stable",
        })
    return sorted(rows, key=lambda r: -r["recentDaysLate"])


def payables(ledger: Ledger) -> dict:
    b = ledger.bills
    open_b = b[b["Status"] != "paid"]
    billed_90 = float(b[b["IssueDate"] > ledger.as_of - pd.Timedelta(days=90)]["Amount"].sum())
    total_open = float(open_b["Amount"].sum())
    return {
        "openTotal": round(total_open, 2),
        "openCount": int(len(open_b)),
        "overdueTotal": round(float(open_b[open_b["DueDate"] < ledger.as_of]["Amount"].sum()), 2),
        "dpo": round(total_open / (billed_90 / 90), 1) if billed_90 else 0.0,
    }


def concentration(ledger: Ledger, days: int = 365) -> dict:
    t = ledger.window(days)
    rev = t[_is_revenue(t)]
    total = float(rev["Amount"].sum())
    b2b = rev[rev["InvoiceId"].notna()]  # invoiced (B2B) sales; the rest is walk-in / card revenue
    b2b_total = float(b2b["Amount"].sum())
    by = b2b.groupby("Counterparty")["Amount"].sum().sort_values(ascending=False)
    shares_b2b = by / b2b_total if b2b_total else by * 0
    hhi = float((shares_b2b ** 2).sum())  # Herfindahl index across B2B customers (0-1)
    top = by.index[0] if len(by) else None
    return {
        "retailShare": round((total - b2b_total) / total, 4) if total else 0.0,
        "b2bShare": round(b2b_total / total, 4) if total else 0.0,
        "topCustomer": top,
        "topCustomerShareOfTotal": round(float(by.iloc[0]) / total, 4) if top else 0.0,
        "topCustomerShareOfB2B": round(float(shares_b2b.iloc[0]), 4) if top else 0.0,
        "top3ShareOfTotal": round(float(by.head(3).sum()) / total, 4) if total else 0.0,
        "b2bHhi": round(hhi, 4),
        "customers": [{"customer": c, "revenue": round(float(v), 2), "shareOfTotal": round(float(v) / total, 4)}
                      for c, v in by.items()],
    }


def liquidity(ledger: Ledger) -> dict:
    t = ledger.window(90)
    months = 90 / 30.4375
    avg_out = float(t.loc[t["Direction"] == "out", "Amount"].sum()) / months
    avg_in = float(t.loc[t["Direction"] == "in", "Amount"].sum()) / months
    net_burn = avg_out - avg_in
    cash = ledger.total_cash
    return {
        "operatingCash": round(ledger.operating_cash, 2),
        "totalCash": round(cash, 2),
        "avgMonthlyInflow": round(avg_in, 2),
        "avgMonthlyOutflow": round(avg_out, 2),
        "netMonthlyBurn": round(net_burn, 2),
        "cashCoverMonths": round(cash / avg_out, 2) if avg_out else None,
        # Runway only applies when the business is losing cash.
        "runwayMonths": round(cash / net_burn, 1) if net_burn > 0 else None,
    }


def growth(ledger: Ledger) -> dict:
    t = ledger.operating_txns()
    rev = t[_is_revenue(t)]

    def window(end: pd.Timestamp, days: int) -> float:
        return float(rev[(rev["TxnDate"] > end - pd.Timedelta(days=days)) & (rev["TxnDate"] <= end)]["Amount"].sum())

    a = ledger.as_of
    last90 = window(a, 90)
    prev_year_90 = window(a - pd.Timedelta(days=365), 90)
    last30 = window(a, 30)
    prev30 = window(a - pd.Timedelta(days=30), 30)
    monthly = pd.Series([m["revenue"] for m in monthly_series(ledger) if not m["partial"]])
    cv = float(monthly.std(ddof=0) / monthly.mean()) if len(monthly) > 1 and monthly.mean() else 0.0
    return {
        "revenueGrowthYoY": round(last90 / prev_year_90 - 1, 4) if prev_year_90 else None,
        "revenueGrowthMoM": round(last30 / prev30 - 1, 4) if prev30 else None,
        "revenueVolatility": round(cv, 4),
    }


def debt(ledger: Ledger, pnl_12m: dict) -> dict:
    annual_service = float((ledger.loans["MonthlyPayment"] * 12).sum()) if not ledger.loans.empty else 0.0
    cash_for_debt = pnl_12m["operatingProfit"] - pnl_12m["ownerCompensation"]
    return {
        "outstanding": round(float(ledger.loans["Outstanding"].sum()), 2) if not ledger.loans.empty else 0.0,
        "annualDebtService": round(annual_service, 2),
        "cashAvailableForDebtService": round(cash_for_debt, 2),
        "dscr": round(cash_for_debt / annual_service, 2) if annual_service else None,
        "loans": [
            {"lender": r.Lender, "type": r.LoanType, "outstanding": float(r.Outstanding),
             "monthlyPayment": float(r.MonthlyPayment), "rate": float(r.AnnualRate)}
            for r in ledger.loans.itertuples()
        ],
    }


def health_score(liq: dict, pnl: dict, gr: dict, ar: dict, dbt: dict, conc: dict) -> dict:
    """Weighted 0-100 score from transparent piecewise-linear sub-scores."""
    cover = liq["cashCoverMonths"] or 0.0
    yoy = gr["revenueGrowthYoY"]
    dscr = dbt["dscr"]
    top_share = conc["topCustomerShareOfTotal"]
    # Without a year of history growth is unknown: score it neutral and say so, rather than show "+0.0%".
    growth_score = linear_score(yoy, -0.10, 0.20) if yoy is not None else 50.0
    growth_value = f"{yoy:+.1%} revenue YoY" if yoy is not None else "needs 12+ months of history"
    # No debt service means no repayment pressure: full marks, shown as "no loans" instead of an invented ratio.
    debt_score = linear_score(dscr, 1.0, 2.0) if dscr is not None else 100.0
    debt_value = f"{dscr:.2f}x DSCR" if dscr is not None else "no loan repayments"

    parts = {
        "liquidity": (
            "Liquidity", linear_score(cover, 0.0, 3.0), f"{cover:.1f} months of cash cover",
            "Cash covers all outgoings for {v:.1f} months with zero revenue (target: 3+).".format(v=cover)),
        "profitability": (
            "Profitability", linear_score(pnl["netMargin"], -0.05, 0.15), f"{pnl['netMargin']:.1%} net margin",
            "Net margin after owner pay, interest and tax (0 at -5%, full marks at 15%+)."),
        "growth": (
            "Growth", growth_score, growth_value,
            "Last 90 days revenue vs the same period last year (0 at -10%, full marks at +20%)."),
        "working_capital": (
            "Collections", linear_score(ar["dso"], 90, 30), f"{ar['dso']:.0f} days DSO",
            "How fast B2B customers pay (full marks at 30 days or less, 0 at 90+)."),
        "debt": (
            "Debt capacity", debt_score, debt_value,
            "Cash available for debt payments vs annual debt service (lenders want 1.25x+)."),
        "stability": (
            "Revenue stability",
            0.7 * linear_score(top_share, 0.5, 0.1) + 0.3 * linear_score(gr["revenueVolatility"], 0.4, 0.05),
            f"top client {top_share:.0%} of revenue",
            "Dependence on the largest customer and month-to-month revenue swings."),
    }
    components = []
    total = 0.0
    for key, (label, score, value, explanation) in parts.items():
        w = HEALTH_WEIGHTS[key]
        total += score * w
        components.append({
            "key": key, "label": label, "score": round(score, 1), "weight": w,
            "contribution": round(score * w, 1), "value": value, "explanation": explanation,
        })
    total = round(total, 1)
    grade = ("Excellent" if total >= 80 else "Good" if total >= 65 else "Fair" if total >= 50
             else "Weak" if total >= 35 else "Critical")
    weakest = min(components, key=lambda c: c["score"])
    return {"score": total, "grade": grade, "components": components, "weakestArea": weakest["label"]}


def insufficient_history(ledger: Ledger) -> dict:
    return {"score": None, "grade": "Not enough data", "components": [], "weakestArea": None,
            "message": f"The health score needs at least {MIN_MONTHS_FOR_SCORE} months of transactions "
                       f"(you have {ledger.months_of_history}). Import more bank history to unlock it."}


def analyze(ledger: Ledger) -> dict:
    pnl_12m = profit_and_loss(ledger, 365)
    pnl_90d = profit_and_loss(ledger, 90)
    liq = liquidity(ledger)
    gr = growth(ledger)
    ar = receivables(ledger)
    dbt = debt(ledger, pnl_12m)
    conc = concentration(ledger)
    return {
        "asOf": ledger.as_of.date().isoformat(),
        "business": {
            "name": ledger.business.Name,
            "industry": ledger.business.Industry,
            "yearsInBusiness": round(ledger.years_in_business, 1),
            "employees": ledger.business.Employees,
            "creditScore": ledger.business.CreditScore,
            "monthsOfHistory": ledger.months_of_history,
            "currency": ledger.business.Currency,
        },
        "healthScore": health_score(liq, pnl_12m, gr, ar, dbt, conc)
        if ledger.months_of_history >= MIN_MONTHS_FOR_SCORE else insufficient_history(ledger),
        "pnl12m": pnl_12m,
        "pnl90d": pnl_90d,
        "liquidity": liq,
        "growth": gr,
        "receivables": ar,
        "customerPayments": customer_payment_behaviour(ledger),
        "payables": payables(ledger),
        "debt": dbt,
        "concentration": conc,
        "expenseBreakdown": expense_breakdown(ledger),
        "expenseAnomalies": expense_anomalies(ledger),
        "monthly": monthly_series(ledger),
    }
