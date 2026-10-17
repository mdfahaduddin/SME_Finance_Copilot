"""Offline mode: a rule-based intent router used when no LLM is configured or the provider fails.

It plans tool calls from keywords and composes the answer from templates, so the demo, the tests
and judges' local runs work without an API key. Tool calls still go through the same policy gate
and audit log as the LLM agent.
"""
from __future__ import annotations

import re

from app import fx
from app.agent.tools import ToolContext

AMOUNT = re.compile(r"\$?\s?(\d[\d,]*(?:\.\d+)?)\s?(k|K|m|M|thousand)?\b")
EQUIPMENT = re.compile(r"\b(oven|equipment|machine|mixer|fridge|freezer|van|vehicle|truck|espresso|kitchen)\b", re.I)


def _amount(text: str) -> float | None:
    for mt in AMOUNT.finditer(text):
        v = float(mt.group(1).replace(",", ""))
        suf = (mt.group(2) or "").lower()
        v *= 1_000 if suf in ("k", "thousand") else 1_000_000 if suf == "m" else 1
        if v >= 100 and not (1990 <= v <= 2100 and not mt.group(0).startswith("$")):
            return v
    return None


def _has(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{w}", text) for w in words)


def plan(text: str, ctx: ToolContext) -> tuple[str, list[tuple[str, dict]]]:
    t = text.lower()
    amount = _amount(text)
    customers = sorted(set(ctx.ledger.invoices["Customer"]))
    customer = next((c for c in customers if c.split()[0].lower() in t), None)
    if customer is None and customers and re.search(r"\b(biggest|largest|top|main|best)\s+(customer|client)\b", t):
        customer = str(ctx.ledger.invoices.groupby("Customer")["Amount"].sum().idxmax())

    if _has(t, "report", "download", "export", "p&l", "profit and loss", "excel", "csv", "spreadsheet",
            "for my bank", "for the bank", "for my lender", "for my accountant"):
        return "reports", [("analyze_financials", {"section": "summary"})]
    if _has(t, "remind", "chase", "follow up", "follow-up") and "T2" in ctx_tiers(ctx):
        open_inv = ctx.ledger.invoices[ctx.ledger.invoices["Status"] == "open"]
        if customer:
            open_inv = open_inv[open_inv["Customer"] == customer]
        overdue = open_inv[open_inv["DueDate"] < ctx.ledger.as_of].sort_values("DueDate")
        if not overdue.empty:
            inv = overdue.iloc[0]
            return "reminder", [("request_payment_reminder", {
                "invoice_no": inv["InvoiceNo"], "tone": "friendly",
                "rationale": f"{inv['Customer']} invoice is overdue."})]
    if _has(t, "afford", "buy", "purchase") and amount:
        label = (EQUIPMENT.search(text).group(0) if EQUIPMENT.search(text) else "purchase").capitalize()
        return "afford", [
            ("run_scenario", {"changes": [{"type": "one_off_expense", "amount": amount, "week": 2, "label": label}]}),
            ("match_financing", {"amount": amount, "purpose": "equipment" if EQUIPMENT.search(text) else "working_capital"}),
        ]
    if _has(t, "loan", "financ", "borrow", "credit", "fund", "lender"):
        if amount:
            purpose = "equipment" if EQUIPMENT.search(text) else "expansion" if _has(t, "expan", "new location") \
                else "working_capital"
            return "financing", [("match_financing", {"amount": amount, "purpose": purpose})]
        return "financing", [("match_financing", {"use_forecast": True})]
    if customer and _has(t, "late", "delay", "pays? later", "lose", "lost"):
        change = {"type": "lose_customer", "customer": customer} if _has(t, "lose", "lost") else \
            {"type": "delay_customer", "customer": customer, "days": 30}
        return "scenario", [("run_scenario", {"changes": [change]})]
    if _has(t, "cash", "forecast", "run out", "runway", "shortfall", "next weeks", "next month", "balance"):
        return "forecast", [("forecast_cashflow", {})]
    if _has(t, "overdue", "owe", "receivable", "invoice", "late pay", "unpaid"):
        return "receivables", [("get_invoices", {"status": "open"})]
    if _has(t, "bill", "payable", "supplier", "vendor"):
        return "bills", [("get_bills", {"status": "unpaid"})]
    if _has(t, "alert", "risk", "warning", "worry", "problem"):
        return "alerts", [("get_alerts", {})]
    return "overview", [("analyze_financials", {"section": "summary"}), ("get_alerts", {})]


def ctx_tiers(ctx: ToolContext) -> set[str]:
    from app.agent.tools import ROLE_TIERS
    return ROLE_TIERS.get(ctx.user.role, set())


def compose(intent: str, results: dict[str, dict], currency: str = "USD") -> str:
    def m(x: float) -> str:  # every figure in the business's own currency
        return fx.fmt(x, currency)

    r = results
    if any("error" in v for v in r.values()):
        err = next(v["error"] for v in r.values() if "error" in v)
        return f"I couldn't complete that: {err}"

    if intent == "forecast":
        s = r["forecast_cashflow"]["summary"]
        lines = [f"**Your cash is forecast to bottom out at {m(s['lowestBalance'])} in week {s['lowestWeek']}** "
                 f"(week of {s['lowestWeekStart']})."]
        if s["firstNegativeWeek"]:
            lines.append(f"- Balance goes **negative in week {s['firstNegativeWeek']}**.")
        elif s["firstBelowBufferWeek"]:
            lines.append(f"- That is below your safety buffer of {m(s['safetyBuffer'])}: a gap of "
                         f"**{m(s['shortfallAmount'])}**.")
        lines.append(f"- Cautious case (P10): {m(s['lowestP10'])}. At-risk receivables: {m(s['atRiskReceivables'])}.")
        lines.append(f"- Balance after 13 weeks: {m(s['endingBalance'])} (from {m(s['openingBalance'])} today).")
        lines.append("\n**Next step:** chase overdue invoices and compare bridge financing before the low week.")
        return "\n".join(lines)

    if intent == "reports":
        a = r["analyze_financials"]
        return ("You can download these on the **Reports** page, filtered by period:\n"
                "- **Profit and loss** by month, **cash-flow forecast**, **aged receivables** and **transactions**, "
                "each as CSV or Excel\n"
                "- A two-page **financial summary PDF** to share with a bank, lender or accountant\n\n"
                f"Headline for the last 12 months: revenue {m(a['pnl12m']['revenue'])}, "
                f"net margin {a['pnl12m']['netMargin']:.1%}.")

    if intent == "overview":
        a = r["analyze_financials"]
        hs = a["healthScore"]
        weakest = min(hs["components"], key=lambda c: c["score"])
        lines = [f"**Financial health: {hs['score']:.0f}/100 ({hs['grade']}).** Weakest area: {weakest['label']} "
                 f"({weakest['value']}).",
                 f"- Revenue (12 months): {m(a['pnl12m']['revenue'])}, net margin {a['pnl12m']['netMargin']:.1%}.",
                 f"- Cash cover: {a['liquidity']['cashCoverMonths']} months; overdue receivables "
                 f"{m(a['receivables']['overdueTotal'])}."]
        alerts = r.get("get_alerts", {}).get("alerts", [])[:3]
        if alerts:
            lines.append("\n**Top alerts:**")
            lines += [f"- {x['title']}" for x in alerts]
        return "\n".join(lines)

    if intent == "receivables":
        inv = r["get_invoices"]
        overdue = [i for i in inv["invoices"] if i.get("daysPastDue", 0) > 0]
        lines = [f"**{inv['count']} open invoices worth {m(inv['total'])}**; {inv['overdueCount']} overdue "
                 f"({m(inv['overdueTotal'])})."]
        lines += [f"- {i['invoiceNo']} {i['customer']}: {m(i['amount'])}, {i['daysPastDue']} "
                  f"day{'s' if i['daysPastDue'] != 1 else ''} overdue"
                  for i in sorted(overdue, key=lambda i: -i["daysPastDue"])[:5]]
        if any("security_warning" in (i.get("memo") or {}) for i in inv["invoices"]):
            lines.append("\n⚠️ One invoice memo contains instructions aimed at an AI assistant. I ignored it; "
                         "please review that record.")
        return "\n".join(lines)

    if intent == "bills":
        b = r["get_bills"]
        lines = [f"**{b['count']} unpaid bills totalling {m(b['total'])}.** Next due:"]
        lines += [f"- {x['dueDate']}: {x['vendor']} {m(x['amount'])}" for x in b["bills"][:6]]
        return "\n".join(lines)

    if intent == "alerts":
        al = r["get_alerts"]["alerts"]
        return "\n".join([f"**{len(al)} active alerts:**"] +
                         [f"- **{x['title']}** ({x['severity']}): {x['suggested_action']}" for x in al[:5]])

    if intent in ("financing", "afford"):
        lines = []
        if intent == "afford":
            sc = r["run_scenario"]
            lines.append(f"**{sc['verdict']}**")
        fin = r["match_financing"]
        if "message" in fin:
            return "\n".join(lines + [fin["message"]])
        need = fin["need"]
        lines.append(f"\n**Best financing options for {m(need['amount'])} ({need['purpose'].replace('_', ' ')}):**")
        for e in fin["eligible"][:3]:
            lines.append(f"{e['rank']}. **{e['lender']} - {e['name']}**: ~{e['estimatedApr']:.1%} APR, "
                         f"{m(e['monthlyPayment'])}/month over {e['termMonths']} months, total cost {m(e['totalCost'])}. "
                         + (e["reasons"][0] if e["reasons"] else ""))
        if not fin["eligible"]:
            lines.append("No eligible products for this request.")
        lines.append(f"\n_{fin['disclaimer']}_")
        return "\n".join(lines)

    if intent == "scenario":
        sc = r["run_scenario"]
        return (f"**{sc['verdict']}**\n- Scenario: {sc['changes'][0]['description']}\n"
                f"- Lowest balance changes by {m(sc['delta']['lowestBalance'])}.")

    if intent == "reminder":
        req = r["request_payment_reminder"]
        return (f"I've prepared request **#{req['requestId']}**: {req['summary']}.\n\n"
                "Nothing has been sent yet. It needs approval in the **Approvals** queue.")

    return "I couldn't work that out in offline mode."


OFFLINE_NOTE = "_Offline mode: answers come from rule-based templates. Connect an OpenAI key for full conversation._"
