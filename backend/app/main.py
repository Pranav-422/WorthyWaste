"""WorthyWaste API. Every step of a sale is its own call, so every fraud check runs at the step it guards.

All routes live under /api: on Vercel the Next.js app and this API share one domain, and Vercel passes
the original path (/api/...) through to this service. Locally, Next.js proxies /api/* here unchanged.
"""
import hashlib
import json
import os
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta

from fastapi import APIRouter, Depends, FastAPI, File, Form, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from . import adapters, auth, clock, fraud, score, services
from .db import DATABASE_URL, connect, init_db, one, rows, transaction
from .services import ApiError

_db = connect()
# One connection per instance, guarded by a lock. A plain Lock, not an RLock: FastAPI may run a sync
# dependency's setup and teardown on different worker threads, and only a Lock can be released by a
# thread other than the one that acquired it. Nothing here acquires it re-entrantly.
#
# This lock only protects the one connection inside this process. On Vercel several instances run at
# once, so it cannot stop two of them accepting or paying the same request: every state change is a
# guarded UPDATE in services.py (`WHERE ... AND status = <expected>`) that 409s when it matches no row.
_lock = threading.Lock()
_ADVISORY_KEY = 7_719_001  # Postgres advisory lock serialising schema setup and seeding across instances


@contextmanager
def _tx():
    """One locked transaction; on ApiError, still record what the refusal says must be kept."""
    with _lock:
        _db.ensure_alive()
        try:
            with transaction(_db):
                yield _db
        except ApiError as e:
            if e.persist:
                with transaction(_db):
                    for write in e.persist:
                        write(_db)
            raise


def db():
    with _tx() as conn:
        yield conn


@contextmanager
def _setup_lock():
    """Serialise schema creation and seeding when several cold starts race on one Postgres.

    The lock is taken on its own direct connection. DATABASE_URL is usually a pooled URL (PgBouncer in
    transaction mode, as on Neon), where pg_advisory_lock and pg_advisory_unlock can run on different
    server sessions: the unlock misses, the lock stays held, and every later cold start waits on it
    until the function times out. A dedicated connection releases the lock for certain when it closes,
    and the wait is bounded so a stuck holder can never hang a request."""
    if not _db.is_pg:
        yield
        return
    import psycopg

    url = (os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("POSTGRES_URL_NON_POOLING")
           or DATABASE_URL)
    with psycopg.connect(url, autocommit=True, connect_timeout=15) as lock_conn:
        lock_conn.execute("SET lock_timeout = '30s'")
        try:
            lock_conn.execute("SELECT pg_advisory_lock(%s)", (_ADVISORY_KEY,))
        except psycopg.errors.LockNotAvailable:
            raise SetupBusy()
        try:
            yield
        finally:
            lock_conn.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_KEY,))


class SetupBusy(Exception):
    """Another instance is creating the schema or seeding right now."""


def startup():
    from .seed import ensure_satin_users, seed

    try:
        with _lock, _setup_lock():
            _db.ensure_alive()
            init_db(_db)
            if _db.execute("SELECT COUNT(*) FROM collectors").fetchone()[0] == 0:
                seed(_db)
            else:
                # Databases created before the Satin login existed have no branch staff to log in as.
                ensure_satin_users(_db)
    except SetupBusy:
        # Another cold start holds the setup lock and will finish the schema and seed itself.
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup()
    yield


app = FastAPI(title="WorthyWaste API", version="0.2.0", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")
api = APIRouter(prefix="/api")


@app.exception_handler(ApiError)
async def api_error(_: Request, e: ApiError):
    return JSONResponse(status_code=e.status,
                        content={"error": e.message, "rule": e.rule, "evidence": e.evidence})


# ---------- Sessions ----------

def _session(request: Request, role: str) -> int | None:
    token = request.cookies.get(auth.cookie_name(role))
    header = request.headers.get("authorization", "")
    if not token and header.lower().startswith("bearer "):
        token = header[7:]
    return auth.read_token(token, role)


def require_collector(request: Request) -> int:
    uid = _session(request, "collector")
    if uid is None:
        raise ApiError(401, "Please log in as a collector")
    return uid


def require_dealer(request: Request) -> int:
    uid = _session(request, "dealer")
    if uid is None:
        raise ApiError(401, "Please log in as a dealer")
    return uid


def require_satin(request: Request) -> int:
    """Satin's dashboard reads collectors' personal data and moves money, so every one of its
    endpoints needs a branch-staff session — not just the page in front of it."""
    uid = _session(request, "satin")
    if uid is None:
        raise ApiError(401, "Please log in as Satin branch staff")
    return uid


def require_demo_mode() -> None:
    """Demo-only routes do not exist unless the server is in demo mode, so production cannot be
    nudged into them by guessing a URL."""
    if not auth.demo_mode():
        raise ApiError(404, "Not found")


async def provider_payload(request: Request, model: type[BaseModel]):
    """Body of a call from a payment or IVR provider, verified against WW_PROVIDER_SECRET.

    The signature covers the raw bytes, so the body is read once and parsed here rather than by
    FastAPI — re-serialising a parsed model would not reproduce what the provider signed."""
    raw = await request.body()
    if not auth.verify_provider_signature(raw, request.headers.get(auth.PROVIDER_SIGNATURE_HEADER)):
        raise ApiError(401, "Missing or invalid X-Provider-Signature")
    try:
        return model.model_validate_json(raw)
    except ValidationError as e:
        raise ApiError(422, f"Provider payload is not valid: {e.error_count()} problem(s)")


def _same(session_id: int, claimed: int | None, what: str) -> int:
    if claimed is not None and claimed != session_id:
        raise ApiError(403, f"You can only act as your own {what} account")
    return session_id


# Where each role's accounts live, and which column holds the display name.
ROLE_TABLE = {"collector": ("collectors", "name"), "dealer": ("dealers", "shop_name"),
              "satin": ("satin_users", "name")}


class LoginBody(BaseModel):
    role: str = Field(pattern="^(collector|dealer|satin)$")
    phone: str = Field(min_length=10, max_length=15)
    pin: str = Field(pattern=r"^\d{4}$")


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


@api.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response, conn=Depends(db)):
    phone = "".join(ch for ch in body.phone if ch.isdigit())[-10:]
    key = f"{body.role}:{phone}"
    if auth.too_many_attempts(key):
        raise ApiError(429, "Too many wrong PINs. Try again in 10 minutes.")
    table, name_col = ROLE_TABLE[body.role]
    user = one(conn.execute(
        f"SELECT id, {name_col} AS name, pin_hash FROM {table} WHERE phone = ?", (phone,)))
    if not user or not auth.verify_pin(body.pin, user["pin_hash"]):
        auth.record_failure(key)
        raise ApiError(401, "Wrong phone number or PIN")
    auth.clear_failures(key)
    response.set_cookie(auth.cookie_name(body.role), auth.make_token(body.role, user["id"]),
                        max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=_is_https(request), path="/")
    return {"role": body.role, "user": {"id": user["id"], "name": user["name"]}}


class LogoutBody(BaseModel):
    role: str = Field(pattern="^(collector|dealer|satin)$")


@api.post("/auth/logout")
def logout(body: LogoutBody, response: Response):
    response.delete_cookie(auth.cookie_name(body.role), path="/")
    return {"ok": True}


@api.get("/auth/me")
def me(role: str, request: Request, conn=Depends(db)):
    if role not in auth.ROLES:
        raise ApiError(400, "Unknown role")
    uid = _session(request, role)
    if uid is None:
        raise ApiError(401, "Not logged in")
    table, name_col = ROLE_TABLE[role]
    user = one(conn.execute(f"SELECT id, {name_col} AS name FROM {table} WHERE id = ?", (uid,)))
    if not user:
        raise ApiError(401, "Account no longer exists")
    return {"role": role, "user": user}


# ---------- Reference ----------

@api.get("/health")
def health():
    return {"ok": True, "time": clock.ts(), "scripted": os.environ.get("WW_SCRIPTED") == "1",
            "demo_mode": auth.demo_mode(), "photo_check": type(adapters.photo_verifier).__name__,
            "photo_check_model": getattr(adapters.photo_verifier, "model", None),
            # A photo check that has quietly stopped working looks exactly like one that finds
            # nothing wrong, so the last latency and the last failure are on the health page.
            **adapters.photo_check_status(),
            "db": "postgres" if _db.is_pg else "sqlite"}


@api.get("/materials")
def materials(conn=Depends(db)):
    return rows(conn.execute("SELECT * FROM materials ORDER BY sort_order"))


@api.get("/photos/{name}")
def photo(name: str, conn=Depends(db)):
    p = one(conn.execute("SELECT data FROM photos WHERE name = ?", (name,)))
    if not p:
        raise ApiError(404, "Photo not found")
    return Response(bytes(p["data"]), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400, immutable"})


# ---------- Collectors ----------

@api.get("/collectors")
def list_collectors(_satin: int = Depends(require_satin), conn=Depends(db)):
    return rows(conn.execute("""
        SELECT c.id, c.name, c.phone, c.qr_token, c.credits, c.basic_phone, c.created_at,
               g.name AS group_name, s.score,
               (SELECT COUNT(*) FROM transactions t WHERE t.collector_id = c.id) AS sales,
               (SELECT COALESCE(SUM(scale_kg),0) FROM transactions t WHERE t.collector_id = c.id) AS total_kg,
               (SELECT COUNT(*) FROM fraud_flags f WHERE f.collector_id = c.id AND f.status = 'open') AS open_flags
        FROM collectors c LEFT JOIN groups g ON g.id = c.group_id LEFT JOIN scores s ON s.collector_id = c.id
        ORDER BY c.id"""))


# Never leaves the backend except to the collector themselves or to Satin: a dealer needs a name to
# serve the person in front of them, not their phone number, UPI handle or QR token.
_COLLECTOR_PRIVATE = ("phone", "qr_token", "upi_vpa", "pin_hash", "id_ref_hash", "consent_at")


def _collector(conn, collector_id: int, *, full: bool) -> dict:
    c = one(conn.execute(
        "SELECT c.*, g.name AS group_name, g.city FROM collectors c LEFT JOIN groups g ON g.id = c.group_id "
        "WHERE c.id = ?", (collector_id,)))
    if not c:
        raise ApiError(404, "Collector not found")
    c.pop("id_ref_hash", None)
    c.pop("pin_hash", None)
    if not full:
        for k in _COLLECTOR_PRIVATE:
            c.pop(k, None)
    return c


@api.get("/collectors/me/requests")
def my_requests(me_id: int = Depends(require_collector), conn=Depends(db)):
    """The collector's own sales, in flight and recent. Two path segments, so it can never be read
    as /collectors/{collector_id}."""
    out = services.collector_requests(conn, me_id)
    # The mock UPI settles when someone next asks about the request, so a list showing "paying"
    # is what nudges it along. A real provider calls the webhook and this does nothing.
    paying = [r["id"] for r in out if r["status"] == "paying"]
    if paying:
        for request_id in paying:
            services.settle_mock_payment(conn, request_id)
        out = services.collector_requests(conn, me_id)
    return out


@api.get("/collectors/by-qr/{token}")
def collector_by_qr(token: str, request: Request, conn=Depends(db)):
    """A dealer looking up the card in their hand. They get a name and a group, nothing more."""
    satin = _session(request, "satin")
    if satin is None and _session(request, "dealer") is None:
        raise ApiError(401, "Please log in as a dealer")
    c = one(conn.execute("SELECT id FROM collectors WHERE qr_token = ?", (token,)))
    if not c:
        raise ApiError(404, "Unknown QR card")
    return _collector(conn, c["id"], full=satin is not None)


@api.get("/collectors/{collector_id}")
def collector_profile(collector_id: int, request: Request, conn=Depends(db)):
    # A collector's full profile — income, flags, loans, score — is for them or for their lender.
    own = _session(request, "collector") == collector_id
    if not own and _session(request, "satin") is None:
        if _session(request, "collector") is None:
            raise ApiError(401, "Please log in")
        raise ApiError(403, "You can only see your own profile")
    c = _collector(conn, collector_id, full=True)
    services.expire_stale(conn)
    s = one(conn.execute("SELECT * FROM scores WHERE collector_id = ?", (collector_id,)))
    return {
        "collector": c,
        "score": {"score": s["score"], "inputs": json.loads(s["inputs_json"]), "computed_at": s["computed_at"]}
                 if s else None,
        "eligibility": score.eligibility(conn, collector_id),
        "transactions": rows(conn.execute(
            "SELECT t.*, d.shop_name, m.label_en, m.label_hi FROM transactions t "
            "JOIN dealers d ON d.id = t.dealer_id JOIN materials m ON m.code = t.material "
            "WHERE t.collector_id = ? ORDER BY t.created_at DESC LIMIT 50", (collector_id,))),
        # Satin underwrites on what actually happened. A sale still in flight is between the
        # collector and their dealer until it completes, so Satin only sees it once it has.
        "requests": rows(conn.execute(
            "SELECT * FROM sale_requests WHERE collector_id = ? " +
            ("" if own else "AND status = 'completed' ") +
            "ORDER BY id DESC LIMIT 10", (collector_id,))),
        "messages": [{**m, "meta": services.json_load(m.pop("meta_json"))} for m in rows(conn.execute(
            "SELECT * FROM messages WHERE collector_id = ? ORDER BY id DESC LIMIT 10", (collector_id,)))],
        "loans": rows(conn.execute("SELECT * FROM loans WHERE collector_id = ? ORDER BY id DESC", (collector_id,))),
        "flags": rows(conn.execute(
            "SELECT * FROM fraud_flags WHERE collector_id = ? ORDER BY id DESC", (collector_id,))),
        "income_by_week": _weekly(conn, "collector_id", collector_id, "amount", weeks=12),
    }


@api.get("/collectors/{collector_id}/score")
def collector_score(collector_id: int, _satin: int = Depends(require_satin), conn=Depends(db)):
    _collector(conn, collector_id, full=False)
    s = score.recompute(conn, collector_id)
    return {**s, "eligibility": score.eligibility(conn, collector_id)}


# ---------- Dealers ----------

@api.get("/dealers")
def list_dealers(conn=Depends(db)):
    """Shop names and locations, so a collector's app can show who is nearby. A dealer's own phone,
    UPI handle and PIN hash are only in their own profile below."""
    return rows(conn.execute(
        "SELECT id, shop_name, owner_name, lat, lng, scale_id, reputation, created_at "
        "FROM dealers ORDER BY id"))


@api.get("/dealers/nearby")
def dealers_nearby(lat: float, lng: float, me_id: int = Depends(require_collector), conn=Depends(db)):
    """Shops the collector can pick from, nearest first. Declared before /dealers/{dealer_id} so
    "nearby" is not read as a dealer id."""
    return services.nearby_dealers(conn, me_id, lat, lng)


@api.get("/dealers/{dealer_id}")
def dealer_profile(dealer_id: int, me_id: int = Depends(require_dealer), conn=Depends(db)):
    _same(me_id, dealer_id, "dealer")
    d = one(conn.execute("SELECT * FROM dealers WHERE id = ?", (dealer_id,)))
    if not d:
        raise ApiError(404, "Dealer not found")
    d.pop("pin_hash", None)
    today = clock.ts()[:10]
    return {
        "dealer": d,
        "today": rows(conn.execute(
            "SELECT t.material, m.label_en, COUNT(*) sales, SUM(t.scale_kg) kg, SUM(t.amount) paid "
            "FROM transactions t JOIN materials m ON m.code = t.material "
            "WHERE t.dealer_id = ? AND substr(t.created_at,1,10) = ? GROUP BY t.material, m.label_en",
            (dealer_id, today))),
        "log": rows(conn.execute(
            "SELECT t.*, c.name AS collector_name, m.label_en FROM transactions t "
            "JOIN collectors c ON c.id = t.collector_id JOIN materials m ON m.code = t.material "
            "WHERE t.dealer_id = ? ORDER BY t.created_at DESC LIMIT 30", (dealer_id,))),
        "open_batches": rows(conn.execute(
            "SELECT b.*, m.label_en FROM batches b JOIN materials m ON m.code = b.material "
            "WHERE b.dealer_id = ? AND b.recycler_sale_id IS NULL AND b.total_kg > 0 ORDER BY b.id DESC",
            (dealer_id,))),
        "recycler_sales": rows(conn.execute(
            "SELECT * FROM recycler_sales WHERE dealer_id = ? ORDER BY sold_at DESC LIMIT 10", (dealer_id,))),
        "mass_balance": fraud.mass_balance(conn, dealer_id),
    }


@api.get("/dealers/{dealer_id}/queue")
def dealer_queue(dealer_id: int, me_id: int = Depends(require_dealer), conn=Depends(db)):
    """Requests this collector sent to this dealer, and nobody else's.

    There is no broadcast any more: a sale is a business matter between the two of them, so another
    dealer never learns that it exists, let alone the collector's name or photo."""
    _same(me_id, dealer_id, "dealer")
    services.expire_stale(conn)
    d = one(conn.execute("SELECT * FROM dealers WHERE id = ?", (dealer_id,)))
    if not d:
        raise ApiError(404, "Dealer not found")
    reqs = rows(conn.execute(
        "SELECT r.*, c.name AS collector_name, c.basic_phone, m.label_en, m.rate_per_kg "
        "FROM sale_requests r JOIN collectors c ON c.id = r.collector_id JOIN materials m ON m.code = r.material "
        "WHERE r.dealer_id = ? AND r.status IN ('open','accepted','weighed','paying','awaiting_ivr') "
        "ORDER BY r.created_at DESC", (dealer_id,)))
    for r in reqs:
        if r["lat"] is not None:
            r["distance_m"] = round(fraud.haversine_m(r["lat"], r["lng"], d["lat"], d["lng"]))
    return reqs


# ---------- Sale flow ----------

@api.post("/requests", status_code=201)
async def create_request(
    request: Request,
    material: str = Form(...), est_kg: float = Form(...),
    lat: float | None = Form(None), lng: float | None = Form(None), photo: UploadFile = File(...),
    collector_id: int | None = Form(None),
    # The shop the collector picked. Optional in the signature only so that acting as someone else
    # is still answered with 403 rather than a validation error about a missing field.
    dealer_id: int | None = Form(None),
    # Set after the collector has seen the photo-check warning and chosen "Send anyway".
    confirm_mismatch: bool = Form(False),
    # Demo only (WW_DEMO_MODE=1): script what the photo check "sees", to show the warning on stage.
    demo_ai_material: str | None = Form(None),
):
    me_id = _same(require_collector(request), collector_id, "collector")
    if dealer_id is None:
        raise ApiError(400, "Pick the shop you are selling to")
    data = await photo.read()
    if len(data) > 4_000_000:
        raise ApiError(413, "Photo too large")
    # A reused photo is refused before the photo check: no point waiting seconds and paying for a
    # model call on a sale that is about to be turned down. (create_request checks again, inside
    # its transaction, in case the same photo arrives twice at once.)
    phash_hex = await run_in_threadpool(services.photo_hash_or_400, data)
    with _tx() as conn:
        services.refuse_duplicate_photo(conn, me_id, phash_hex)
    # The photo check calls an external model and can take seconds. Run it before taking the
    # instance lock and opening a transaction, and off the event loop, so a slow model never stalls
    # other requests or holds a database connection open.
    clean, ai = await run_in_threadpool(services.check_photo, material, data, demo_ai_material)
    with _tx() as conn:
        return services.create_request(conn, collector_id=me_id, material_code=material,
                                       est_kg=est_kg, lat=lat, lng=lng, photo=data,
                                       dealer_id=dealer_id, confirm_mismatch=confirm_mismatch,
                                       demo_ai_material=demo_ai_material, checked=(clean, ai))


def _may_see_request(request: Request, req: dict) -> bool:
    """The collector it belongs to, the dealer they chose, or Satin. Nobody else."""
    # Compare only real sessions: requests from before dealer choice have dealer_id NULL, and an
    # anonymous visitor's missing session must not "match" that.
    if _session(request, "satin") is not None:
        return True
    collector = _session(request, "collector")
    if collector is not None and collector == req["collector_id"]:
        return True
    dealer = _session(request, "dealer")
    return dealer is not None and dealer == req["dealer_id"]


@api.get("/requests/{request_id}")
def get_request(request_id: int, request: Request, conn=Depends(db)):
    req = services.get_request(conn, request_id)
    if not _may_see_request(request, req):
        # Same answer as for a request that does not exist: "someone else's" would confirm it does.
        raise ApiError(404, "Request not found")
    services.settle_mock_payment(conn, request_id)
    req = services.get_request(conn, request_id)
    tx = one(conn.execute("SELECT * FROM transactions WHERE request_id = ?", (request_id,)))
    pay = one(conn.execute("SELECT * FROM payments WHERE request_id = ? ORDER BY id DESC", (request_id,)))
    m = services.material(conn, req["material"])
    return {"request": req, "transaction": tx, "payment": pay, "material": m}


@api.post("/requests/{request_id}/cancel")
def cancel_request(request_id: int, me_id: int = Depends(require_collector), conn=Depends(db)):
    return services.cancel_request(conn, request_id, collector_id=me_id)


class AcceptBody(BaseModel):
    dealer_id: int | None = None
    qr_token: str
    lat: float
    lng: float


@api.post("/requests/{request_id}/accept")
def accept(request_id: int, body: AcceptBody, me_id: int = Depends(require_dealer), conn=Depends(db)):
    dealer_id = _same(me_id, body.dealer_id, "dealer")
    return services.accept_request(conn, request_id, dealer_id=dealer_id, qr_token=body.qr_token,
                                   lat=body.lat, lng=body.lng)


class WeighBody(BaseModel):
    dealer_id: int | None = None
    mode: str = Field("normal", pattern="^(normal|overstated)$")


@api.post("/requests/{request_id}/weigh")
def weigh(request_id: int, body: WeighBody, me_id: int = Depends(require_dealer), conn=Depends(db)):
    return services.weigh_request(conn, request_id, dealer_id=_same(me_id, body.dealer_id, "dealer"),
                                  mode=body.mode)


class ApproveBody(BaseModel):
    dealer_id: int | None = None
    # What the dealer confirmed with the scrap on the scale; defaults to the collector's choice.
    material: str | None = None


@api.post("/requests/{request_id}/approve")
def approve(request_id: int, body: ApproveBody, me_id: int = Depends(require_dealer), conn=Depends(db)):
    # With the mock UPI adapter the payment settles on the next GET /requests/{id} after ~1 s.
    return services.approve_request(conn, request_id, dealer_id=_same(me_id, body.dealer_id, "dealer"),
                                    dealer_material=body.material)


class WebhookBody(BaseModel):
    provider_ref: str
    status: str


@api.post("/payments/webhook")
async def payment_webhook(request: Request, conn=Depends(db)):
    """Called by the payment aggregator. Anyone who could post here unsigned could mark any pending
    payment successful, so the signature is checked before the body is even parsed."""
    body: WebhookBody = await provider_payload(request, WebhookBody)
    return services.payment_webhook(conn, body.provider_ref, body.status)


class UpiObserved(BaseModel):
    from_vpa: str
    to_vpa: str
    amount: float
    upi_ref: str | None = None


@api.post("/upi/observed")
async def upi_observed(request: Request, conn=Depends(db)):
    """Aggregator feed of transfers between platform VPAs; runs the circular-payment rule.
    Signed: unsigned posts here could invent a circular payment against any collector."""
    body: UpiObserved = await provider_payload(request, UpiObserved)
    return services.observe_upi(conn, **body.model_dump())


class IvrStart(BaseModel):
    dealer_id: int | None = None
    qr_token: str
    material: str
    est_kg: float


@api.post("/ivr/start")
def ivr_start(body: IvrStart, me_id: int = Depends(require_dealer), conn=Depends(db)):
    return services.ivr_start(conn, dealer_id=_same(me_id, body.dealer_id, "dealer"), qr_token=body.qr_token,
                              material_code=body.material, est_kg=body.est_kg)


class IvrConfirm(BaseModel):
    request_id: int
    caller_phone: str
    digit: str


@api.post("/ivr/confirm")
async def ivr_confirm(request: Request, conn=Depends(db)):
    """Called by the IVR provider when the collector presses a key. Signed, because this is the only
    consent a basic-phone collector gives. The dealer's on-stage button uses the demo route below."""
    body: IvrConfirm = await provider_payload(request, IvrConfirm)
    return services.ivr_confirm(conn, **body.model_dump())


class RecyclerSaleBody(BaseModel):
    dealer_id: int | None = None
    recycler_name: str
    material: str
    kg: float
    invoice_ref: str


@api.post("/recycler-sales", status_code=201)
def recycler_sale(body: RecyclerSaleBody, me_id: int = Depends(require_dealer), conn=Depends(db)):
    return services.recycler_sale(conn, dealer_id=_same(me_id, body.dealer_id, "dealer"),
                                  recycler_name=body.recycler_name, material_code=body.material,
                                  kg=body.kg, invoice_ref=body.invoice_ref)


# ---------- Satin ----------
# Every route here needs a Satin branch-staff session (phone + PIN, see /auth/login with role=satin):
# together they read collectors' personal data, review fraud flags and disburse money.

@api.get("/flags")
def list_flags(status: str | None = None, _satin: int = Depends(require_satin), conn=Depends(db)):
    q = ("SELECT f.*, c.name AS collector_name, d.shop_name FROM fraud_flags f "
         "LEFT JOIN collectors c ON c.id = f.collector_id LEFT JOIN dealers d ON d.id = f.dealer_id ")
    args = ()
    if status:
        q += "WHERE f.status = ? "
        args = (status,)
    out = rows(conn.execute(q + "ORDER BY f.created_at DESC, f.id DESC", args))
    for f in out:
        f["evidence"] = services.json_load(f.pop("evidence_json"))
        f["rule_label"] = fraud.RULE_LABELS.get(f["rule"], f["rule"])
    return out


class FlagUpdate(BaseModel):
    status: str = Field(pattern="^(confirmed|dismissed|open)$")


@api.post("/flags/{flag_id}")
def update_flag(flag_id: int, body: FlagUpdate, _satin: int = Depends(require_satin), conn=Depends(db)):
    f = one(conn.execute("SELECT * FROM fraud_flags WHERE id = ?", (flag_id,)))
    if not f:
        raise ApiError(404, "Flag not found")
    conn.execute("UPDATE fraud_flags SET status = ? WHERE id = ?", (body.status, flag_id))
    # A confirmed flag lowers the dealer's reputation; eligibility freeze follows from the flag itself.
    if body.status == "confirmed" and f["status"] != "confirmed" and f["dealer_id"]:
        conn.execute("UPDATE dealers SET reputation = CASE WHEN reputation > 10 THEN reputation - 10 ELSE 0 END "
                     "WHERE id = ?", (f["dealer_id"],))
    return one(conn.execute("SELECT * FROM fraud_flags WHERE id = ?", (flag_id,)))


@api.post("/scores/recompute")
def recompute_scores(_satin: int = Depends(require_satin), conn=Depends(db)):
    return {"recomputed": score.recompute_all(conn)}


class LoanBody(BaseModel):
    collector_id: int


@api.post("/loans", status_code=201)
def create_loan(body: LoanBody, _satin: int = Depends(require_satin), conn=Depends(db)):
    return services.disburse_starter_loan(conn, body.collector_id)


@api.get("/groups")
def list_groups(_satin: int = Depends(require_satin), conn=Depends(db)):
    groups = rows(conn.execute("SELECT * FROM groups ORDER BY id"))
    for g in groups:
        g["members"] = rows(conn.execute(
            "SELECT c.id, c.name, c.group_guarantee, s.score, "
            "(SELECT status FROM loans l WHERE l.collector_id = c.id ORDER BY id DESC LIMIT 1) AS loan_status, "
            "(SELECT COALESCE(SUM(instalments_on_time),0) FROM loans l WHERE l.collector_id = c.id) AS on_time, "
            "(SELECT COALESCE(SUM(instalments_due),0) FROM loans l WHERE l.collector_id = c.id) AS due "
            "FROM collectors c LEFT JOIN scores s ON s.collector_id = c.id WHERE c.group_id = ? ORDER BY c.id",
            (g["id"],)))
        for m in g["members"]:
            m["repayment"] = f"{int(m.pop('on_time'))}/{int(m.pop('due'))}"
    return groups


def _weekly(conn, col: str | None, val, field: str, weeks: int = 8) -> list[dict]:
    now = clock.now()
    out = []
    for i in reversed(range(weeks)):
        end = now - timedelta(days=7 * i)
        start = end - timedelta(days=7)
        q = f"SELECT COALESCE(SUM({field}),0) FROM transactions WHERE created_at >= ? AND created_at < ?"
        args = [clock.ts(start), clock.ts(end + timedelta(seconds=1))]
        if col:
            q += f" AND {col} = ?"
            args.append(val)
        out.append({"week_start": clock.ts(start)[:10], "value": round(conn.execute(q, args).fetchone()[0], 1)})
    return out


@api.get("/satin/overview")
def satin_overview(_satin: int = Depends(require_satin), conn=Depends(db)):
    month_ago = clock.ago(days=30)
    active = conn.execute(
        "SELECT COUNT(*) FROM (SELECT collector_id FROM transactions WHERE created_at >= ? "
        "GROUP BY collector_id HAVING COUNT(DISTINCT substr(created_at,1,10)) >= 8) a", (month_ago,)).fetchone()[0]
    kg_month = conn.execute("SELECT COALESCE(SUM(scale_kg),0) FROM transactions WHERE created_at >= ?",
                            (month_ago,)).fetchone()[0]
    by_material = rows(conn.execute(
        "SELECT t.material, m.label_en, m.co2e_per_kg, SUM(t.scale_kg) kg, SUM(t.amount) paid "
        "FROM transactions t JOIN materials m ON m.code = t.material WHERE t.created_at >= ? "
        "GROUP BY t.material, m.label_en, m.co2e_per_kg ORDER BY kg DESC", (month_ago,)))
    co2e = sum(r["kg"] * r["co2e_per_kg"] for r in by_material if r["co2e_per_kg"])
    loans = one(conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(principal),0) principal, "
        "COALESCE(SUM(instalments_on_time),0) on_time, COALESCE(SUM(instalments_due),0) due FROM loans"))
    eligible = sum(1 for r in rows(conn.execute("SELECT id FROM collectors"))
                   if score.eligibility(conn, r["id"])["eligible"])
    return {
        "collectors": conn.execute("SELECT COUNT(*) FROM collectors").fetchone()[0],
        "active_collectors": active,
        "tonnes_month": round(kg_month / 1000, 2),
        "upi_share": 1.0,  # by construction: no record without a UPI payment
        "loans": loans,
        "eligible_now": eligible,
        "open_flags": conn.execute("SELECT COUNT(*) FROM fraud_flags WHERE status='open'").fetchone()[0],
        "by_material": by_material,
        "co2e_kg_month": round(co2e),
        "kg_by_week": _weekly(conn, None, None, "scale_kg", weeks=8),
        "dealers": [{**d, "mass_balance": fraud.mass_balance(conn, d["id"])}
                    for d in rows(conn.execute("SELECT id, shop_name, reputation FROM dealers ORDER BY id"))],
    }


def _collector_ref(collector_id: int) -> str:
    """Stable pseudonym for brands: keyed hash, so it can't be reversed to the collector's id."""
    return "C-" + hashlib.sha256(auth.SECRET + f":collector:{collector_id}".encode()).hexdigest()[:6].upper()


@api.get("/batches/{code}")
def batch_trace(code: str, _satin: int = Depends(require_satin), conn=Depends(db)):
    """Pseudonymised trace for recyclers/brands: no names or phone numbers."""
    b = one(conn.execute("SELECT b.*, d.shop_name FROM batches b JOIN dealers d ON d.id = b.dealer_id "
                         "WHERE b.code = ?", (code,)))
    if not b:
        raise ApiError(404, "Batch not found")
    txs = [{"collector_ref": _collector_ref(t.pop("collector_id")), **t} for t in rows(conn.execute(
        "SELECT collector_id, scale_kg, created_at, upi_ref FROM transactions WHERE batch_id = ? "
        "ORDER BY created_at", (b["id"],)))]
    sale = one(conn.execute("SELECT recycler_name, kg, invoice_ref, sold_at FROM recycler_sales WHERE id = ?",
                            (b["recycler_sale_id"],))) if b["recycler_sale_id"] else None
    return {"batch": b, "sales": txs, "recycler_sale": sale}


# ---------- Demo-only routes ----------
# These exist so the recording can be driven from the stage. They are off by default: reset needs
# WW_ALLOW_RESET=1 plus the X-Demo-Key secret, and the rest 404 unless WW_DEMO_MODE=1.

@api.post("/demo/reset")
def demo_reset(request: Request):
    """Wipes and reseeds everything, so it is locked behind both a switch and a shared secret."""
    if not auth.demo_reset_allowed():
        raise ApiError(403, "Reset is disabled. Set WW_ALLOW_RESET=1 to allow it.")
    if not auth.demo_key_ok(request.headers.get("x-demo-key")):
        raise ApiError(403, "Missing or wrong X-Demo-Key")
    from .seed import seed
    try:
        with _lock, _setup_lock():
            _db.ensure_alive()
            seed(_db, wipe=True)
    except SetupBusy:
        raise ApiError(503, "Another reset or setup is running. Try again in a minute.")
    return {"ok": True}


class SimulateScanBody(BaseModel):
    lat: float
    lng: float


@api.post("/demo/requests/{request_id}/simulate-scan", dependencies=[Depends(require_demo_mode)])
def demo_simulate_scan(request_id: int, body: SimulateScanBody,
                       me_id: int = Depends(require_dealer), conn=Depends(db)):
    """Stands in for pointing the camera at the collector's QR card. The token stays on the server:
    dealers are never told a collector's QR token, so the scan has to be simulated here."""
    req = services.dealer_request(conn, request_id, me_id)
    c = one(conn.execute("SELECT qr_token FROM collectors WHERE id = ?", (req["collector_id"],)))
    if not c:
        raise ApiError(404, "Collector not found")
    return services.accept_request(conn, request_id, dealer_id=me_id, qr_token=c["qr_token"],
                                   lat=body.lat, lng=body.lng)


@api.post("/demo/requests/{request_id}/ivr-confirm", dependencies=[Depends(require_demo_mode)])
def demo_ivr_confirm(request_id: int, me_id: int = Depends(require_dealer), conn=Depends(db)):
    """The dealer's "collector presses 1" button. The real /ivr/confirm needs the provider's
    signature and the collector's caller ID; this looks the phone number up instead."""
    req = services.dealer_request(conn, request_id, me_id)
    c = one(conn.execute("SELECT phone FROM collectors WHERE id = ?", (req["collector_id"],)))
    return services.ivr_confirm(conn, request_id=request_id, caller_phone=c["phone"], digit="1")


app.include_router(api)
