"""Authentication endpoints: registration, login (+TOTP), logout, sessions, passwords, MFA setup."""
from __future__ import annotations

from datetime import date, timedelta

import pyotp
import segno
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.api.deps import CamelModel
from app.auth import (
    CurrentUser, any_user, clear_session_cookies, create_session, resolve_session, revoke_user_sessions,
    set_session_cookies,
)
from app.config import get_settings
from app.db import get_db
from app.mailer import send_email
from app.models import AuthToken, SmeBusiness, SmeUser, UserSession, utcnow
from app.ratelimit import login_limiter, mfa_limiter, recovery_limiter, register_limiter
from app.security import decrypt, encrypt, hash_password, new_token, password_problems, token_hash, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

RESET_TTL = timedelta(minutes=60)
EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$"
INDUSTRIES = ["Food & Beverage", "Retail", "Professional Services", "Construction", "Manufacturing",
              "Healthcare", "Technology", "Transport & Logistics", "Hospitality", "Other"]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _user_dict(u: SmeUser, business: SmeBusiness | None = None) -> dict:
    d = {"id": u.Id, "email": u.Email, "name": u.FullName, "role": u.Role, "mfaEnabled": u.MfaEnabled}
    if business is not None:
        d["business"] = {"id": business.Id, "name": business.Name, "onboardingStatus": business.OnboardingStatus,
                         "currency": business.Currency}
    return d


def _check_password(password: str, email: str, name: str = "") -> None:
    problems = password_problems(password, email, name)
    if problems:
        raise HTTPException(422, "Password must be " + ", ".join(problems))


# ---------------------------------------------------------------- registration

class RegisterRequest(CamelModel):
    business_name: str = Field(min_length=2, max_length=200)
    industry: str = Field(max_length=100)
    region: str = Field("", max_length=100)
    founded_date: date
    employees: int = Field(ge=0, le=100_000)
    currency: str = Field("USD", pattern=r"^[A-Z]{3}$")
    full_name: str = Field(min_length=2, max_length=200)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=200)
    password: str = Field(max_length=128)
    accept_terms: bool

    @field_validator("founded_date")
    @classmethod
    def _not_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("cannot be in the future")
        return v


@router.get("/industries")
def industries() -> list[str]:
    return INDUSTRIES


@router.post("/register", status_code=201)
def register(body: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    register_limiter.check(f"register|{_client_ip(request)}")
    if not body.accept_terms:
        raise HTTPException(422, "You must accept the terms of service and privacy policy")
    email = body.email.strip().lower()
    _check_password(body.password, email, body.full_name)
    if db.scalar(select(SmeUser.Id).where(func.lower(SmeUser.Email) == email)):
        raise HTTPException(409, "An account with this email already exists. Sign in or reset your password.")
    biz = SmeBusiness(
        Name=body.business_name.strip(), Industry=body.industry, Region=body.region.strip(),
        FoundedDate=body.founded_date, Employees=body.employees, Currency=body.currency, AnnualRevenue=0,
        CreditScore=None, HasCollateral=False, DataAsOf=None, OnboardingStatus="accounts",
    )
    db.add(biz)
    db.flush()
    user = SmeUser(BusinessId=biz.Id, Email=email, FullName=body.full_name.strip(), Role="owner",
                   PasswordHash=hash_password(body.password), PasswordChangedAt=utcnow(), LastLoginAt=utcnow())
    db.add(user)
    db.flush()
    token, _ = create_session(db, user, request)
    audit.record(db, action="auth.registered", actor=f"{email} (owner)", actor_type="user", business_id=biz.Id,
                 decision="allowed", result=f"Business created: {biz.Name}", commit=False)
    db.commit()
    set_session_cookies(response, token)
    return {"user": _user_dict(user, biz), "mfaRequired": False}


# ---------------------------------------------------------------- login / logout

class LoginRequest(CamelModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    email = body.email.strip().lower()
    login_limiter.check(f"{_client_ip(request)}|{email}")
    user = db.scalar(select(SmeUser).where(func.lower(SmeUser.Email) == email))
    if user is None or not user.IsActive or not verify_password(body.password, user.PasswordHash):
        audit.record(db, action="auth.login_failed", actor=email, actor_type="user",
                     business_id=user.BusinessId if user else None, decision="denied")
        # Same message for unknown user and wrong password (no account enumeration).
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    token, _ = create_session(db, user, request, mfa_verified=not user.MfaEnabled)
    if not user.MfaEnabled:
        user.LastLoginAt = utcnow()
    audit.record(db, action="auth.login" if not user.MfaEnabled else "auth.login_mfa_pending",
                 actor=f"{user.Email} ({user.Role})", actor_type="user", business_id=user.BusinessId,
                 decision="allowed", commit=False)
    db.commit()
    set_session_cookies(response, token)
    biz = db.get(SmeBusiness, user.BusinessId)
    return {"user": _user_dict(user, biz) if not user.MfaEnabled else None, "mfaRequired": user.MfaEnabled}


class CodeRequest(CamelModel):
    code: str = Field(pattern=r"^\d{6}$")


@router.post("/mfa/verify")
def mfa_verify(body: CodeRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    user, row, _ = resolve_session(request, db, allow_mfa_pending=True)
    mfa_limiter.check(f"mfa|{user.Id}")
    if row.MfaVerified:
        raise HTTPException(409, "Already verified")
    if not (user.MfaSecretEnc and pyotp.TOTP(decrypt(user.MfaSecretEnc)).verify(body.code, valid_window=1)):
        audit.record(db, action="auth.mfa_failed", actor=user.Email, actor_type="user",
                     business_id=user.BusinessId, decision="denied")
        raise HTTPException(401, "Invalid code")
    # Replace the pending session with a full one (a new token, so the pre-MFA token is useless).
    row.RevokedAt = utcnow()
    token, _ = create_session(db, user, request)
    user.LastLoginAt = utcnow()
    audit.record(db, action="auth.login", actor=f"{user.Email} ({user.Role})", actor_type="user",
                 business_id=user.BusinessId, decision="allowed", result="with two-factor code", commit=False)
    db.commit()
    set_session_cookies(response, token)
    return {"user": _user_dict(user, db.get(SmeBusiness, user.BusinessId)), "mfaRequired": False}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    try:
        user, row, _ = resolve_session(request, db, allow_mfa_pending=True)
        row.RevokedAt = utcnow()
        audit.record(db, action="auth.logout", actor=user.Email, actor_type="user", business_id=user.BusinessId,
                     commit=False)
        db.commit()
    except HTTPException:
        pass  # already signed out
    clear_session_cookies(response)
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    u = db.get(SmeUser, user.id)
    return _user_dict(u, db.get(SmeBusiness, user.business_id))


# ---------------------------------------------------------------- sessions

@router.get("/sessions")
def sessions(user: CurrentUser = Depends(any_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(UserSession).where(
        UserSession.UserId == user.id, UserSession.RevokedAt.is_(None), UserSession.ExpiresAt > utcnow(),
        UserSession.MfaVerified.is_(True)).order_by(UserSession.LastSeenAt.desc())).all()
    return [{"id": r.Id, "userAgent": r.UserAgent, "createdAt": r.CreatedAt.isoformat(timespec="seconds") + "Z",
             "lastSeenAt": r.LastSeenAt.isoformat(timespec="seconds") + "Z", "current": r.Id == user.session_id}
            for r in rows]


@router.post("/sessions/revoke-others")
def revoke_others(user: CurrentUser = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    n = revoke_user_sessions(db, user.id, except_session_id=user.session_id)
    audit.record(db, action="auth.sessions_revoked", actor=user.label, actor_type="user",
                 business_id=user.business_id, result=f"{n} other sessions signed out", commit=False)
    db.commit()
    return {"revoked": n}


# ---------------------------------------------------------------- passwords

class ChangePasswordRequest(CamelModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=128)


@router.post("/password/change")
def change_password(body: ChangePasswordRequest, user: CurrentUser = Depends(any_user),
                    db: Session = Depends(get_db)) -> dict:
    u = db.get(SmeUser, user.id)
    if not verify_password(body.current_password, u.PasswordHash):
        raise HTTPException(403, "Current password is incorrect")
    _check_password(body.new_password, u.Email, u.FullName)
    u.PasswordHash, u.PasswordChangedAt = hash_password(body.new_password), utcnow()
    revoke_user_sessions(db, u.Id, except_session_id=user.session_id)
    audit.record(db, action="auth.password_changed", actor=user.label, actor_type="user",
                 business_id=user.business_id, commit=False)
    db.commit()
    return {"ok": True}


class ForgotRequest(CamelModel):
    email: str = Field(max_length=200)


@router.post("/password/forgot")
def forgot_password(body: ForgotRequest, request: Request, background: BackgroundTasks,
                    db: Session = Depends(get_db)) -> dict:
    email = body.email.strip().lower()
    recovery_limiter.check(f"forgot|{_client_ip(request)}|{email}")
    user = db.scalar(select(SmeUser).where(func.lower(SmeUser.Email) == email, SmeUser.IsActive.is_(True)))
    if user is not None:
        token = new_token()
        db.add(AuthToken(Purpose="password_reset", TokenHash=token_hash(token), UserId=user.Id, Email=email,
                         ExpiresAt=utcnow() + RESET_TTL))
        audit.record(db, action="auth.password_reset_requested", actor=email, actor_type="user",
                     business_id=user.BusinessId, commit=False)
        db.commit()
        link = f"{get_settings().public_base_url}/reset-password?token={token}"
        background.add_task(send_email, email, "Reset your SME Finance Copilot password",
                            f"Hello {user.FullName},\n\nUse this link within 60 minutes to choose a new password:\n"
                            f"{link}\n\nIf you did not ask for this, you can ignore this email.")
    # Identical response whether or not the account exists.
    return {"ok": True, "message": "If an account exists for that email, a reset link is on its way."}


class ResetRequest(CamelModel):
    token: str = Field(min_length=20, max_length=100)
    new_password: str = Field(max_length=128)


@router.post("/password/reset")
def reset_password(body: ResetRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    recovery_limiter.check(f"reset|{_client_ip(request)}")
    t = db.scalar(select(AuthToken).where(AuthToken.TokenHash == token_hash(body.token),
                                          AuthToken.Purpose == "password_reset"))
    if t is None or t.UsedAt is not None or t.ExpiresAt <= utcnow():
        raise HTTPException(400, "This reset link is invalid or has expired. Request a new one.")
    u = db.get(SmeUser, t.UserId)
    _check_password(body.new_password, u.Email, u.FullName)
    u.PasswordHash, u.PasswordChangedAt = hash_password(body.new_password), utcnow()
    t.UsedAt = utcnow()
    revoke_user_sessions(db, u.Id)  # sign out everywhere
    audit.record(db, action="auth.password_reset", actor=u.Email, actor_type="user", business_id=u.BusinessId,
                 commit=False)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- MFA (TOTP)

@router.post("/mfa/setup")
def mfa_setup(user: CurrentUser = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    u = db.get(SmeUser, user.id)
    if u.MfaEnabled:
        raise HTTPException(409, "Two-factor authentication is already on")
    secret = pyotp.random_base32()
    u.MfaSecretEnc = encrypt(secret)
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=u.Email, issuer_name="SME Finance Copilot")
    return {"secret": secret, "otpauthUri": uri, "qrSvg": segno.make(uri, error="m").svg_data_uri(scale=5)}


@router.post("/mfa/enable")
def mfa_enable(body: CodeRequest, user: CurrentUser = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    u = db.get(SmeUser, user.id)
    mfa_limiter.check(f"mfa|{u.Id}")
    if not u.MfaSecretEnc or not pyotp.TOTP(decrypt(u.MfaSecretEnc)).verify(body.code, valid_window=1):
        raise HTTPException(400, "That code did not match. Check your authenticator app's time and try again.")
    u.MfaEnabled = True
    revoke_user_sessions(db, u.Id, except_session_id=user.session_id)
    audit.record(db, action="auth.mfa_enabled", actor=user.label, actor_type="user",
                 business_id=user.business_id, commit=False)
    db.commit()
    return {"ok": True}


class DisableMfaRequest(CamelModel):
    password: str = Field(max_length=200)
    code: str = Field(pattern=r"^\d{6}$")


@router.post("/mfa/disable")
def mfa_disable(body: DisableMfaRequest, user: CurrentUser = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    u = db.get(SmeUser, user.id)
    mfa_limiter.check(f"mfa|{u.Id}")
    if not u.MfaEnabled:
        raise HTTPException(409, "Two-factor authentication is not on")
    if not verify_password(body.password, u.PasswordHash) or \
            not pyotp.TOTP(decrypt(u.MfaSecretEnc)).verify(body.code, valid_window=1):
        raise HTTPException(403, "Password or code is incorrect")
    u.MfaEnabled, u.MfaSecretEnc = False, None
    audit.record(db, action="auth.mfa_disabled", actor=user.label, actor_type="user",
                 business_id=user.business_id, commit=False)
    db.commit()
    return {"ok": True}
