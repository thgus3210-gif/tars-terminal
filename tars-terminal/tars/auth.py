"""Session + CSRF + password hashing, stdlib-only crypto.

Mirrors the observed contract:
  * cookie-based session (signed, HttpOnly, SameSite=Lax)
  * GET /api/personal/session returns {authenticated, username, csrf}
  * mutating requests require a matching CSRF token AND same-origin
  * passwords stored as pbkdf2_sha256 with per-user salt

No external auth deps. For production, put this behind HTTPS (the SECURE
cookie flag turns on automatically when SESSION_SECURE=1).
"""

from __future__ import annotations
import hashlib
import hmac
import os
import secrets

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

SESSION_COOKIE = "tars_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 days
_PBKDF2_ROUNDS = 240_000


def _secret() -> str:
    s = os.getenv("SESSION_SECRET")
    if not s:
        # Ephemeral secret => sessions drop on restart. Fine for dev; set one in prod.
        s = secrets.token_hex(32)
        os.environ["SESSION_SECRET"] = s
    return s


_serializer = URLSafeTimedSerializer(_secret(), salt="tars.session")


# ---- passwords ----
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, hash_hex = stored.split("$")
        assert algo == "pbkdf2_sha256"
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ---- session cookie ----
def issue_session(username: str) -> tuple[str, str]:
    """Return (cookie_value, csrf_token). CSRF is bound into the session."""
    csrf = secrets.token_urlsafe(24)
    value = _serializer.dumps({"u": username, "c": csrf})
    return value, csrf


def read_session(cookie_value: str | None):
    if not cookie_value:
        return None
    try:
        data = _serializer.loads(cookie_value, max_age=SESSION_MAX_AGE)
        return {"username": data["u"], "csrf": data["c"]}
    except (BadSignature, SignatureExpired, KeyError, TypeError):
        return None


def csrf_ok(session: dict | None, presented: str | None) -> bool:
    if not session or not presented:
        return False
    return hmac.compare_digest(session["csrf"], presented)
