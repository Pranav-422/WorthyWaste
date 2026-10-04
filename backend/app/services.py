"""Transaction flow: request → accept → weigh → approve → payment webhook → transaction.
A sale becomes a transaction only once payment succeeds."""
import json
import logging
import secrets
import uuid
from datetime import timedelta


from . import adapters, auth, clock, fraud, phash, score
from .db import one, rows

log = logging.getLogger("worthywaste.services")

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


def dealer_request(conn, request_id: int, dealer_id: int) -> dict:
    """A request as its chosen dealer sees it.

    A sale is between one collector and one dealer, so any other dealer gets the same answer as for
    a request that does not exist. 403 would tell them that Meena has a sale running somewhere."""
    req = get_request(conn, request_id)
    if req["dealer_id"] != dealer_id:
        raise ApiError(404, "Request not found")
    return req


def set_shop_location(conn, dealer_id: int, lat: float, lng: float, accuracy_m: float | None) -> dict:
    """The dealer pins their shop from their phone, standing at the shop. This is what collectors'
    "nearby shops" list is measured from."""
    if accuracy_m is not None and accuracy_m > fraud.SHOP_LOCATION_MAX_ACCURACY_M:
        raise ApiError(400, f"GPS is only accurate to about {accuracy_m:,.0f} m. Stand at the shop with a clear "
                            f"view of the sky and try again.", rule="gps_inaccurate",
                       evidence={"accuracy_m": round(accuracy_m)})
    if abs(lat) < 0.0001 and abs(lng) < 0.0001:
        raise ApiError(400, "That location looks empty (0, 0). Turn on GPS and try again.")
    now = clock.ts()
    conn.execute("UPDATE dealers SET lat = ?, lng = ?, location_set_at = ? WHERE id = ?", (lat, lng, now, dealer_id))
    return {"lat": lat, "lng": lng, "location_set_at": now}


def nearby_dealers(conn, collector_id: int, lat: float, lng: float) -> list[dict]:
    """Shops the collector could walk to, nearest first. Shop name and distance only: a collector
    picking a shop has no business knowing its phone number or where its money goes."""
    last = one(conn.execute(
        "SELECT dealer_id FROM transactions WHERE collector_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (collector_id,)))
    last_used = last["dealer_id"] if last else None
    out = []
    for d in rows(conn.execute("SELECT id, shop_name, lat, lng FROM dealers ORDER BY id")):
        distance = fraud.haversine_m(lat, lng, d["lat"], d["lng"])
        if distance > fraud.DEALER_CHOICE_MAX_M:
            continue
        out.append({"id": d["id"], "shop_name": d["shop_name"], "distance_m": round(distance),
                    "last_used": d["id"] == last_used})
    out.sort(key=lambda r: r["distance_m"])
    return out


def material(conn, code: str) -> dict:
    m = one(conn.execute("SELECT * FROM materials WHERE code = ?", (code,)))
    if not m:
        raise ApiError(400, f"Unknown material '{code}'")
    return m


def photo_phash(data: bytes) -> str:
    return phash.phash(data)


def photo_hash_or_400(data: bytes) -> str:
    try:
        return photo_phash(data)
    except Exception:
        raise ApiError(400, "Photo could not be read")


def refuse_duplicate_photo(conn, collector_id: int, phash_hex: str) -> None:
    """Refuse a photo already used in the last 30 days, and record the attempt for Satin."""
    dup = fraud.find_duplicate_photo(conn, phash_hex)
    if not dup:
        return
    same = dup["collector_id"] == collector_id
    flag = lambda c: fraud.raise_flag(  # noqa: E731
        c, entity_type="collector", entity_id=collector_id, rule="duplicate_photo",
        detail=("Reused a photo from" if same else "Used another collector's photo from")
               + f" request #{dup['request_id']} (hash distance {dup['distance']})",
        evidence=dup, collector_id=collector_id, dedupe_hours=1,
    )
    raise ApiError(409, "This photo was already used", rule="duplicate_photo", evidence=dup, persist=[flag])


# ---------- Step 1: collector raises a request ----------

def verify_photo(selected_material: str, jpeg: bytes) -> dict:
    """Ask the photo verifier whether the photo shows what the collector selected. Any failure comes
    back as the 'unchecked' verdict: the AI is an extra pair of eyes, never a gate."""
    try:
        check = adapters.photo_verifier.check(jpeg, selected_material)
    except Exception as e:  # a broken adapter must not cost the collector their sale
        reason = f"{type(e).__name__}: {e}"
        adapters.record_photo_check(error=reason)
        log.warning("photo check adapter raised: %s", reason)
        check = adapters.PhotoCheck.unavailable(f"Photo check failed ({type(e).__name__})")
    return fraud.photo_verdict(selected_material, check)


def check_photo(material_code: str, photo: bytes, demo_ai_material: str | None = None) -> tuple[bytes, dict]:
    """Re-encode the photo and run the photo check. Needs no database, so the API runs it before taking
    a connection: the verifier is a network call that can take seconds.

    Re-encoding comes first because Pillow writes pixels only, so EXIF (including the GPS tags phones
    embed) is gone, both from what we send the verifier and from what we store."""
    try:
        clean = adapters.reencode_jpeg(photo)
    except Exception:
        raise ApiError(400, "Photo could not be read")
    if demo_ai_material and auth.demo_mode():
        # Demo only: script what the photo check "saw", so the mismatch warning can be shown on stage
        # without hunting for a photo the real model gets wrong.
        ai = fraud.photo_verdict(material_code, adapters.PhotoCheck(
            available=True, material=demo_ai_material, confidence=0.87, real_scene=True,
            approx_quantity="one full sack", notes="Scripted demo photo check"))
    else:
        ai = verify_photo(material_code, clean)
    return clean, ai


def create_request(conn, *, collector_id: int, material_code: str, est_kg: float,
                   lat: float | None, lng: float | None, photo: bytes, dealer_id: int,
                   confirm_mismatch: bool = False, demo_ai_material: str | None = None,
                   checked: tuple[bytes, dict] | None = None) -> dict:
    """`checked` is check_photo()'s result when the caller already ran it outside the transaction."""
    c = one(conn.execute("SELECT * FROM collectors WHERE id = ?", (collector_id,)))
    if not c:
        raise ApiError(404, "Collector not found")
    m = material(conn, material_code)
    if not (0 < est_kg <= 500):
        raise ApiError(400, "Estimated weight must be between 0 and 500 kg")
    # The collector picks the shop, so the request is private to the two of them from the start.
    d = one(conn.execute("SELECT id, shop_name, lat, lng FROM dealers WHERE id = ?", (dealer_id,)))
    if not d:
        raise ApiError(404, "That shop is not registered")
    if lat is None or lng is None:
        raise ApiError(400, "Location needed to pick a shop — turn on GPS and try again",
                       rule="location_missing")
    distance = fraud.haversine_m(lat, lng, d["lat"], d["lng"])
    if distance > fraud.DEALER_CHOICE_MAX_M:
        raise ApiError(403, f"{d['shop_name']} is {distance / 1000:,.1f} km away — pick a shop within "
                            f"{fraud.DEALER_CHOICE_MAX_M // 1000} km",
                       rule="dealer_too_far", evidence={"distance_m": round(distance)})
    phash_hex = photo_hash_or_400(photo)
    refuse_duplicate_photo(conn, collector_id, phash_hex)

    clean, ai = checked or check_photo(material_code, photo, demo_ai_material)

    if ai["verdict"] == "mismatch" and not confirm_mismatch:
        # Warn once, don't refuse: the collector can fix the material or send it anyway.
        raise ApiError(409, "This photo may not match the scrap you chose", rule="photo_mismatch",
                       evidence={"chose": material_code, "chose_label_hi": m["label_hi"],
                                 "chose_label_en": m["label_en"], **ai})

    name = f"{uuid.uuid4().hex}.jpg"
    conn.execute("INSERT INTO photos (name, data, created_at) VALUES (?,?,?)", (name, clean, clock.ts()))
    now = clock.now()
    cur = conn.execute(
        "INSERT INTO sale_requests (collector_id, dealer_id, material, est_kg, photo_url, photo_phash, "
        "lat, lng, ai_material, ai_confidence, ai_verdict, ai_notes, ai_real_scene, "
        "status, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'open', ?, ?)",
        (collector_id, dealer_id, material_code, est_kg, f"/api/photos/{name}", phash_hex, lat, lng,
         ai["material"], ai["confidence"], ai["verdict"], ai["notes"],
         None if ai["real_scene"] is None else int(ai["real_scene"]),
         clock.ts(now), clock.ts(now + timedelta(minutes=REQUEST_TTL_MIN))),
    )
    req = get_request(conn, cur.lastrowid)
    if ai["verdict"] == "mismatch":
        # Recorded on the request either way; only a pattern of them becomes a flag.
        fraud.check_photo_mismatch(conn, req)
    return req


# ---------- Step 2: dealer scans QR and accepts ----------

def accept_request(conn, request_id: int, *, dealer_id: int, qr_token: str,
                   lat: float, lng: float) -> dict:
    req = dealer_request(conn, request_id, dealer_id)
    if req["status"] == "expired":
        raise ApiError(410, "Request expired — ask the collector to send a new one", rule="request_expiry")
    if req["status"] == "cancelled":
        raise ApiError(409, "The collector cancelled this request")
    if req["status"] != "open":
        raise ApiError(409, f"Request is already {req['status']}")
    c = one(conn.execute("SELECT * FROM collectors WHERE id = ?", (req["collector_id"],)))
    if c["qr_token"] != qr_token:
        raise ApiError(403, "QR card does not belong to this request's collector", rule="qr_mismatch")
    try:
        d = fraud.check_location(req, lat, lng)
    except fraud.Blocked as b:
        raise ApiError(403, b.message, rule=b.rule, evidence=b.evidence)
    # Guarded update, not just the check above: two dealer phones (or two serverless instances) can
    # reach this line at the same time, and only the one that still sees 'open' may take the request.
    cur = conn.execute(
        "UPDATE sale_requests SET status='accepted', dealer_lat=?, dealer_lng=?, gps_distance_m=? "
        "WHERE id=? AND status='open'",
        (lat, lng, round(d, 1), request_id),
    )
    if cur.rowcount == 0:
        raise ApiError(409, f"This request is already {get_request(conn, request_id)['status']}")
    return get_request(conn, request_id)


# ---------- Step 3: dealer weighs on the scale ----------

def weigh_request(conn, request_id: int, *, dealer_id: int, mode: str = "normal") -> dict:
    if mode != "normal" and not auth.demo_mode():
        raise ApiError(403, "Scale simulation modes are only available in demo mode")
    req = dealer_request(conn, request_id, dealer_id)
    if req["status"] not in ("accepted", "weighed"):
        raise ApiError(409, f"Cannot weigh a request that is {req['status']}")
    dealer = one(conn.execute("SELECT * FROM dealers WHERE id = ?", (dealer_id,)))
    reading = adapters.scale.read(dealer["scale_id"], req["est_kg"], mode)
    if reading.kg <= 0:
        raise ApiError(400, "Scale returned no weight — put the scrap on the scale")
    # Re-weighing is allowed, paying is not: once the request has moved on, this update finds no row.
    cur = conn.execute(
        "UPDATE sale_requests SET status='weighed', scale_kg=?, scale_source=? "
        "WHERE id=? AND status IN ('accepted','weighed')",
        (reading.kg, reading.source, request_id),
    )
    if cur.rowcount == 0:
        raise ApiError(409, f"Cannot weigh a request that is {get_request(conn, request_id)['status']}")
    req = get_request(conn, request_id)
    collector = one(conn.execute("SELECT equipment FROM collectors WHERE id = ?", (req["collector_id"],)))
    gap = fraud.check_weight_gap(conn, req, reading.kg)
    outlier = fraud.check_volume_outlier(conn, req, reading.kg, collector["equipment"])
    rate = material(conn, req["material"])["rate_per_kg"]
    return {
        "request": req,
        "material": req["material"],   # the collector's choice; the dealer confirms it before paying
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

def approve_request(conn, request_id: int, *, dealer_id: int, dealer_material: str | None = None) -> dict:
    """`dealer_material` is what the dealer confirmed with the scrap in front of them. It decides the
    rate, so the amount paid, the credits' batch and the traceable record all follow the dealer."""
    req = dealer_request(conn, request_id, dealer_id)
    if req["status"] == "paying":
        # A repeat tap on "Approve and pay": show the payment already running, never start a second.
        p = one(conn.execute("SELECT * FROM payments WHERE request_id = ? ORDER BY id DESC", (request_id,)))
        return {"payment": p, "request": req}
    if req["status"] != "weighed":
        raise ApiError(409, "Weigh the scrap on the scale before paying")
    confirmed = dealer_material or req["dealer_material"] or req["material"]
    m = material(conn, confirmed)
    # Claim the request before initiating payment: if this finds no row another instance already has
    # it, and we must not ask the aggregator for a second transfer.
    cur = conn.execute("UPDATE sale_requests SET status='paying', dealer_material=? "
                       "WHERE id=? AND status='weighed'", (confirmed, request_id))
    if cur.rowcount == 0:
        raise ApiError(409, f"This sale is already {get_request(conn, request_id)['status']}")
    dealer = one(conn.execute("SELECT * FROM dealers WHERE id = ?", (dealer_id,)))
    collector = one(conn.execute("SELECT * FROM collectors WHERE id = ?", (req["collector_id"],)))
    amount = pay_amount(req["scale_kg"], m["rate_per_kg"])
    init = adapters.payments.initiate(dealer["upi_vpa"], collector["upi_vpa"], amount)
    conn.execute(
        "INSERT INTO payments (request_id, amount, payer_vpa, payee_vpa, provider_ref, status, created_at) "
        "VALUES (?,?,?,?,?, 'pending', ?)",
        (request_id, amount, dealer["upi_vpa"], collector["upi_vpa"], init.provider_ref, clock.ts()),
    )
    p = one(conn.execute("SELECT * FROM payments WHERE provider_ref = ?", (init.provider_ref,)))
    return {"payment": p, "request": get_request(conn, request_id)}


# ---------- Step 5: payment webhook → transaction, credits, message ----------

def payment_webhook(conn, provider_ref: str, status: str) -> dict:
    """Providers retry webhooks, and two instances can be told about the same payment at once. The
    status change is the guard: whoever moves the row off 'pending' is the one that books the sale."""
    p = one(conn.execute("SELECT * FROM payments WHERE provider_ref = ?", (provider_ref,)))
    if not p:
        raise ApiError(404, "Unknown payment")
    if status != "success":
        cur = conn.execute("UPDATE payments SET status='failed' WHERE provider_ref=? AND status='pending'",
                           (provider_ref,))
        if cur.rowcount == 0:
            return {"payment": p, "duplicate": True}
        conn.execute("UPDATE sale_requests SET status='weighed' WHERE id=? AND status='paying'",
                     (p["request_id"],))
        return {"payment": {**p, "status": "failed"}}

    cur = conn.execute("UPDATE payments SET status='success' WHERE provider_ref=? AND status='pending'",
                       (provider_ref,))
    if cur.rowcount == 0:
        return {"payment": p, "duplicate": True}
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
    # The dealer confirmed the material at the scale; that is what was actually bought and traced.
    confirmed = req.get("dealer_material") or req["material"]
    m = material(conn, confirmed)
    credits = int(round(req["scale_kg"] * CREDITS_PER_KG))
    batch_id = open_batch(conn, req["dealer_id"], confirmed)
    now = clock.ts()
    cur = conn.execute(
        "INSERT INTO transactions (request_id, collector_id, dealer_id, material, est_kg, scale_kg, "
        "rate_per_kg, amount, upi_ref, dealer_lat, dealer_lng, credits, batch_id, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (req["id"], req["collector_id"], req["dealer_id"], confirmed, req["est_kg"],
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
    if req.get("dealer_material"):
        # A human looked at the scrap and called it something else: worth Satin's review.
        fraud.check_material_override(conn, req, req["dealer_material"])

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


def cancel_request(conn, request_id: int, *, collector_id: int) -> dict:
    """The collector changed their mind, or walked to a different shop. Only while nobody has acted
    on it: once a dealer has accepted, the two of them are standing together and sort it out there."""
    req = get_request(conn, request_id)
    if req["collector_id"] != collector_id:
        raise ApiError(404, "Request not found")
    cur = conn.execute(
        "UPDATE sale_requests SET status='cancelled', reject_reason=? WHERE id=? AND status='open'",
        ("Cancelled by the collector", request_id))
    if cur.rowcount == 0:
        raise ApiError(409, f"Cannot cancel a request that is {get_request(conn, request_id)['status']}")
    return get_request(conn, request_id)


def collector_requests(conn, collector_id: int, limit: int = 20) -> list[dict]:
    """The collector's own sales, in flight and recent, with the shop and the amount once paid."""
    expire_stale(conn)
    return rows(conn.execute(
        "SELECT r.id, r.material, r.est_kg, r.scale_kg, r.status, r.created_at, r.expires_at, "
        "r.dealer_material, r.ai_verdict, r.ai_material, r.photo_url, "
        "d.shop_name, m.label_en, m.label_hi, t.amount, t.credits "
        "FROM sale_requests r "
        "LEFT JOIN dealers d ON d.id = r.dealer_id "
        "JOIN materials m ON m.code = r.material "
        "LEFT JOIN transactions t ON t.request_id = r.id "
        "WHERE r.collector_id = ? ORDER BY r.id DESC LIMIT ?", (collector_id, limit)))


def ivr_confirm(conn, *, request_id: int, caller_phone: str, digit: str) -> dict:
    req = get_request(conn, request_id)
    if req["status"] != "awaiting_ivr":
        raise ApiError(409, f"Request is {req['status']}")
    c = one(conn.execute("SELECT phone FROM collectors WHERE id = ?", (req["collector_id"],)))
    if c["phone"] != caller_phone:
        raise ApiError(403, "Caller ID does not match the collector")
    status = "accepted" if digit == "1" else "rejected"
    # One keypress decides: a repeated or replayed IVR callback finds no awaiting_ivr row.
    cur = conn.execute("UPDATE sale_requests SET status=?, reject_reason=? WHERE id=? AND status='awaiting_ivr'",
                       (status, None if digit == "1" else "Collector declined on IVR", request_id))
    if cur.rowcount == 0:
        raise ApiError(409, f"Request is {get_request(conn, request_id)['status']}")
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
