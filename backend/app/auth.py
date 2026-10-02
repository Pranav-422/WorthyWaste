"""Phone + PIN login for collectors and dealers.

Sessions are stateless signed tokens kept in an httpOnly cookie per role (ww_collector, ww_dealer), so a
collector and a dealer can be signed in side by side on the demo stage. The Next.js server verifies the
same tokens (frontend/lib/session.ts), so both must share WW_SECRET.

Token: base64url(JSON {"r": role, "id": id, "exp": unix}) + "." + base64url(HMAC-SHA256(secret, payload))
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

ROLES = ("collector", "dealer")
SESSION_DAYS = 7
PBKDF2_ROUNDS = 120_000
DEV_SECRET = "worthywaste-dev-secret-change-me"

_secret = os.environ.get("WW_SECRET")
if not _secret:
    if os.environ.get("VERCEL_ENV") == "production":
        raise RuntimeError("WW_SECRET must be set in production")
    _secret = DEV_SECRET
SECRET = _secret.encode()


def cookie_name(role: str) -> str:
    return f"ww_{role}"


# ---------- PINs ----------

def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, rounds, salt, digest = stored.split("$")
    except ValueError:
        return False
    got = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), int(rounds))
    return hmac.compare_digest(got.hex(), digest)


# ---------- Tokens ----------

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(role: str, user_id: int, now: float | None = None) -> str:
    exp = int((now or time.time()) + SESSION_DAYS * 86400)
    payload = _b64(json.dumps({"r": role, "id": user_id, "exp": exp}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(SECRET, payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str | None, role: str) -> int | None:
    """User id if the token is valid, unexpired and for this role; otherwise None."""
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    want = _b64(hmac.new(SECRET, payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, want):
        return None
    try:
        data = json.loads(_unb64(payload))
    except ValueError:
        return None
    if data.get("r") != role or data.get("exp", 0) < time.time():
        return None
    return int(data["id"])


# ---------- Brute-force guard ----------
# Per instance only; enough to slow PIN guessing in a demo. The pilot moves this to the database
# (or OTP via the SMS provider) so it holds across serverless instances.

_attempts: dict[str, list[float]] = {}
MAX_ATTEMPTS = 5
WINDOW_S = 600


def too_many_attempts(key: str) -> bool:
    now = time.time()
    recent = [t for t in _attempts.get(key, []) if now - t < WINDOW_S]
    _attempts[key] = recent
    return len(recent) >= MAX_ATTEMPTS


def record_failure(key: str) -> None:
    _attempts.setdefault(key, []).append(time.time())


def clear_failures(key: str) -> None:
    _attempts.pop(key, None)
