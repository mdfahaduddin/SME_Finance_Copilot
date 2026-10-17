"""Cryptographic helpers: password hashing and policy, opaque tokens, CSRF tokens, secret encryption."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

import bcrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

# A short list of passwords that are always rejected (the length rule already removes most weak ones).
COMMON_PASSWORDS = {
    "password", "password1", "password123", "123456789", "1234567890", "qwertyuiop", "qwerty123",
    "iloveyou", "welcome123", "admin12345", "letmein123", "monkey1234", "football1", "abc1234567",
    "passw0rd123", "p@ssw0rd123", "changeme123", "1q2w3e4r5t", "zaq12wsxcde",
}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def password_problems(password: str, email: str = "", name: str = "") -> list[str]:
    """Return the reasons a password is not acceptable (empty list = OK)."""
    s = get_settings()
    problems = []
    if len(password) < s.password_min_length:
        problems.append(f"at least {s.password_min_length} characters")
    if len(password) > 128:
        problems.append("at most 128 characters")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("not a commonly used password")
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in password.lower():
        problems.append("not containing your email address")
    if len(set(password)) < 4:
        problems.append("more than a few repeated characters")
    return problems


# ---------------------------------------------------------------- opaque tokens

def new_token() -> str:
    """Random 256-bit URL-safe token (session ids, reset and invite links)."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Tokens are stored only as SHA-256 hashes, so a database leak does not leak live sessions."""
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_for(session_token: str) -> str:
    """CSRF token bound to a session: HMAC(secret, session). Echoed by the browser in X-CSRF-Token."""
    mac = hmac.new(get_settings().secret_key.encode(), f"csrf:{session_token}".encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode().rstrip("=")


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ---------------------------------------------------------------- secret encryption (MFA secrets)

def _key() -> bytes:
    return hashlib.sha256(f"enc:{get_settings().secret_key}".encode()).digest()


def encrypt(plaintext: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plaintext.encode(), None)
    return base64.urlsafe_b64encode(nonce + ct).decode()


def decrypt(token: str) -> str:
    raw = base64.urlsafe_b64decode(token.encode())
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], None).decode()
