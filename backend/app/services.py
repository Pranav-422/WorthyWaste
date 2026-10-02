"""Transaction flow: request → accept → weigh → approve → payment webhook → transaction.
A sale becomes a transaction only once payment succeeds."""
import json
import secrets
import uuid
from datetime import timedelta


from . import adapters, clock, fraud, phash, score
from .db import one, rows

REQUEST_TTL_MIN = 15
CREDITS_PER_KG = 1


class ApiError(Exception):
    """A refused request. The request's transaction rolls back; `persist` holds writes that must
    survive anyway (e.g. the fraud flag explaining why it was refused), run in a fresh transaction."""

    def __init__(self, status: int, message: str, rule: str | None = None, evidence: dict | None = None,
                 persist=None):
        super().__init__(message)
        self.status, self.message, self.rule, self.evidence = status, message, rule, evidence or {}
        self.persist = persist or []


def expire_stale(conn) -> None:
    conn.execute(
        "UPDATE sale_requests SET status = 'expired' WHERE status IN ('open', 'awaiting_ivr') AND expires_at < ?",
        (clock.ts(),),
    )


def get_request(conn, request_id: int) -> dict:
    expire_stale(conn)
    req = one(conn.execute("SELECT * FROM sale_requests WHERE id = ?", (request_id,)))
    if not req:
        raise ApiError(404, "Request not found")
    return req


def material(conn, code: str) -> dict:
    m = one(conn.execute("SELECT * FROM materials WHERE code = ?", (code,)))
    if not m:
        raise ApiError(400, f"Unknown material '{code}'")
    return m


def photo_phash(data: bytes) -> str:
    return phash.phash(data)


# ---------- Step 1: collector raises a request ----------

def create_request(conn, *, collector_id: int, material_code: str, est_kg: float,
                   lat: float | None, lng: float | None, photo: bytes) -> dict:
    c = one(conn.execute("SELECT * FROM collectors WHERE id = ?", (collector_id,)))
    if not c:
        raise ApiError(404, "Collector not found")
    material(conn, material_code)
    if not (0 < est_kg <= 500):
        raise ApiError(400, "Estimated weight must be between 0 and 500 kg")
    try:
        phash_hex = photo_phash(photo)
    except Exception:
        raise ApiError(400, "Photo could not be read")

    dup = fraud.find_duplicate_photo(conn, phash_hex)
    if dup:
        same = dup["collector_id"] == collector_id
        flag = lambda c: fraud.raise_flag(  # noqa: E731
            c, entity_type="collector", entity_id=collector_id, rule="duplicate_photo",
            detail=("Reused a photo from" if same else "Used another collector's photo from")
                   + f" request #{dup['request_id']} (hash distance {dup['distance']})",
            evidence=dup, collector_id=collector_id, dedupe_hours=1,
        )
        raise ApiError(409, "This photo was already used", rule="duplicate_photo", evidence=dup, persist=[flag])

    name = f"{uuid.uuid4().hex}.jpg"
    conn.execute("INSERT INTO photos (name, data, created_at) VALUES (?,?,?)", (name, photo, clock.ts()))
    now = clock.now()
    cur = conn.execute(
        "INSERT INTO sale_requests (collector_id, material, est_kg, photo_url, photo_phash, lat, lng, "
        "status, created_at, expires_at) VALUES (?,?,?,?,?,?,?, 'open', ?, ?)",
        (collector_id, material_code, est_kg, f"/api/photos/{name}", phash_hex, lat, lng,
         clock.ts(now), clock.ts(now + timedelta(minutes=REQUEST_TTL_MIN))),
    )
    return get_request(conn, cur.lastrowid)


# ---------- Step 2: dealer scans QR and accepts ----------

def accept_request(conn, request_id: int, *, dealer_id: int, qr_token: str,
                   lat: float, lng: float) -> dict:
    req = get_request(conn, request_id)
    if req["status"] == "expired":
        raise ApiError(410, "Request expired — ask the collector to send a new one", rule="request_expiry")
    if req["status"] != "open":
        raise ApiError(409, f"Request is already {req['status']}")
    c = one(conn.execute("SELECT * FROM collectors WHERE id = ?", (req["collector_id"],)))
    if c["qr_token"] != qr_token:
        raise ApiError(403, "QR card does not belong to this request's collector", rule="qr_mismatch")
    if not one(conn.execute("SELECT id FROM dealers WHERE id = ?", (dealer_id,))):
        raise ApiError(404, "Dealer not found")
    try:
        d = fraud.check_location(req, lat, lng)
    except fraud.Blocked as b:
        raise ApiError(403, b.message, rule=b.rule, evidence=b.evidence)
    conn.execute(
        "UPDATE sale_requests SET status='accepted', dealer_id=?, dealer_lat=?, dealer_lng=?, gps_distance_m=? "
        "WHERE id=?",
        (dealer_id, lat, lng, round(d, 1), request_id),
    )
    return get_request(conn, request_id)


# ---------- Step 3: dealer weighs on the scale ----------

def weigh_request(conn, request_id: int, *, dealer_id: int, mode: str = "normal") -> dict:
    req = get_request(conn, request_id)
    if req["dealer_id"] != dealer_id:
        raise ApiError(403, "This request was accepted by another dealer")
    if req["status"] not in ("accepted", "weighed"):
        raise ApiError(409, f"Cannot weigh a request that is {req['status']}")
    dealer = one(conn.execute("SELECT * FROM dealers WHERE id = ?", (dealer_id,)))
    reading = adapters.scale.read(dealer["scale_id"], req["est_kg"], mode)
    if reading.kg <= 0:
        raise ApiError(400, "Scale returned no weight — put the scrap on the scale")
    conn.execute(
        "UPDATE sale_requests SET status='weighed', scale_kg=?, scale_source=? WHERE id=?",
        (reading.kg, reading.source, request_id),
    )
    req = get_request(conn, request_id)
    collector = one(conn.execute("SELECT equipment FROM collectors WHERE id = ?", (req["collector_id"],)))
    gap = fraud.check_weight_gap(conn, req, reading.kg)
    outlier = fraud.check_volume_outlier(conn, req, reading.kg, collector["equipment"])
    rate = material(conn, req["material"])["rate_per_kg"]
    return {
        "request": req,
        "scale_kg": reading.kg,
        "scale_source": reading.source,
        "rate_per_kg": rate,
        "amount": pay_amount(reading.kg, rate),
        "gap_pct": round(fraud.weight_gap(req["est_kg"], reading.kg) * 100, 1),
        "gap_warning": gap is not None,
        "flags": [f for f in ((gap or {}).get("flag_id"), outlier) if f],
    }


def pay_amount(kg: float, rate: float) -> int:
    return int(round(kg * rate))


# ---------- Step 4: dealer approves → UPI ----------

def approve_request(conn, request_id: int, *, dealer_id: int) -> dict:
    req = get_request(conn, request_id)
    if req["dealer_id"] != dealer_id:
        raise ApiError(403, "This request was accepted by another dealer")
    if req["status"] == "paying":
        p = one(conn.execute("SELECT * FROM payments WHERE request_id = ? ORDER BY id DESC", (request_id,)))
        return {"payment": p, "request": req}
    if req["status"] != "weighed":
        raise ApiError(409, "Weigh the scrap on the scale before paying")
    dealer = one(conn.execute("SELECT * FROM dealers WHERE id = ?", (dealer_id,)))
    collector = one(conn.execute("SELECT * FROM collectors WHERE id = ?", (req["collector_id"],)))
    amount = pay_amount(req["scale_kg"], material(conn, req["material"])["rate_per_kg"])
    init = adapters.payments.initiate(dealer["upi_vpa"], collector["upi_vpa"], amount)
    conn.execute(
        "INSERT INTO payments (request_id, amount, payer_vpa, payee_vpa, provider_ref, status, created_at) "
        "VALUES (?,?,?,?,?, 'pending', ?)",
        (request_id, amount, dealer["upi_vpa"], collector["upi_vpa"], init.provider_ref, clock.ts()),
    )
    conn.execute("UPDATE sale_requests SET status='paying' WHERE id=?", (request_id,))
    p = one(conn.execute("SELECT * FROM payments WHERE provider_ref = ?", (init.provider_ref,)))
    return {"payment": p, "request": get_request(conn, request_id)}


# ---------- Step 5: payment webhook → transaction, credits, message ----------

def payment_webhook(conn, provider_ref: str, status: str) -> dict:
    p = one(conn.execute("SELECT * FROM payments WHERE provider_ref = ?", (provider_ref,)))
    if not p:
        raise ApiError(404, "Unknown payment")
    if p["status"] != "pending":
        return {"payment": p, "duplicate": True}
    if status != "success":
        conn.execute("UPDATE payments SET status='failed' WHERE id=?", (p["id"],))
        conn.execute("UPDATE sale_requests SET status='weighed' WHERE id=?", (p["request_id"],))
        return {"payment": {**p, "status": "failed"}}

    conn.execute("UPDATE payments SET status='success' WHERE id=?", (p["id"],))
    req = get_request(conn, p["request_id"])
    tx = record_transaction(conn, req, amount=p["amount"], upi_ref=provider_ref,
                            payer_vpa=p["payer_vpa"], payee_vpa=p["payee_vpa"])
    return {"payment": {**p, "status": "success"}, "transaction": tx}


def settle_mock_payment(conn, request_id: int) -> None:
    """Stand-in for the provider's webhook when using the mock UPI adapter."""
    after = adapters.payments.settles_after_s
    if after is None:
        return
    cutoff = clock.ts(clock.now() - timedelta(seconds=after))
    for p in rows(conn.execute(
            "SELECT provider_ref FROM payments WHERE request_id = ? AND status = 'pending' AND created_at <= ?",
            (request_id, cutoff))):
        payment_webhook(conn, p["provider_ref"], "success")


def record_transaction(conn, req: dict, *, amount: float, upi_ref: str,
                       payer_vpa: str, payee_vpa: str, notify: bool = True) -> dict:
    m = material(conn, req["material"])
    credits = int(round(req["scale_kg"] * CREDITS_PER_KG))
    batch_id = open_batch(conn, req["dealer_id"], req["material"])
    now = clock.ts()
    cur = conn.execute(
        "INSERT INTO transactions (request_id, collector_id, dealer_id, material, est_kg, scale_kg, "
        "rate_per_kg, amount, upi_ref, dealer_lat, dealer_lng, credits, batch_id, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (req["id"], req["collector_id"], req["dealer_id"], req["material"], req["est_kg"],
         req["scale_kg"], m["rate_per_kg"], amount, upi_ref, req["dealer_lat"], req["dealer_lng"],
         credits, batch_id, now),
    )
    conn.execute("UPDATE batches SET total_kg = total_kg + ? WHERE id = ?", (req["scale_kg"], batch_id))
    conn.execute("UPDATE collectors SET credits = credits + ? WHERE id = ?", (credits, req["collector_id"]))
    conn.execute("UPDATE sale_requests SET status='completed' WHERE id=?", (req["id"],))
    ev = conn.execute(
        "INSERT INTO upi_events (from_vpa, to_vpa, amount, upi_ref, at) VALUES (?,?,?,?,?)",
        (payer_vpa, payee_vpa, amount, upi_ref, now),
    )
    fraud.check_circular(conn, one(conn.execute("SELECT * FROM upi_events WHERE id=?", (ev.lastrowid,))))
    fraud.check_pair_frequency(conn, req["dealer_id"], req["collector_id"])

    if notify:
        c = one(conn.execute("SELECT * FROM collectors WHERE id = ?", (req["collector_id"],)))
        channel = "voice" if c["basic_phone"] else "whatsapp"
        adapters.messages.send(conn, c["id"], channel, c["language"],
                               confirmation_text(c["language"], amount, req["scale_kg"], m, credits),
                               meta={"kind": "sale_confirmation", "amount": int(round(amount)),
                                     "kg": req["scale_kg"], "material": m["code"], "credits": credits})
        score.recompute(conn, c["id"])
    return one(conn.execute("SELECT * FROM transactions WHERE id = ?", (cur.lastrowid,)))


def confirmation_text(lang: str, amount: float, kg: float, m: dict, credits: int) -> str:
    if lang == "hi":
        return (f"₹{amount:,.0f} मिले — {kg:g} किलो {m['label_hi']}। "
                f"आपके खाते में {credits} क्रेडिट जुड़ गए।")
    return f"₹{amount:,.0f} received for {kg:g} kg {m['label_en'].lower()}. {credits} credits added."


def open_batch(conn, dealer_id: int, material_code: str) -> int:
    b = conn.execute(
        "SELECT id FROM batches WHERE dealer_id = ? AND material = ? AND recycler_sale_id IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (dealer_id, material_code),
    ).fetchone()
    if b:
        return b[0]
    n = conn.execute("SELECT COUNT(*) FROM batches WHERE dealer_id = ?", (dealer_id,)).fetchone()[0] + 1
    code = f"WW-D{dealer_id:02d}-{material_code[:3].upper()}-{clock.now():%y%m%d}-{n:03d}"
    cur = conn.execute(
        "INSERT INTO batches (code, dealer_id, material, total_kg, created_at) VALUES (?,?,?,0,?)",
        (code, dealer_id, material_code, clock.ts()),
    )
    return cur.lastrowid


# ---------- Observed UPI transfers (aggregator feed) ----------

def observe_upi(conn, from_vpa: str, to_vpa: str, amount: float, upi_ref: str | None = None) -> dict:
    cur = conn.execute(
        "INSERT INTO upi_events (from_vpa, to_vpa, amount, upi_ref, at) VALUES (?,?,?,?,?)",
        (from_vpa, to_vpa, amount, upi_ref or adapters.new_upi_ref(), clock.ts()),
    )
    ev = one(conn.execute("SELECT * FROM upi_events WHERE id = ?", (cur.lastrowid,)))
    return {"event": ev, "flag_id": fraud.check_circular(conn, ev)}


# ---------- Basic-phone path (IVR) ----------

def ivr_start(conn, *, dealer_id: int, qr_token: str, material_code: str, est_kg: float) -> dict:
    c = one(conn.execute("SELECT * FROM collectors WHERE qr_token = ?", (qr_token,)))
    if not c:
        raise ApiError(404, "Unknown QR card")
    d = one(conn.execute("SELECT * FROM dealers WHERE id = ?", (dealer_id,)))
    m = material(conn, material_code)
    now = clock.now()
    cur = conn.execute(
        "INSERT INTO sale_requests (collector_id, dealer_id, material, est_kg, lat, lng, channel, status, "
        "dealer_lat, dealer_lng, gps_distance_m, created_at, expires_at) "
        "VALUES (?,?,?,?,?,?, 'ivr', 'awaiting_ivr', ?, ?, 0, ?, ?)",
        (c["id"], dealer_id, material_code, est_kg, d["lat"], d["lng"], d["lat"], d["lng"],
         clock.ts(now), clock.ts(now + timedelta(minutes=REQUEST_TTL_MIN))),
    )
    prompt = (f"{d['shop_name']} से {est_kg:g} किलो {m['label_hi']} की बिक्री। पुष्टि के लिए 1 दबाएँ।"
              if c["language"] == "hi" else
              f"Sale of {est_kg:g} kg {m['label_en'].lower()} to {d['shop_name']}. Press 1 to confirm.")
    adapters.messages.send(conn, c["id"], "ivr", c["language"], prompt)
    return {"request": get_request(conn, cur.lastrowid), "ivr_prompt": prompt, "calling": c["phone"]}


def ivr_confirm(conn, *, request_id: int, caller_phone: str, digit: str) -> dict:
    req = get_request(conn, request_id)
    if req["status"] != "awaiting_ivr":
        raise ApiError(409, f"Request is {req['status']}")
    c = one(conn.execute("SELECT phone FROM collectors WHERE id = ?", (req["collector_id"],)))
    if c["phone"] != caller_phone:
        raise ApiError(403, "Caller ID does not match the collector")
    status = "accepted" if digit == "1" else "rejected"
    conn.execute("UPDATE sale_requests SET status=?, reject_reason=? WHERE id=?",
                 (status, None if digit == "1" else "Collector declined on IVR", request_id))
    return get_request(conn, request_id)


# ---------- Recycler sales & mass balance ----------

def recycler_sale(conn, *, dealer_id: int, recycler_name: str, material_code: str,
                  kg: float, invoice_ref: str) -> dict:
    material(conn, material_code)
    if kg <= 0:
        raise ApiError(400, "Weight must be positive")
    cur = conn.execute(
        "INSERT INTO recycler_sales (dealer_id, recycler_name, material, kg, invoice_ref, sold_at) "
        "VALUES (?,?,?,?,?,?)",
        (dealer_id, recycler_name, material_code, kg, invoice_ref, clock.ts()),
    )
    sale_id = cur.lastrowid
    conn.execute(
        "UPDATE batches SET recycler_sale_id = ? WHERE dealer_id = ? AND material = ? AND recycler_sale_id IS NULL",
        (sale_id, dealer_id, material_code),
    )
    flag_id = fraud.check_mass_balance(conn, dealer_id)
    return {
        "sale": one(conn.execute("SELECT * FROM recycler_sales WHERE id = ?", (sale_id,))),
        "batches": rows(conn.execute("SELECT * FROM batches WHERE recycler_sale_id = ?", (sale_id,))),
        "mass_balance": fraud.mass_balance(conn, dealer_id),
        "flag_id": flag_id,
    }


# ---------- Loans (mirror of Satin's record) ----------

def disburse_starter_loan(conn, collector_id: int) -> dict:
    el = score.eligibility(conn, collector_id)
    if not el["eligible"]:
        failed = [c["label"] for c in el["checks"] if not c["ok"]]
        raise ApiError(409, "Not eligible: " + "; ".join(failed))
    c = one(conn.execute("SELECT group_id FROM collectors WHERE id = ?", (collector_id,)))
    cur = conn.execute(
        "INSERT INTO loans (collector_id, group_id, principal, tenure_m, status, disbursed_at) "
        "VALUES (?,?,?,?, 'active', ?)",
        (collector_id, c["group_id"], el["limit"], 6, clock.ts()),
    )
    return one(conn.execute("SELECT * FROM loans WHERE id = ?", (cur.lastrowid,)))


def new_qr_token() -> str:
    return "WWC-" + secrets.token_hex(4).upper()


def json_load(s: str | None):
    return json.loads(s) if s else None
