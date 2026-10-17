"""Read-only access to the sandbox ledger (tier T0)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.api.deps import mask_account
from app.auth import CurrentUser, any_user
from app.db import get_db

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


@router.get("/accounts")
def accounts(db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> list[dict]:
    rows = db.scalars(select(models.SmeBankAccount).where(models.SmeBankAccount.BusinessId == user.business_id))
    return [{"id": a.Id, "name": a.Name, "type": a.AccountType, "number": mask_account(a.AccountNumber),
             "balance": a.Balance, "currency": a.Currency} for a in rows]


@router.get("/transactions")
def transactions(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    category: str | None = Query(None, max_length=50),
    direction: Literal["in", "out"] | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(any_user),
) -> dict:
    acct_ids = select(models.SmeBankAccount.Id).where(models.SmeBankAccount.BusinessId == user.business_id)
    q = select(models.SmeTransaction).where(models.SmeTransaction.AccountId.in_(acct_ids),
                                            models.SmeTransaction.Category != "Opening Balance")
    if category:
        q = q.where(models.SmeTransaction.Category == category)
    if direction:
        q = q.where(models.SmeTransaction.Direction == direction)
    rows = db.scalars(q.order_by(models.SmeTransaction.TxnDate.desc(), models.SmeTransaction.Id.desc())
                      .limit(limit).offset(offset)).all()
    return {"items": [{"id": t.Id, "date": t.TxnDate.isoformat(), "amount": t.Amount, "direction": t.Direction,
                       "category": t.Category, "counterparty": t.Counterparty, "description": t.Description}
                      for t in rows], "limit": limit, "offset": offset}


@router.get("/invoices")
def invoices(
    status: Literal["open", "paid", "all"] = "open",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(any_user),
) -> list[dict]:
    q = select(models.SmeInvoice).where(models.SmeInvoice.BusinessId == user.business_id)
    if status != "all":
        q = q.where(models.SmeInvoice.Status == status)
    as_of = db.get(models.SmeBusiness, user.business_id).today
    return [{"id": i.Id, "invoiceNo": i.InvoiceNo, "customer": i.Customer, "issueDate": i.IssueDate.isoformat(),
             "dueDate": i.DueDate.isoformat(), "amount": i.Amount, "status": i.Status,
             "paidDate": i.PaidDate.isoformat() if i.PaidDate else None,
             "daysPastDue": (as_of - i.DueDate).days if i.Status == "open" else None,
             "memo": i.Memo}  # memo is untrusted free text; the UI renders it as plain text
            for i in db.scalars(q.order_by(models.SmeInvoice.DueDate.desc()))]


@router.get("/bills")
def bills(
    status: Literal["open", "scheduled", "paid", "unpaid", "all"] = "unpaid",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(any_user),
) -> list[dict]:
    q = select(models.SmeBill).where(models.SmeBill.BusinessId == user.business_id)
    if status == "unpaid":
        q = q.where(models.SmeBill.Status != "paid")
    elif status != "all":
        q = q.where(models.SmeBill.Status == status)
    return [{"id": b.Id, "vendor": b.Vendor, "category": b.Category, "dueDate": b.DueDate.isoformat(),
             "amount": b.Amount, "status": b.Status,
             "scheduledDate": b.ScheduledDate.isoformat() if b.ScheduledDate else None, "recurring": b.IsRecurring}
            for b in db.scalars(q.order_by(models.SmeBill.DueDate))]


@router.get("/loan-applications")
def loan_applications(db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> list[dict]:
    rows = db.scalars(select(models.LoanApplication).where(models.LoanApplication.BusinessId == user.business_id)
                      .order_by(models.LoanApplication.Id.desc()))
    return [{"id": r.Id, "productId": r.ProductId, "amount": r.Amount, "termMonths": r.TermMonths,
             "purpose": r.Purpose, "status": r.Status, "referenceNo": r.ReferenceNo,
             "submittedAt": r.SubmittedAt.isoformat(timespec="seconds") + "Z" if r.SubmittedAt else None}
            for r in rows]


@router.get("/outbox")
def outbox(db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> list[dict]:
    rows = db.scalars(select(models.SmeOutboxMessage).where(models.SmeOutboxMessage.BusinessId == user.business_id)
                      .order_by(models.SmeOutboxMessage.Id.desc()))
    return [{"id": m.Id, "actionRequestId": m.ActionRequestId, "channel": m.Channel, "recipient": m.Recipient,
             "subject": m.Subject, "body": m.Body, "status": m.Status,
             "createdAt": m.CreatedAt.isoformat(timespec="seconds") + "Z"} for m in rows]
