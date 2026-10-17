"""Onboarding: business profile, bank accounts, setup status, team members and invitations."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, models
from app.api.auth import EMAIL_PATTERN, INDUSTRIES, _check_password, _user_dict
from app.api.deps import CamelModel, mask_account
from app.auth import (
    CurrentUser, any_user, create_session, owner_only, revoke_user_sessions, set_session_cookies, staff,
)
from app.config import get_settings
from app.db import get_db
from app.mailer import send_email
from app.models import utcnow
from app.ratelimit import recovery_limiter
from app.security import hash_password, new_token, token_hash

router = APIRouter(prefix="/api", tags=["onboarding"])

INVITE_TTL = timedelta(days=7)


# ---------------------------------------------------------------- business profile

class ProfileBody(CamelModel):
    name: str = Field(min_length=2, max_length=200)
    industry: str = Field(max_length=100)
    region: str = Field("", max_length=100)
    founded_date: date
    employees: int = Field(ge=0, le=100_000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    credit_score: int | None = Field(None, ge=300, le=850)
    has_collateral: bool = False
    annual_revenue: float | None = Field(None, ge=0, le=10_000_000_000)


def _profile(b: models.SmeBusiness) -> dict:
    return {"id": b.Id, "name": b.Name, "industry": b.Industry, "region": b.Region,
            "foundedDate": b.FoundedDate.isoformat(), "employees": b.Employees, "currency": b.Currency,
            "creditScore": b.CreditScore, "hasCollateral": b.HasCollateral, "annualRevenue": b.AnnualRevenue,
            "onboardingStatus": b.OnboardingStatus, "industries": INDUSTRIES}


@router.get("/business/profile")
def get_profile(db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> dict:
    return _profile(db.get(models.SmeBusiness, user.business_id))


@router.put("/business/profile")
def update_profile(body: ProfileBody, db: Session = Depends(get_db), user: CurrentUser = Depends(owner_only)) -> dict:
    if body.founded_date > date.today():
        raise HTTPException(422, "Founded date cannot be in the future")
    b = db.get(models.SmeBusiness, user.business_id)
    b.Name, b.Industry, b.Region = body.name.strip(), body.industry, body.region.strip()
    b.FoundedDate, b.Employees, b.Currency = body.founded_date, body.employees, body.currency
    b.CreditScore, b.HasCollateral = body.credit_score, body.has_collateral
    if body.annual_revenue is not None:
        b.AnnualRevenue = body.annual_revenue
    audit.record(db, action="business.profile_updated", actor=user.label, actor_type="user",
                 business_id=user.business_id, params=body.model_dump(mode="json"), commit=False)
    db.commit()
    return _profile(b)


# ---------------------------------------------------------------- bank accounts

class AccountBody(CamelModel):
    name: str = Field(min_length=2, max_length=100)
    account_type: Literal["checking", "savings"] = "checking"
    last4: str = Field("", pattern=r"^(\d{4})?$")
    balance: float = Field(ge=-100_000_000, le=10_000_000_000)


def _account(a: models.SmeBankAccount) -> dict:
    return {"id": a.Id, "name": a.Name, "type": a.AccountType, "number": mask_account(a.AccountNumber),
            "balance": a.Balance, "currency": a.Currency}


@router.post("/business/accounts", status_code=201)
def add_account(body: AccountBody, db: Session = Depends(get_db), user: CurrentUser = Depends(staff)) -> dict:
    b = db.get(models.SmeBusiness, user.business_id)
    if db.scalar(select(func.count()).select_from(models.SmeBankAccount).where(
            models.SmeBankAccount.BusinessId == b.Id)) >= 20:
        raise HTTPException(422, "Up to 20 accounts per business")
    # Only the last four digits are kept: the full number is never needed for analysis.
    a = models.SmeBankAccount(BusinessId=b.Id, Name=body.name.strip(), AccountType=body.account_type,
                              AccountNumber=body.last4 or "", Balance=body.balance, Currency=b.Currency)
    db.add(a)
    if b.OnboardingStatus == "accounts":
        b.OnboardingStatus = "data"
    audit.record(db, action="business.account_added", actor=user.label, actor_type="user",
                 business_id=b.Id, result=f"{a.Name} ({a.AccountType})", commit=False)
    db.commit()
    return _account(a)


class BalanceBody(CamelModel):
    name: str | None = Field(None, min_length=2, max_length=100)
    balance: float = Field(ge=-100_000_000, le=10_000_000_000)


@router.put("/business/accounts/{account_id}")
def update_account(account_id: int, body: BalanceBody, db: Session = Depends(get_db),
                   user: CurrentUser = Depends(staff)) -> dict:
    a = db.get(models.SmeBankAccount, account_id)
    if a is None or a.BusinessId != user.business_id:
        raise HTTPException(404, "Account not found")
    if body.name:
        a.Name = body.name.strip()
    a.Balance = body.balance
    audit.record(db, action="business.account_updated", actor=user.label, actor_type="user",
                 business_id=user.business_id, result=f"{a.Name} balance updated", commit=False)
    db.commit()
    return _account(a)


# ---------------------------------------------------------------- onboarding status

def _counts(db: Session, business_id: int) -> dict:
    accts = select(models.SmeBankAccount.Id).where(models.SmeBankAccount.BusinessId == business_id)
    return {
        "accounts": db.scalar(select(func.count()).select_from(models.SmeBankAccount)
                              .where(models.SmeBankAccount.BusinessId == business_id)),
        "transactions": db.scalar(select(func.count()).select_from(models.SmeTransaction)
                                  .where(models.SmeTransaction.AccountId.in_(accts))),
        "invoices": db.scalar(select(func.count()).select_from(models.SmeInvoice)
                              .where(models.SmeInvoice.BusinessId == business_id)),
        "bills": db.scalar(select(func.count()).select_from(models.SmeBill)
                           .where(models.SmeBill.BusinessId == business_id)),
    }


@router.get("/onboarding/status")
def onboarding_status(db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> dict:
    b = db.get(models.SmeBusiness, user.business_id)
    c = _counts(db, b.Id)
    first = db.scalar(select(func.min(models.SmeTransaction.TxnDate)).where(models.SmeTransaction.AccountId.in_(
        select(models.SmeBankAccount.Id).where(models.SmeBankAccount.BusinessId == b.Id))))
    months = round((date.today() - first).days / 30.4, 1) if first else 0
    return {"status": b.OnboardingStatus, "counts": c, "monthsOfHistory": months,
            "canFinish": c["accounts"] > 0,
            "recommendation": None if months >= 6 else
            "Import at least 6 months of bank transactions for reliable forecasts (12+ months captures seasonality)."}


@router.post("/onboarding/complete")
def onboarding_complete(db: Session = Depends(get_db), user: CurrentUser = Depends(owner_only)) -> dict:
    b = db.get(models.SmeBusiness, user.business_id)
    if _counts(db, b.Id)["accounts"] == 0:
        raise HTTPException(422, "Add at least one bank account first")
    b.OnboardingStatus = "complete"
    audit.record(db, action="business.onboarding_complete", actor=user.label, actor_type="user",
                 business_id=b.Id, commit=False)
    db.commit()
    return {"status": "complete"}


# ---------------------------------------------------------------- team

class InviteBody(CamelModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=200)
    role: Literal["owner", "accountant", "viewer"]


@router.get("/team")
def team(db: Session = Depends(get_db), user: CurrentUser = Depends(any_user)) -> dict:
    members = db.scalars(select(models.SmeUser).where(models.SmeUser.BusinessId == user.business_id)
                         .order_by(models.SmeUser.Id)).all()
    invites = db.scalars(select(models.AuthToken).where(
        models.AuthToken.BusinessId == user.business_id, models.AuthToken.Purpose == "invite",
        models.AuthToken.UsedAt.is_(None), models.AuthToken.ExpiresAt > utcnow())).all()
    return {
        "members": [{"id": m.Id, "name": m.FullName, "email": m.Email, "role": m.Role, "active": m.IsActive,
                     "mfaEnabled": m.MfaEnabled, "you": m.Id == user.id,
                     "lastLoginAt": m.LastLoginAt.isoformat(timespec="seconds") + "Z" if m.LastLoginAt else None}
                    for m in members],
        "invites": [{"id": i.Id, "email": i.Email, "role": i.Role,
                     "expiresAt": i.ExpiresAt.isoformat(timespec="seconds") + "Z"} for i in invites]
                   if user.role != "viewer" else [],
    }


@router.post("/team/invites", status_code=201)
def invite(body: InviteBody, background: BackgroundTasks, db: Session = Depends(get_db),
           user: CurrentUser = Depends(owner_only)) -> dict:
    email = body.email.strip().lower()
    if db.scalar(select(models.SmeUser.Id).where(func.lower(models.SmeUser.Email) == email)):
        raise HTTPException(409, "That email already has an account")
    token = new_token()
    row = models.AuthToken(Purpose="invite", TokenHash=token_hash(token), BusinessId=user.business_id, Email=email,
                           Role=body.role, CreatedBy=user.id, ExpiresAt=utcnow() + INVITE_TTL)
    db.add(row)
    biz = db.get(models.SmeBusiness, user.business_id)
    audit.record(db, action="team.invited", actor=user.label, actor_type="user", business_id=user.business_id,
                 params={"email": email}, result=f"Invited as {body.role}", commit=False)
    db.commit()
    link = f"{get_settings().public_base_url}/accept-invite?token={token}"
    background.add_task(send_email, email, f"You're invited to {biz.Name} on SME Finance Copilot",
                        f"{user.name} invited you to join {biz.Name} as {body.role}.\n\n"
                        f"Accept within 7 days: {link}\n")
    return {"id": row.Id, "email": email, "role": body.role,
            "expiresAt": row.ExpiresAt.isoformat(timespec="seconds") + "Z"}


@router.delete("/team/invites/{invite_id}")
def revoke_invite(invite_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(owner_only)) -> dict:
    row = db.get(models.AuthToken, invite_id)
    if row is None or row.BusinessId != user.business_id or row.Purpose != "invite":
        raise HTTPException(404, "Invite not found")
    row.UsedAt = utcnow()  # consumed = no longer usable
    db.commit()
    return {"ok": True}


class MemberBody(CamelModel):
    role: Literal["owner", "accountant", "viewer"] | None = None
    active: bool | None = None


@router.patch("/team/members/{member_id}")
def update_member(member_id: int, body: MemberBody, db: Session = Depends(get_db),
                  user: CurrentUser = Depends(owner_only)) -> dict:
    m = db.get(models.SmeUser, member_id)
    if m is None or m.BusinessId != user.business_id:
        raise HTTPException(404, "Member not found")
    if m.Id == user.id:
        raise HTTPException(422, "You cannot change your own role or access")
    if m.Role == "owner" and (body.role not in (None, "owner") or body.active is False):
        owners = db.scalar(select(func.count()).select_from(models.SmeUser).where(
            models.SmeUser.BusinessId == user.business_id, models.SmeUser.Role == "owner",
            models.SmeUser.IsActive.is_(True)))
        if owners <= 1:
            raise HTTPException(422, "A business needs at least one active owner")
    if body.role:
        m.Role = body.role
    if body.active is not None:
        m.IsActive = body.active
        if not body.active:
            revoke_user_sessions(db, m.Id)
    audit.record(db, action="team.member_updated", actor=user.label, actor_type="user",
                 business_id=user.business_id, result=f"Member #{m.Id}: role={m.Role}, active={m.IsActive}",
                 commit=False)
    db.commit()
    return {"id": m.Id, "role": m.Role, "active": m.IsActive}


# ---------------------------------------------------------------- accepting an invite (public)

def _valid_invite(db: Session, token: str) -> models.AuthToken:
    row = db.scalar(select(models.AuthToken).where(models.AuthToken.TokenHash == token_hash(token),
                                                   models.AuthToken.Purpose == "invite"))
    if row is None or row.UsedAt is not None or row.ExpiresAt <= utcnow():
        raise HTTPException(400, "This invitation is invalid or has expired. Ask for a new one.")
    return row


@router.get("/auth/invite/{token}")
def invite_preview(token: str, request: Request, db: Session = Depends(get_db)) -> dict:
    recovery_limiter.check(f"invite|{request.client.host if request.client else 'unknown'}")
    row = _valid_invite(db, token)
    biz = db.get(models.SmeBusiness, row.BusinessId)
    return {"businessName": biz.Name, "email": row.Email, "role": row.Role}


class AcceptBody(CamelModel):
    token: str = Field(min_length=20, max_length=100)
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(max_length=128)


@router.post("/auth/invite/accept", status_code=201)
def accept_invite(body: AcceptBody, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    recovery_limiter.check(f"accept|{request.client.host if request.client else 'unknown'}")
    row = _valid_invite(db, body.token)
    if db.scalar(select(models.SmeUser.Id).where(func.lower(models.SmeUser.Email) == row.Email)):
        raise HTTPException(409, "That email already has an account")
    _check_password(body.password, row.Email, body.full_name)
    u = models.SmeUser(BusinessId=row.BusinessId, Email=row.Email, FullName=body.full_name.strip(), Role=row.Role,
                       PasswordHash=hash_password(body.password), PasswordChangedAt=utcnow(), LastLoginAt=utcnow())
    db.add(u)
    row.UsedAt = utcnow()
    db.flush()
    token, _ = create_session(db, u, request)
    audit.record(db, action="team.invite_accepted", actor=f"{u.Email} ({u.Role})", actor_type="user",
                 business_id=row.BusinessId, commit=False)
    db.commit()
    set_session_cookies(response, token)
    return {"user": _user_dict(u, db.get(models.SmeBusiness, row.BusinessId)), "mfaRequired": False}
