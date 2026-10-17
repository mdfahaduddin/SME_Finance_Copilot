"""Authentication (server-side sessions) and role-based access control.

Sessions
  * Login creates a random 256-bit token. The browser receives it in an HttpOnly, SameSite=Lax cookie
    (Secure in production) and JavaScript can never read it. The database stores only its SHA-256 hash.
  * A session ends after SESSION_IDLE_MINUTES of inactivity, after SESSION_ABSOLUTE_HOURS in any case,
    on logout, on password change/reset, or when revoked from "active sessions".
  * API clients may send the same token as `Authorization: Bearer <token>` instead of the cookie.

CSRF
  * For cookie-authenticated requests that change state (POST/PUT/PATCH/DELETE), the client must send
    `X-CSRF-Token` equal to the `sme_csrf` cookie, which is HMAC(SECRET_KEY, session token). A malicious
    site can make the browser send the session cookie but cannot read the CSRF cookie to copy it.

Roles
  owner       full access; the only role that can approve money-moving or contractual actions
  accountant  read everything, acknowledge alerts, request actions, approve payment reminders, import data
  viewer      read-only

Authorization is enforced here, server-side, on every route. The LLM agent never decides what a
user may do; it acts with the calling user's identity and role.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import SmeUser, UserSession, utcnow
from app.security import constant_time_equal, csrf_for, new_token, token_hash

ROLES = ("owner", "accountant", "viewer")
SESSION_COOKIE = "sme_session"
CSRF_COOKIE = "sme_csrf"
CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MFA_PENDING_MINUTES = 5


@dataclass(frozen=True)
class CurrentUser:
    id: int
    business_id: int
    email: str
    name: str
    role: str
    session_id: int = 0

    @property
    def label(self) -> str:
        return f"{self.email} ({self.role})"


# ---------------------------------------------------------------- session lifecycle

def create_session(db: Session, user: SmeUser, request: Request | None, *, mfa_verified: bool = True
                   ) -> tuple[str, UserSession]:
    s = get_settings()
    token = new_token()
    lifetime = timedelta(hours=s.session_absolute_hours) if mfa_verified else timedelta(minutes=MFA_PENDING_MINUTES)
    row = UserSession(
        UserId=user.Id, TokenHash=token_hash(token), MfaVerified=mfa_verified, ExpiresAt=utcnow() + lifetime,
        UserAgent=(request.headers.get("user-agent", "") if request else "")[:200],
    )
    db.add(row)
    db.flush()
    return token, row


def set_session_cookies(response: Response, token: str) -> None:
    s = get_settings()
    max_age = s.session_absolute_hours * 3600
    common = dict(max_age=max_age, path="/", secure=bool(s.cookie_secure), samesite="lax")
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    # Readable by the frontend so it can echo it in X-CSRF-Token.
    response.set_cookie(CSRF_COOKIE, csrf_for(token), httponly=False, **common)


def clear_session_cookies(response: Response) -> None:
    s = get_settings()
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=bool(s.cookie_secure), samesite="lax")


def revoke_user_sessions(db: Session, user_id: int, *, except_session_id: int | None = None) -> int:
    q = update(UserSession).where(UserSession.UserId == user_id, UserSession.RevokedAt.is_(None))
    if except_session_id:
        q = q.where(UserSession.Id != except_session_id)
    return db.execute(q.values(RevokedAt=utcnow())).rowcount or 0


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail)


def _token_from(request: Request) -> tuple[str | None, bool]:
    """Return (token, via_cookie)."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None, False
    return request.cookies.get(SESSION_COOKIE), True


def resolve_session(request: Request, db: Session, *, allow_mfa_pending: bool = False
                    ) -> tuple[SmeUser, UserSession, str]:
    token, via_cookie = _token_from(request)
    if not token:
        raise _unauthorized()
    row = db.scalar(select(UserSession).where(UserSession.TokenHash == token_hash(token)))
    now = utcnow()
    s = get_settings()
    if row is None or row.RevokedAt is not None or row.ExpiresAt <= now:
        raise _unauthorized("Session expired, please sign in again")
    if row.LastSeenAt + timedelta(minutes=s.session_idle_minutes) <= now:
        row.RevokedAt = now
        db.commit()
        raise _unauthorized("Signed out after inactivity, please sign in again")
    if not row.MfaVerified and not allow_mfa_pending:
        raise _unauthorized("Two-factor verification required")
    if via_cookie and request.method in UNSAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not constant_time_equal(sent, csrf_for(token)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF check failed - reload the page and try again")
    user = db.get(SmeUser, row.UserId)
    # Re-read the user so deactivation or role changes take effect immediately.
    if user is None or not user.IsActive:
        raise _unauthorized("User no longer active")
    if (now - row.LastSeenAt).total_seconds() > 60:  # sliding expiry, written at most once a minute
        row.LastSeenAt = now
        db.commit()
    return user, row, token


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    user, row, _ = resolve_session(request, db)
    return CurrentUser(id=user.Id, business_id=user.BusinessId, email=user.Email, name=user.FullName,
                       role=user.Role, session_id=row.Id)


def require_roles(*roles: str):
    unknown = set(roles) - set(ROLES)
    if unknown:
        raise ValueError(f"Unknown roles: {unknown}")

    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role: {', '.join(roles)}")
        return user

    return dependency


any_user = get_current_user
staff = require_roles("owner", "accountant")
owner_only = require_roles("owner")
