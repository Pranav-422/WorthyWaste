"""Phone + PIN login for collectors, dealers, Satin branch staff, households and the WorthyWaste team.

Sessions are stateless signed tokens kept in an httpOnly cookie per role (ww_collector, ww_dealer,
ww_satin, ww_household, ww_ops), so everyone in a demo can be signed in side by side in one browser.
The Next.js server verifies the same tokens (frontend/lib/session.ts), so both must share WW_SECRET.

Token: base64url(JSON {"r": role, "id": id, "exp": unix}) + "." + base64url(HMAC-SHA256(secret, payload))
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

ROLES = ("collector", "dealer", "satin", "household", "ops")
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


# ---------- Provider webhook signatures ----------
# Payment and IVR providers sign the raw request body with a shared secret
# (X-Provider-Signature: hex HMAC-SHA256). Without WW_PROVIDER_SECRET nothing can be verified, so
# every signed route refuses — a missing secret must not mean "open".

PROVIDER_SIGNATURE_HEADER = "x-provider-signature"


def provider_secret() -> bytes | None:
    s = os.environ.get("WW_PROVIDER_SECRET")
    return s.encode() if s else None


def sign_provider_body(body: bytes, secret: bytes | None = None) -> str:
    key = secret if secret is not None else provider_secret()
    if not key:
        raise RuntimeError("WW_PROVIDER_SECRET is not set")
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def verify_provider_signature(body: bytes, header: str | None) -> bool:
    key = provider_secret()
    if not key or not header:
        return False
    # Accept a bare hex digest or the common "sha256=<hex>" form.
    got = header.strip()
    if got.lower().startswith("sha256="):
        got = got[7:]
    return hmac.compare_digest(got.lower(), hmac.new(key, body, hashlib.sha256).hexdigest())


# ---------- Demo reset key ----------

def demo_reset_allowed() -> bool:
    """POST /api/demo/reset wipes everything, so it stays off unless deliberately switched on."""
    return os.environ.get("WW_ALLOW_RESET") == "1"


def demo_key_ok(header: str | None) -> bool:
    want = os.environ.get("WW_DEMO_KEY")
    if not want or not header:
        return False
    return hmac.compare_digest(header, want)


def demo_mode() -> bool:
    """Demo shortcuts (simulated scan, over-estimated load, fixed location) exist only when this is on."""
    return os.environ.get("WW_DEMO_MODE") == "1"
