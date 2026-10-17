"""Tier-2 actions and the human-in-the-loop approval queue.

Every action with an external or financial effect goes through:

    request_action()  -> AgentActionRequest(status="pending")    [user or agent]
    approve()/reject() -> human decision by an allowed role        [never the agent]
    execute()          -> runs once against the sandbox             [on approval]

Safety rules enforced here (not by the LLM):
  * Parameters are validated with Pydantic and resolved against the caller's own business.
  * Amounts come from the referenced records (bill, invoice, product), never from free text.
  * Per-action and per-day limits; requests above them are refused outright.
  * Approvals of amounts >= the re-authentication threshold require the approver's password.
  * The limits are defined once in USD and applied in each business's own currency (see safety_limits).
  * Idempotency: an identical pending request is returned instead of duplicated, and a
    request can only move approved -> executed once.
  * Requests expire after 24 hours.
  * Every step is written to the hash-chained audit log.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session

from app import audit, fx, models
from app.auth import CurrentUser
from app.engines.matching import Limits
from app.models import utcnow
from app.security import verify_password

# Safety limits in USD. Each business gets them in its own currency: converted at the indicative rate (app/fx.py)
# and rounded to two significant figures, e.g. BDT 610,000 for the $5,000 password re-confirmation threshold.
REAUTH_THRESHOLD = 5_000.0
REQUEST_TTL = timedelta(hours=24)
SCHEDULE_PAYMENT_MAX = 10_000.0
SCHEDULE_PAYMENT_DAILY_MAX = 25_000.0


@dataclass(frozen=True)
class SafetyLimits:
    currency: str
    reauth: float        # approvals of this amount or more need the approver's password
    payment_max: float   # largest single scheduled payment
    daily_max: float     # total scheduled payments per rolling day

    def fmt(self, amount: float, decimals: int = 0) -> str:
        return fx.fmt(amount, self.currency, decimals)


def safety_limits(currency: str) -> SafetyLimits:
    try:
        r = fx.rate("USD", currency)
    except fx.UnknownCurrency:
        r = 1.0  # no rate: the USD figures apply as-is (stricter for most currencies, never looser)
    if r == 1.0:
        return SafetyLimits(currency, REAUTH_THRESHOLD, SCHEDULE_PAYMENT_MAX, SCHEDULE_PAYMENT_DAILY_MAX)
    return SafetyLimits(currency, fx.nice(REAUTH_THRESHOLD * r), fx.nice(SCHEDULE_PAYMENT_MAX * r),
                        fx.nice(SCHEDULE_PAYMENT_DAILY_MAX * r))


def business_limits(db: Session, business_id: int) -> SafetyLimits:
    return safety_limits(db.get(models.SmeBusiness, business_id).Currency)


class ActionError(Exception):
    """Raised for invalid or refused action requests (mapped to HTTP 400/403 by the API)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- parameter schemas

class ActionParams(BaseModel):
    # snake_case (agent) or camelCase (UI); unknown fields such as a client-supplied "amount" are refused.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class SubmitLoanApplication(ActionParams):
    product_id: int = Field(gt=0)
    amount: float = Field(gt=0, le=100_000_000_000)  # business currency; the product's limits are checked below
    term_months: int = Field(ge=0, le=120)
    purpose: str = Field(min_length=3, max_length=300)


class SendPaymentReminder(ActionParams):
    invoice_no: str = Field(pattern=r"^INV-\d{1,8}$")
    tone: str = Field(default="friendly", pattern=r"^(friendly|firm)$")


class SchedulePayment(ActionParams):
    bill_id: int = Field(gt=0)
    pay_date: date


class RequestBillDeferral(ActionParams):
    bill_id: int = Field(gt=0)
    new_due_date: date


@dataclass(frozen=True)
class ActionSpec:
    name: str
    schema: type[ActionParams]
    approver_roles: tuple[str, ...]
    description: str


ACTIONS: dict[str, ActionSpec] = {
    "submit_loan_application": ActionSpec(
        "submit_loan_application", SubmitLoanApplication, ("owner",),
        "Submit a financing application to a (sandbox) lender."),
    "send_payment_reminder": ActionSpec(
        "send_payment_reminder", SendPaymentReminder, ("owner", "accountant"),
        "Email a payment reminder to a customer about an open invoice."),
    "schedule_payment": ActionSpec(
        "schedule_payment", SchedulePayment, ("owner",),
        "Schedule payment of an open bill (per-payment and daily limits apply; see the policy in Settings)."),
    "request_bill_deferral": ActionSpec(
        "request_bill_deferral", RequestBillDeferral, ("owner",),
        "Ask a supplier to accept later payment of a bill."),
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _as_of(db: Session, business_id: int) -> date:
    return db.get(models.SmeBusiness, business_id).today


# ---------------------------------------------------------------- request preparation
# Each preparer validates against the caller's business and returns (amount, risk, summary, params).

def _prepare_loan(db: Session, user: CurrentUser, p: SubmitLoanApplication):
    product = db.get(models.FinProduct, p.product_id)
    if product is None:
        raise ActionError("Unknown product")
    cur = db.get(models.SmeBusiness, user.business_id).Currency
    try:
        lim = Limits.of(product, cur)
    except fx.UnknownCurrency as e:
        raise ActionError(str(e)) from None
    if not (lim.min_amount <= p.amount <= lim.max_amount):
        raise ActionError(f"Amount must be between {fx.fmt(lim.min_amount, cur)} and {fx.fmt(lim.max_amount, cur)}")
    summary = f"Apply to {product.Lender} for {fx.fmt(p.amount, cur)} ({product.Name}, {p.term_months} months)"
    return p.amount, "high", summary, p.model_dump()  # snake_case keys


def _prepare_reminder(db: Session, user: CurrentUser, p: SendPaymentReminder):
    inv = db.scalar(select(models.SmeInvoice).where(
        models.SmeInvoice.InvoiceNo == p.invoice_no, models.SmeInvoice.BusinessId == user.business_id))
    if inv is None:
        raise ActionError("Invoice not found")
    if inv.Status != "open":
        raise ActionError(f"Invoice {inv.InvoiceNo} is not open")
    lim = business_limits(db, user.business_id)
    return inv.Amount, "low", f"Send {p.tone} reminder to {inv.Customer} for {inv.InvoiceNo} ({lim.fmt(inv.Amount)})", \
        p.model_dump()


def _open_bill(db: Session, user: CurrentUser, bill_id: int) -> models.SmeBill:
    bill = db.get(models.SmeBill, bill_id)
    if bill is None or bill.BusinessId != user.business_id:
        raise ActionError("Bill not found")
    if bill.Status != "open":
        raise ActionError(f"Bill {bill_id} is not open (status: {bill.Status})")
    return bill


def _prepare_schedule(db: Session, user: CurrentUser, p: SchedulePayment):
    bill = _open_bill(db, user, p.bill_id)
    today = _as_of(db, user.business_id)
    if p.pay_date < today:
        raise ActionError("Payment date cannot be in the past")
    if p.pay_date > bill.DueDate + timedelta(days=30):
        raise ActionError("Payment date is more than 30 days after the due date")
    lim = business_limits(db, user.business_id)
    if bill.Amount > lim.payment_max:
        raise ActionError(f"Amount {lim.fmt(bill.Amount)} exceeds the {lim.fmt(lim.payment_max)} per-payment limit; "
                          "pay this bill directly through your bank.", 403)
    already = db.scalar(select(func.coalesce(func.sum(models.AgentActionRequest.Amount), 0.0)).where(
        models.AgentActionRequest.BusinessId == user.business_id,
        models.AgentActionRequest.Tool == "schedule_payment",
        models.AgentActionRequest.Status.in_(["pending", "approved", "executed"]),
        models.AgentActionRequest.CreatedAt >= utcnow() - timedelta(days=1),
    ))
    if already + bill.Amount > lim.daily_max:
        raise ActionError(f"Daily scheduled-payment limit of {lim.fmt(lim.daily_max)} would be exceeded", 403)
    risk = "high" if bill.Amount >= lim.reauth else "medium"
    return bill.Amount, risk, f"Pay {bill.Vendor} {lim.fmt(bill.Amount)} on {p.pay_date.isoformat()}", \
        {"bill_id": p.bill_id, "pay_date": p.pay_date.isoformat()}


def _prepare_deferral(db: Session, user: CurrentUser, p: RequestBillDeferral):
    bill = _open_bill(db, user, p.bill_id)
    if p.new_due_date <= bill.DueDate:
        raise ActionError("New due date must be after the current due date")
    if p.new_due_date > bill.DueDate + timedelta(days=60):
        raise ActionError("Deferral requests are limited to 60 days")
    amount = business_limits(db, user.business_id).fmt(bill.Amount)
    return bill.Amount, "medium", f"Ask {bill.Vendor} to move {amount} bill from {bill.DueDate} to {p.new_due_date}", \
        {"bill_id": p.bill_id, "new_due_date": p.new_due_date.isoformat()}


PREPARERS: dict[str, Callable] = {
    "submit_loan_application": _prepare_loan,
    "send_payment_reminder": _prepare_reminder,
    "schedule_payment": _prepare_schedule,
    "request_bill_deferral": _prepare_deferral,
}


# ---------------------------------------------------------------- executors (sandbox side effects)

def _outbox(db: Session, req: models.AgentActionRequest, recipient: str, subject: str, body: str) -> None:
    db.add(models.SmeOutboxMessage(BusinessId=req.BusinessId, ActionRequestId=req.Id, Recipient=recipient,
                                   Subject=subject, Body=body))


def _exec_loan(db: Session, req: models.AgentActionRequest, p: dict) -> dict:
    product = db.get(models.FinProduct, p["product_id"])
    biz = db.get(models.SmeBusiness, req.BusinessId)
    ref = f"{_slug(product.Lender)[:4].upper()}-{req.Id:05d}"
    app_row = models.LoanApplication(
        BusinessId=req.BusinessId, ProductId=product.Id, Amount=p["amount"], TermMonths=p["term_months"],
        Purpose=p["purpose"], Status="submitted", ReferenceNo=ref, SubmittedAt=utcnow(),
        PayloadJson=json.dumps({"business": biz.Name, "annualRevenue": biz.AnnualRevenue,
                                "creditScore": biz.CreditScore, "product": product.Name}),
    )
    db.add(app_row)
    _outbox(db, req, f"applications@{_slug(product.Lender)}.example",
            f"Financing application {ref} - {biz.Name}",
            f"{biz.Name} applies for {fx.fmt(p['amount'], biz.Currency)} ({product.Name}) over {p['term_months']} months.\n"
            f"Purpose: {p['purpose']}\nReference: {ref}")
    return {"message": f"Application {ref} prepared for {product.Lender}. Send it to the lender to apply.",
            "referenceNo": ref}


def _exec_reminder(db: Session, req: models.AgentActionRequest, p: dict) -> dict:
    inv = db.scalar(select(models.SmeInvoice).where(models.SmeInvoice.InvoiceNo == p["invoice_no"],
                                                    models.SmeInvoice.BusinessId == req.BusinessId))
    if inv.Status != "open":
        raise ActionError(f"Invoice {inv.InvoiceNo} was paid in the meantime; reminder not sent")
    biz = db.get(models.SmeBusiness, req.BusinessId)
    days = (biz.today - inv.DueDate).days
    status_line = f"is now {days} days overdue" if days > 0 else f"is due on {inv.DueDate:%d %b %Y}"
    opener = "Just a friendly reminder" if p["tone"] == "friendly" else "This is a reminder"
    body = (f"Hello {inv.Customer} team,\n\n{opener} that invoice {inv.InvoiceNo} for {fx.fmt(inv.Amount, biz.Currency, 2)} "
            f"{status_line}. Please arrange payment at your earliest convenience.\n\nThank you,\n{biz.Name}")
    _outbox(db, req, inv.CustomerEmail, f"Payment reminder: {inv.InvoiceNo}", body)
    return {"message": f"Reminder for {inv.InvoiceNo} for {inv.Customer} is ready in the outbox. "
                       "It is not emailed automatically."}


def _exec_schedule(db: Session, req: models.AgentActionRequest, p: dict) -> dict:
    bill = db.get(models.SmeBill, p["bill_id"])
    if bill.Status != "open":
        raise ActionError(f"Bill {bill.Id} is no longer open")
    bill.Status = "scheduled"
    bill.ScheduledDate = date.fromisoformat(p["pay_date"])
    amount = fx.fmt(bill.Amount, db.get(models.SmeBusiness, req.BusinessId).Currency)
    return {"message": f"Payment of {amount} to {bill.Vendor} marked as scheduled for {p['pay_date']}. "
                       "Make the payment in your bank on that date."}


def _exec_deferral(db: Session, req: models.AgentActionRequest, p: dict) -> dict:
    bill = db.get(models.SmeBill, p["bill_id"])
    biz = db.get(models.SmeBusiness, req.BusinessId)
    _outbox(db, req, f"accounts@{_slug(bill.Vendor)}.example", f"Request to extend payment date - {biz.Name}",
            f"Hello {bill.Vendor},\n\nCould we move payment of our {fx.fmt(bill.Amount, biz.Currency, 2)} bill due {bill.DueDate:%d %b %Y} "
            f"to {date.fromisoformat(p['new_due_date']):%d %b %Y}? We value our partnership and will confirm "
            f"payment on the new date.\n\nKind regards,\n{biz.Name}")
    return {"message": f"Deferral request for {bill.Vendor} is ready in the outbox. The due date changes once they agree."}


EXECUTORS: dict[str, Callable] = {
    "submit_loan_application": _exec_loan,
    "send_payment_reminder": _exec_reminder,
    "schedule_payment": _exec_schedule,
    "request_bill_deferral": _exec_deferral,
}


# ---------------------------------------------------------------- queue operations

def _idempotency_key(business_id: int, tool: str, params: dict) -> str:
    raw = f"{business_id}|{tool}|{audit.canonical_json(params)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def expire_stale(db: Session, business_id: int) -> int:
    rows = db.scalars(select(models.AgentActionRequest).where(
        models.AgentActionRequest.BusinessId == business_id,
        models.AgentActionRequest.Status == "pending",
        models.AgentActionRequest.ExpiresAt < utcnow())).all()
    for r in rows:
        r.Status = "expired"
        audit.record(db, action="action.expired", actor="system", actor_type="system", business_id=business_id,
                     tool=r.Tool, tier="T2", decision="expired", result=f"Request #{r.Id} expired", commit=False)
    if rows:
        db.commit()
    return len(rows)


def request_action(db: Session, user: CurrentUser, tool: str, raw_params: dict[str, Any], *,
                   via: str = "ui", rationale: str = "") -> models.AgentActionRequest:
    spec = ACTIONS.get(tool)
    if spec is None:
        raise ActionError(f"Unknown action '{tool}'")
    if user.role == "viewer":
        raise ActionError("Viewers cannot request actions", 403)
    try:
        params = spec.schema.model_validate(raw_params)
    except ValidationError as e:
        raise ActionError("Invalid parameters: " + "; ".join(
            f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()))
    amount, risk, summary, clean = PREPARERS[tool](db, user, params)

    key = _idempotency_key(user.business_id, tool, clean)
    existing = db.scalar(select(models.AgentActionRequest).where(models.AgentActionRequest.IdempotencyKey == key))
    if existing is not None and existing.Status == "pending":
        return existing
    if existing is not None:
        key = f"{key}:{utcnow().timestamp():.0f}"  # same action again after an earlier decision

    req = models.AgentActionRequest(
        BusinessId=user.business_id, Tool=tool, Summary=summary, RequestedVia=via,
        ParamsJson=json.dumps(clean, sort_keys=True), Rationale=rationale[:2000], RiskLevel=risk, Amount=amount,
        Status="pending", IdempotencyKey=key, RequestedBy=user.id, ExpiresAt=utcnow() + REQUEST_TTL,
    )
    db.add(req)
    db.flush()
    audit.record(db, action="action.requested", actor=user.label if via == "ui" else f"agent for {user.label}",
                 actor_type="user" if via == "ui" else "agent", business_id=user.business_id, tool=tool,
                 tier="T2", params=clean, decision="pending", result=f"Request #{req.Id}: {summary}", commit=False)
    db.commit()
    return req


def _get_pending(db: Session, user: CurrentUser, request_id: int) -> models.AgentActionRequest:
    expire_stale(db, user.business_id)
    req = db.get(models.AgentActionRequest, request_id)
    if req is None or req.BusinessId != user.business_id:
        raise ActionError("Request not found", 404)
    if req.Status != "pending":
        raise ActionError(f"Request is already {req.Status}", 409)
    return req


def approve(db: Session, user: CurrentUser, request_id: int, password: str | None = None,
            reason: str = "") -> models.AgentActionRequest:
    req = _get_pending(db, user, request_id)
    spec = ACTIONS[req.Tool]
    if user.role not in spec.approver_roles:
        audit.record(db, action="action.approve_denied", actor=user.label, actor_type="user",
                     business_id=user.business_id, tool=req.Tool, tier="T2", decision="denied",
                     result=f"Request #{req.Id}: role '{user.role}' not allowed")
        raise ActionError(f"Only {' or '.join(spec.approver_roles)} can approve this action", 403)
    lim = business_limits(db, req.BusinessId)
    if (req.Amount or 0) >= lim.reauth:
        db_user = db.get(models.SmeUser, user.id)
        if not password or not verify_password(password, db_user.PasswordHash):
            audit.record(db, action="action.reauth_failed", actor=user.label, actor_type="user",
                         business_id=user.business_id, tool=req.Tool, tier="T2", decision="denied",
                         result=f"Request #{req.Id}: password confirmation failed")
            raise ActionError(f"Confirm your password to approve actions of {lim.fmt(lim.reauth)} or more", 403)

    req.Status, req.DecidedBy, req.DecidedAt, req.DecisionReason = "approved", user.id, utcnow(), reason[:1000]
    audit.record(db, action="action.approved", actor=user.label, actor_type="user", business_id=user.business_id,
                 tool=req.Tool, tier="T2", decision="approved", result=f"Request #{req.Id}: {req.Summary}",
                 commit=False)
    db.commit()
    return execute(db, req)


def execute(db: Session, req: models.AgentActionRequest) -> models.AgentActionRequest:
    # Guard against double execution (e.g. a retried request).
    if req.Status != "approved":
        raise ActionError(f"Cannot execute a request that is {req.Status}", 409)
    params = json.loads(req.ParamsJson)
    try:
        result = EXECUTORS[req.Tool](db, req, params)
        req.Status, req.ResultJson = "executed", json.dumps(result)
        audit.record(db, action="action.executed", actor="system", actor_type="system", business_id=req.BusinessId,
                     tool=req.Tool, tier="T2", params=params, decision="executed",
                     result=f"Request #{req.Id}: {result['message']}", commit=False)
    except ActionError as e:
        req.Status, req.ResultJson = "failed", json.dumps({"message": str(e)})
        audit.record(db, action="action.failed", actor="system", actor_type="system", business_id=req.BusinessId,
                     tool=req.Tool, tier="T2", params=params, decision="failed", result=f"Request #{req.Id}: {e}",
                     commit=False)
    db.commit()
    return req


def reject(db: Session, user: CurrentUser, request_id: int, reason: str = "") -> models.AgentActionRequest:
    req = _get_pending(db, user, request_id)
    if user.role not in ACTIONS[req.Tool].approver_roles:
        raise ActionError("You are not allowed to decide on this action", 403)
    req.Status, req.DecidedBy, req.DecidedAt, req.DecisionReason = "rejected", user.id, utcnow(), reason[:1000]
    audit.record(db, action="action.rejected", actor=user.label, actor_type="user", business_id=user.business_id,
                 tool=req.Tool, tier="T2", decision="rejected", result=f"Request #{req.Id}: {reason or 'no reason'}",
                 commit=False)
    db.commit()
    return req


def to_dict(req: models.AgentActionRequest) -> dict:
    return {
        "id": req.Id, "tool": req.Tool, "summary": req.Summary, "requestedVia": req.RequestedVia,
        "params": json.loads(req.ParamsJson), "rationale": req.Rationale, "riskLevel": req.RiskLevel,
        "amount": req.Amount, "status": req.Status, "requestedBy": req.RequestedBy, "decidedBy": req.DecidedBy,
        "decisionReason": req.DecisionReason, "result": json.loads(req.ResultJson) if req.ResultJson else None,
        "requiresReauth": requires_reauth(req),
        "approverRoles": list(ACTIONS[req.Tool].approver_roles),
        "createdAt": _iso(req.CreatedAt), "decidedAt": _iso(req.DecidedAt), "expiresAt": _iso(req.ExpiresAt),
    }


def requires_reauth(req: models.AgentActionRequest) -> bool:
    return (req.Amount or 0) >= business_limits(object_session(req), req.BusinessId).reauth


def _iso(d: datetime | None) -> str | None:
    return d.isoformat(timespec="seconds") + "Z" if d else None
