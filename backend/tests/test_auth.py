"""Production authentication: cookie sessions, CSRF, expiry, revocation, password reset, MFA,
registration and team invitations."""
import re
from datetime import timedelta

import pyotp
import pytest
from sqlalchemy import select, update

from app import models
from app.models import utcnow

OWNER = {"email": "owner@lotusbakery.example", "password": "Owner#2026"}
STRONG = "correct horse battery staple"


@pytest.fixture()
def outbox(monkeypatch):
    """Capture emails instead of sending them."""
    sent: list[dict] = []

    def fake_send(to, subject, body):
        sent.append({"to": to, "subject": subject, "body": body})

    import app.api.auth as auth_api
    import app.api.onboarding as onboarding_api
    monkeypatch.setattr(auth_api, "send_email", fake_send)
    monkeypatch.setattr(onboarding_api, "send_email", fake_send)
    return sent


def _link_token(mail: dict) -> str:
    return re.search(r"token=([\w-]+)", mail["body"]).group(1)


def login_cookie(client, creds=OWNER):
    r = client.post("/api/auth/login", json=creds)
    assert r.status_code == 200, r.text
    return r


def csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("sme_csrf")}


# ---- cookies and CSRF ---------------------------------------------------------------

def test_session_cookie_flags(client):
    r = login_cookie(client)
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("sme_session="))
    token_cookie = next(c for c in cookies if c.startswith("sme_csrf="))
    assert "HttpOnly" in session and "samesite=lax" in session.lower()
    assert "HttpOnly" not in token_cookie  # the frontend must read it to echo it
    assert "sme_session" not in r.text  # token never in the body


def test_cookie_requests_need_csrf_for_changes(client):
    login_cookie(client)
    assert client.get("/api/auth/me").status_code == 200  # safe method: no CSRF needed
    body = {"changes": []}
    assert client.post("/api/scenarios/run", json=body).status_code == 403
    assert client.post("/api/scenarios/run", json=body, headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert client.post("/api/scenarios/run", json=body, headers=csrf(client)).status_code == 200


def test_bearer_requests_skip_csrf(client):
    h = client.as_role("viewer")
    assert client.post("/api/scenarios/run", json={"changes": []}, headers=h).status_code == 200


# ---- expiry and revocation ---------------------------------------------------------------

def test_absolute_and_idle_expiry(client):
    h = client.as_role("owner")
    with client.session() as s:
        s.execute(update(models.UserSession).values(LastSeenAt=utcnow() - timedelta(hours=3)))
        s.commit()
    r = client.get("/api/auth/me", headers=h)
    assert r.status_code == 401 and "inactivity" in r.json()["detail"]

    client._tokens.clear()
    h = client.as_role("owner")
    with client.session() as s:
        s.execute(update(models.UserSession).where(models.UserSession.RevokedAt.is_(None))
                  .values(ExpiresAt=utcnow() - timedelta(seconds=1)))
        s.commit()
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_logout_revokes_server_side(client):
    login_cookie(client)
    token = client.cookies.get("sme_session")
    assert client.post("/api/auth/logout", headers=csrf(client)).status_code == 200
    # The old token is dead even if someone kept a copy.
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_revoke_other_sessions(client):
    phone = client.as_role("owner")
    client._tokens.clear()
    laptop = client.as_role("owner")
    listed = client.get("/api/auth/sessions", headers=laptop).json()
    assert len(listed) == 2 and sum(s["current"] for s in listed) == 1
    assert client.post("/api/auth/sessions/revoke-others", headers=laptop).json()["revoked"] == 1
    assert client.get("/api/auth/me", headers=phone).status_code == 401
    assert client.get("/api/auth/me", headers=laptop).status_code == 200


def test_deactivated_user_loses_access(client):
    v = client.as_role("viewer")
    with client.session() as s:
        s.execute(update(models.SmeUser).where(models.SmeUser.Role == "viewer").values(IsActive=False))
        s.commit()
    assert client.get("/api/auth/me", headers=v).status_code == 401


# ---- passwords ----------------------------------------------------------------------------

def test_change_password_policy_and_effect(client):
    other = client.as_role("owner")
    client._tokens.clear()
    h = client.as_role("owner")
    weak = client.post("/api/auth/password/change", json={"currentPassword": "Owner#2026", "newPassword": "short"},
                       headers=h)
    assert weak.status_code == 422 and "at least" in weak.json()["detail"]
    wrong = client.post("/api/auth/password/change", json={"currentPassword": "nope", "newPassword": STRONG}, headers=h)
    assert wrong.status_code == 403
    ok = client.post("/api/auth/password/change", json={"currentPassword": "Owner#2026", "newPassword": STRONG},
                     headers=h)
    assert ok.status_code == 200
    assert client.get("/api/auth/me", headers=other).status_code == 401  # other sessions signed out
    assert client.get("/api/auth/me", headers=h).status_code == 200      # this one kept
    assert client.post("/api/auth/login", json={**OWNER, "password": STRONG}).status_code == 200


def test_password_reset_flow(client, outbox):
    same_unknown = client.post("/api/auth/password/forgot", json={"email": "nobody@example.com"})
    r = client.post("/api/auth/password/forgot", json={"email": OWNER["email"]})
    assert r.json() == same_unknown.json()  # no account enumeration
    assert len(outbox) == 1 and outbox[0]["to"] == OWNER["email"]
    token = _link_token(outbox[0])
    old_session = client.as_role("owner")
    assert client.post("/api/auth/password/reset", json={"token": token, "newPassword": STRONG}).status_code == 200
    assert client.get("/api/auth/me", headers=old_session).status_code == 401  # signed out everywhere
    again = client.post("/api/auth/password/reset", json={"token": token, "newPassword": STRONG + "!"})
    assert again.status_code == 400  # single use
    assert client.post("/api/auth/login", json={**OWNER, "password": STRONG}).status_code == 200


def test_reset_token_expires(client, outbox):
    client.post("/api/auth/password/forgot", json={"email": OWNER["email"]})
    with client.session() as s:
        s.execute(update(models.AuthToken).values(ExpiresAt=utcnow() - timedelta(minutes=1)))
        s.commit()
    r = client.post("/api/auth/password/reset", json={"token": _link_token(outbox[0]), "newPassword": STRONG})
    assert r.status_code == 400


# ---- MFA ---------------------------------------------------------------------------------

def test_mfa_enrolment_and_login(client):
    h = client.as_role("owner")
    setup = client.post("/api/auth/mfa/setup", headers=h).json()
    assert setup["qrSvg"].startswith("data:image/svg+xml") and setup["otpauthUri"].startswith("otpauth://")
    totp = pyotp.TOTP(setup["secret"])
    assert client.post("/api/auth/mfa/enable", json={"code": "000000"}, headers=h).status_code == 400
    assert client.post("/api/auth/mfa/enable", json={"code": totp.now()}, headers=h).status_code == 200
    with client.session() as s:
        stored = s.scalar(select(models.SmeUser.MfaSecretEnc).where(models.SmeUser.Role == "owner"))
    assert setup["secret"] not in stored  # encrypted at rest

    client.cookies.clear()
    r = client.post("/api/auth/login", json=OWNER)
    assert r.json() == {"user": None, "mfaRequired": True}
    pending = client.cookies.get("sme_session")
    # A password-only session cannot use the API...
    assert client.get("/api/dashboard/summary", headers={"Authorization": f"Bearer {pending}"}).status_code == 401
    assert client.post("/api/auth/mfa/verify", json={"code": "123456"},
                       headers={"Authorization": f"Bearer {pending}"}).status_code == 401
    ok = client.post("/api/auth/mfa/verify", json={"code": totp.now()}, headers={"Authorization": f"Bearer {pending}"})
    assert ok.status_code == 200 and ok.json()["user"]["mfaEnabled"] is True
    full = client.cookies.get("sme_session")
    assert full != pending  # a fresh token after MFA
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {pending}"}).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {full}"}).status_code == 200


# ---- registration ------------------------------------------------------------------------

REG = {"businessName": "Blue Fern Studio", "industry": "Professional Services", "region": "Dhaka",
       "foundedDate": "2022-03-01", "employees": 4, "currency": "BDT", "fullName": "Nadia Rahman",
       "email": "nadia@bluefern.example", "password": STRONG, "acceptTerms": True}


def test_register_creates_isolated_business(client):
    r = client.post("/api/auth/register", json=REG)
    assert r.status_code == 201, r.text
    user = r.json()["user"]
    assert user["role"] == "owner" and user["business"]["onboardingStatus"] == "accounts"
    assert client.get("/api/auth/me").json()["business"]["name"] == "Blue Fern Studio"
    # The new owner sees only their own (empty) business, never the demo bakery.
    assert client.get("/api/ledger/invoices?status=all").json() == []
    assert client.get("/api/ledger/accounts").json() == []
    client.cookies.clear()
    assert client.post("/api/auth/register", json=REG).status_code == 409  # email taken


@pytest.mark.parametrize("patch,status", [
    ({"acceptTerms": False}, 422), ({"password": "short"}, 422), ({"password": "nadiaxyz123456"}, 422),
    ({"email": "not-an-email"}, 422), ({"foundedDate": "2999-01-01"}, 422), ({"currency": "usd"}, 422),
])
def test_register_validation(client, patch, status):
    assert client.post("/api/auth/register", json={**REG, **patch}).status_code == status


# ---- invitations and team ------------------------------------------------------------------

def test_invite_accept_and_team_management(client, outbox):
    h = client.as_role("owner")
    acct = client.as_role("accountant")
    assert client.post("/api/team/invites", json={"email": "mia@lotusbakery.example", "role": "viewer"},
                       headers=acct).status_code == 403  # owners only
    r = client.post("/api/team/invites", json={"email": "Mia@LotusBakery.example", "role": "accountant"}, headers=h)
    assert r.status_code == 201
    token = _link_token(outbox[-1])
    preview = client.get(f"/api/auth/invite/{token}").json()
    assert preview == {"businessName": "Lotus Bakery & Cafe Ltd.", "email": "mia@lotusbakery.example",
                       "role": "accountant"}
    accepted = client.post("/api/auth/invite/accept", json={"token": token, "fullName": "Mia Chen", "password": STRONG})
    assert accepted.status_code == 201 and accepted.json()["user"]["role"] == "accountant"
    assert client.post("/api/auth/invite/accept",
                       json={"token": token, "fullName": "Xavier", "password": STRONG}).status_code == 400  # used
    client.cookies.clear()

    members = client.get("/api/team", headers=h).json()["members"]
    mia = next(m for m in members if m["email"] == "mia@lotusbakery.example")
    me = next(m for m in members if m["you"])
    assert client.patch(f"/api/team/members/{me['id']}", json={"role": "viewer"}, headers=h).status_code == 422
    assert client.patch(f"/api/team/members/{mia['id']}", json={"active": False}, headers=h).status_code == 200
    assert client.post("/api/auth/login", json={"email": "mia@lotusbakery.example", "password": STRONG}).status_code == 401


def test_invite_for_existing_email_refused(client):
    h = client.as_role("owner")
    r = client.post("/api/team/invites", json={"email": "viewer@lotusbakery.example", "role": "viewer"}, headers=h)
    assert r.status_code == 409
