"""WorthyWaste API. Every step of a sale is its own call, so every fraud check runs at the step it guards."""
import json
import os
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import adapters, clock, fraud, score, services
from .db import PHOTO_DIR, connect, init_db, one, rows, transaction
from .services import ApiError

_conn = connect()
init_db(_conn)
# One SQLite connection guarded by a lock: plenty for a demo and a single-city pilot API.
# A plain Lock, not an RLock: FastAPI may run a sync dependency's setup and teardown on different
# worker threads, and only a Lock can be released by a thread other than the one that acquired it.
# Nothing here acquires it re-entrantly.
_lock = threading.Lock()


@contextmanager
def _tx():
    """One locked transaction; on ApiError, still record what the refusal says must be kept."""
    with _lock:
        try:
            with transaction(_conn):
                yield _conn
        except ApiError as e:
            if e.persist:
                with transaction(_conn):
                    for write in e.persist:
                        write(_conn)
            raise


def db():
    with _tx() as conn:
        yield conn


@asynccontextmanager
async def lifespan(app: FastAPI):
    with _lock:
        if _conn.execute("SELECT COUNT(*) FROM collectors").fetchone()[0] == 0:
            from .seed import seed
            seed(_conn)
    yield


app = FastAPI(title="WorthyWaste API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("WW_CORS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
PHOTO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/photos", StaticFiles(directory=PHOTO_DIR), name="photos")


@app.exception_handler(ApiError)
async def api_error(_: Request, e: ApiError):
    return JSONResponse(status_code=e.status,
                        content={"error": e.message, "rule": e.rule, "evidence": e.evidence})


@app.get("/health")
def health():
    return {"ok": True, "time": clock.ts(), "scripted": os.environ.get("WW_SCRIPTED") == "1"}


@app.get("/materials")
def materials(conn=Depends(db)):
    return rows(conn.execute("SELECT * FROM materials ORDER BY rowid"))


# ---------- Collectors ----------

@app.get("/collectors")
def list_collectors(conn=Depends(db)):
    return rows(conn.execute("""
        SELECT c.id, c.name, c.phone, c.qr_token, c.credits, c.basic_phone, c.created_at,
               g.name AS group_name, s.score,
               (SELECT COUNT(*) FROM transactions t WHERE t.collector_id = c.id) AS sales,
               (SELECT COALESCE(SUM(scale_kg),0) FROM transactions t WHERE t.collector_id = c.id) AS total_kg,
               (SELECT COUNT(*) FROM fraud_flags f WHERE f.collector_id = c.id AND f.status = 'open') AS open_flags
        FROM collectors c LEFT JOIN groups g ON g.id = c.group_id LEFT JOIN scores s ON s.collector_id = c.id
        ORDER BY c.id"""))


def _collector(conn, collector_id: int) -> dict:
    c = one(conn.execute(
        "SELECT c.*, g.name AS group_name, g.city FROM collectors c LEFT JOIN groups g ON g.id = c.group_id "
        "WHERE c.id = ?", (collector_id,)))
    if not c:
        raise ApiError(404, "Collector not found")
    c.pop("id_ref_hash", None)
    return c


@app.get("/collectors/by-qr/{token}")
def collector_by_qr(token: str, conn=Depends(db)):
    c = one(conn.execute("SELECT id FROM collectors WHERE qr_token = ?", (token,)))
    if not c:
        raise ApiError(404, "Unknown QR card")
    return _collector(conn, c["id"])


@app.get("/collectors/{collector_id}")
def collector_profile(collector_id: int, conn=Depends(db)):
    c = _collector(conn, collector_id)
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
        "requests": rows(conn.execute(
            "SELECT * FROM sale_requests WHERE collector_id = ? ORDER BY id DESC LIMIT 10", (collector_id,))),
        "messages": [{**m, "meta": services.json_load(m.pop("meta_json"))} for m in rows(conn.execute(
            "SELECT * FROM messages WHERE collector_id = ? ORDER BY id DESC LIMIT 10", (collector_id,)))],
        "loans": rows(conn.execute("SELECT * FROM loans WHERE collector_id = ? ORDER BY id DESC", (collector_id,))),
        "flags": rows(conn.execute(
            "SELECT * FROM fraud_flags WHERE collector_id = ? ORDER BY id DESC", (collector_id,))),
        "income_by_week": _weekly(conn, "collector_id", collector_id, "amount", weeks=12),
    }


@app.get("/collectors/{collector_id}/score")
def collector_score(collector_id: int, conn=Depends(db)):
    _collector(conn, collector_id)
    s = score.recompute(conn, collector_id)
    return {**s, "eligibility": score.eligibility(conn, collector_id)}


# ---------- Dealers ----------

@app.get("/dealers")
def list_dealers(conn=Depends(db)):
    return rows(conn.execute("SELECT * FROM dealers ORDER BY id"))


@app.get("/dealers/{dealer_id}")
def dealer_profile(dealer_id: int, conn=Depends(db)):
    d = one(conn.execute("SELECT * FROM dealers WHERE id = ?", (dealer_id,)))
    if not d:
        raise ApiError(404, "Dealer not found")
    today = clock.ts()[:10]
    return {
        "dealer": d,
        "today": rows(conn.execute(
            "SELECT t.material, m.label_en, COUNT(*) sales, SUM(t.scale_kg) kg, SUM(t.amount) paid "
            "FROM transactions t JOIN materials m ON m.code = t.material "
            "WHERE t.dealer_id = ? AND substr(t.created_at,1,10) = ? GROUP BY t.material", (dealer_id, today))),
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


@app.get("/dealers/{dealer_id}/queue")
def dealer_queue(dealer_id: int, conn=Depends(db)):
    """Open requests nearby plus this dealer's in-progress ones."""
    services.expire_stale(conn)
    d = one(conn.execute("SELECT * FROM dealers WHERE id = ?", (dealer_id,)))
    if not d:
        raise ApiError(404, "Dealer not found")
    reqs = rows(conn.execute(
        "SELECT r.*, c.name AS collector_name, c.basic_phone, m.label_en, m.rate_per_kg "
        "FROM sale_requests r JOIN collectors c ON c.id = r.collector_id JOIN materials m ON m.code = r.material "
        "WHERE r.status = 'open' OR (r.dealer_id = ? AND r.status IN ('accepted','weighed','paying','awaiting_ivr')) "
        "ORDER BY r.created_at DESC", (dealer_id,)))
    out = []
    for r in reqs:
        if r["lat"] is not None:
            r["distance_m"] = round(fraud.haversine_m(r["lat"], r["lng"], d["lat"], d["lng"]))
            if r["status"] == "open" and r["distance_m"] > 2000:
                continue
        out.append(r)
    return out


# ---------- Sale flow ----------

@app.post("/requests", status_code=201)
async def create_request(
    collector_id: int = Form(...), material: str = Form(...), est_kg: float = Form(...),
    lat: float | None = Form(None), lng: float | None = Form(None), photo: UploadFile = File(...),
):
    data = await photo.read()
    if len(data) > 5_000_000:
        raise ApiError(413, "Photo too large")
    with _tx() as conn:
        return services.create_request(conn, collector_id=collector_id, material_code=material,
                                       est_kg=est_kg, lat=lat, lng=lng, photo=data)


@app.get("/requests/{request_id}")
def get_request(request_id: int, conn=Depends(db)):
    req = services.get_request(conn, request_id)
    tx = one(conn.execute("SELECT * FROM transactions WHERE request_id = ?", (request_id,)))
    pay = one(conn.execute("SELECT * FROM payments WHERE request_id = ? ORDER BY id DESC", (request_id,)))
    m = services.material(conn, req["material"])
    return {"request": req, "transaction": tx, "payment": pay, "material": m}


class AcceptBody(BaseModel):
    dealer_id: int
    qr_token: str
    lat: float
    lng: float


@app.post("/requests/{request_id}/accept")
def accept(request_id: int, body: AcceptBody, conn=Depends(db)):
    return services.accept_request(conn, request_id, **body.model_dump())


class WeighBody(BaseModel):
    dealer_id: int
    mode: str = Field("normal", pattern="^(normal|overstated)$")


@app.post("/requests/{request_id}/weigh")
def weigh(request_id: int, body: WeighBody, conn=Depends(db)):
    return services.weigh_request(conn, request_id, dealer_id=body.dealer_id, mode=body.mode)


class ApproveBody(BaseModel):
    dealer_id: int


@app.post("/requests/{request_id}/approve")
def approve(request_id: int, body: ApproveBody, conn=Depends(db)):
    out = services.approve_request(conn, request_id, dealer_id=body.dealer_id)
    delay = adapters.payments.mock_webhook_delay
    if delay is not None and out["payment"]["status"] == "pending":
        ref = out["payment"]["provider_ref"]
        threading.Timer(delay, _mock_provider_callback, args=(ref,)).start()
    return out


def _mock_provider_callback(ref: str):
    with _lock, transaction(_conn):
        services.payment_webhook(_conn, ref, "success")


class WebhookBody(BaseModel):
    provider_ref: str
    status: str


@app.post("/payments/webhook")
def payment_webhook(body: WebhookBody, conn=Depends(db)):
    # Pilot: verify the aggregator's signature header before trusting this.
    return services.payment_webhook(conn, body.provider_ref, body.status)


class UpiObserved(BaseModel):
    from_vpa: str
    to_vpa: str
    amount: float
    upi_ref: str | None = None


@app.post("/upi/observed")
def upi_observed(body: UpiObserved, conn=Depends(db)):
    """Aggregator feed of transfers between platform VPAs; runs the circular-payment rule."""
    return services.observe_upi(conn, **body.model_dump())


class IvrStart(BaseModel):
    dealer_id: int
    qr_token: str
    material: str
    est_kg: float


@app.post("/ivr/start")
def ivr_start(body: IvrStart, conn=Depends(db)):
    return services.ivr_start(conn, dealer_id=body.dealer_id, qr_token=body.qr_token,
                              material_code=body.material, est_kg=body.est_kg)


class IvrConfirm(BaseModel):
    request_id: int
    caller_phone: str
    digit: str


@app.post("/ivr/confirm")
def ivr_confirm(body: IvrConfirm, conn=Depends(db)):
    return services.ivr_confirm(conn, **body.model_dump())


class RecyclerSaleBody(BaseModel):
    dealer_id: int
    recycler_name: str
    material: str
    kg: float
    invoice_ref: str


@app.post("/recycler-sales", status_code=201)
def recycler_sale(body: RecyclerSaleBody, conn=Depends(db)):
    return services.recycler_sale(conn, dealer_id=body.dealer_id, recycler_name=body.recycler_name,
                                  material_code=body.material, kg=body.kg, invoice_ref=body.invoice_ref)


# ---------- Satin ----------

@app.get("/flags")
def list_flags(status: str | None = None, conn=Depends(db)):
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


@app.post("/flags/{flag_id}")
def update_flag(flag_id: int, body: FlagUpdate, conn=Depends(db)):
    f = one(conn.execute("SELECT * FROM fraud_flags WHERE id = ?", (flag_id,)))
    if not f:
        raise ApiError(404, "Flag not found")
    conn.execute("UPDATE fraud_flags SET status = ? WHERE id = ?", (body.status, flag_id))
    # A confirmed flag lowers the dealer's reputation; eligibility freeze follows from the flag itself.
    if body.status == "confirmed" and f["status"] != "confirmed" and f["dealer_id"]:
        conn.execute("UPDATE dealers SET reputation = MAX(0, reputation - 10) WHERE id = ?", (f["dealer_id"],))
    return one(conn.execute("SELECT * FROM fraud_flags WHERE id = ?", (flag_id,)))


@app.post("/scores/recompute")
def recompute_scores(conn=Depends(db)):
    return {"recomputed": score.recompute_all(conn)}


@app.post("/loans", status_code=201)
def create_loan(body: dict, conn=Depends(db)):
    return services.disburse_starter_loan(conn, int(body["collector_id"]))


@app.get("/groups")
def list_groups(conn=Depends(db)):
    groups = rows(conn.execute("SELECT * FROM groups ORDER BY id"))
    for g in groups:
        g["members"] = rows(conn.execute(
            "SELECT c.id, c.name, c.group_guarantee, s.score, "
            "(SELECT status FROM loans l WHERE l.collector_id = c.id ORDER BY id DESC LIMIT 1) AS loan_status, "
            "(SELECT COALESCE(SUM(instalments_on_time),0) || '/' || COALESCE(SUM(instalments_due),0) "
            " FROM loans l WHERE l.collector_id = c.id) AS repayment "
            "FROM collectors c LEFT JOIN scores s ON s.collector_id = c.id WHERE c.group_id = ?", (g["id"],)))
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


@app.get("/satin/overview")
def satin_overview(conn=Depends(db)):
    month_ago = clock.ago(days=30)
    active = conn.execute(
        "SELECT COUNT(*) FROM (SELECT collector_id FROM transactions WHERE created_at >= ? "
        "GROUP BY collector_id HAVING COUNT(DISTINCT substr(created_at,1,10)) >= 8)", (month_ago,)).fetchone()[0]
    kg_month = conn.execute("SELECT COALESCE(SUM(scale_kg),0) FROM transactions WHERE created_at >= ?",
                            (month_ago,)).fetchone()[0]
    by_material = rows(conn.execute(
        "SELECT t.material, m.label_en, m.co2e_per_kg, SUM(t.scale_kg) kg, SUM(t.amount) paid "
        "FROM transactions t JOIN materials m ON m.code = t.material WHERE t.created_at >= ? "
        "GROUP BY t.material ORDER BY kg DESC", (month_ago,)))
    co2e = sum(r["kg"] * r["co2e_per_kg"] for r in by_material if r["co2e_per_kg"])
    loans = one(conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(principal),0) principal, "
        "COALESCE(SUM(instalments_on_time),0) on_time, COALESCE(SUM(instalments_due),0) due FROM loans"))
    eligible = sum(1 for (cid,) in conn.execute("SELECT id FROM collectors")
                   if score.eligibility(conn, cid)["eligible"])
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
                    for d in rows(conn.execute("SELECT id, shop_name, reputation FROM dealers"))],
    }


@app.get("/batches/{code}")
def batch_trace(code: str, conn=Depends(db)):
    """Pseudonymised trace for recyclers/brands: no names or phone numbers."""
    b = one(conn.execute("SELECT b.*, d.shop_name FROM batches b JOIN dealers d ON d.id = b.dealer_id "
                         "WHERE b.code = ?", (code,)))
    if not b:
        raise ApiError(404, "Batch not found")
    txs = rows(conn.execute(
        "SELECT 'C-' || substr(hex(collector_id * 7919), -4) AS collector_ref, scale_kg, created_at, upi_ref "
        "FROM transactions WHERE batch_id = ? ORDER BY created_at", (b["id"],)))
    sale = one(conn.execute("SELECT recycler_name, kg, invoice_ref, sold_at FROM recycler_sales WHERE id = ?",
                            (b["recycler_sale_id"],))) if b["recycler_sale_id"] else None
    return {"batch": b, "sales": txs, "recycler_sale": sale}


@app.post("/demo/reset")
def demo_reset():
    if os.environ.get("WW_ALLOW_RESET", "1") != "1":
        raise ApiError(403, "Reset disabled")
    from .seed import seed
    with _lock:
        seed(_conn, wipe=True)
    return {"ok": True}
