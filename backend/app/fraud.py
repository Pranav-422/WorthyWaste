"""Fraud rules engine (Tech Spec). Each rule runs at the step it guards and either blocks
or writes a flag with a one-line reason. Thresholds are starting values to tune in the pilot."""
import json
import math
import statistics
from datetime import timedelta


from . import clock, phash

DUP_PHOTO_MAX_DISTANCE = 6
DUP_PHOTO_WINDOW_DAYS = 30
GPS_MAX_DISTANCE_M = 50
# How far a collector may be from the shop they pick. Wider than GPS_MAX_DISTANCE_M on purpose: at
# this point they are choosing where to walk to, not standing at the scale.
DEALER_CHOICE_MAX_M = 5000
# The shop pin only decides which shops a collector sees within DEALER_CHOICE_MAX_M (5 km). The 50 m
# "standing together" check uses both phones' live GPS at accept time, not this pin. So a coarse fix is
# fine here; a laptop's Wi-Fi location (often ±150–300 m) has to be accepted.
SHOP_LOCATION_MAX_ACCURACY_M = 1000
WEIGHT_GAP_PCT = 0.10
WEIGHT_GAP_REPEATS = 3
WEIGHT_GAP_WINDOW_DAYS = 7
DAILY_KG_CAP = {"hand_cart": 150, "cycle_rickshaw": 300, "sack": 60}
CIRCULAR_WINDOW_H = 48
PAIR_FREQ_MULTIPLE = 3
PAIR_FREQ_MIN_COUNT = 6
PAIR_FREQ_MIN_COLLECTORS = 5  # need a real pattern before calling a pair unusual
MASS_BALANCE_WINDOW_DAYS = 30
MASS_BALANCE_GAP = 0.15
MASS_BALANCE_MIN_KG = 500  # too little volume and normal stock lag looks like a gap
PHOTO_MATCH_CONFIDENCE = 0.80
PHOTO_MISMATCH_REPEATS = 3
PHOTO_MISMATCH_WINDOW_DAYS = 7
# Door-to-door pickups (Phase 2).
PICKUP_GPS_MAX_M = 50          # collector's phone vs the home's registered location
PICKUP_BURST_MAX = 25          # more doors than this in PICKUP_BURST_WINDOW_MIN is not a real round
PICKUP_BURST_WINDOW_MIN = 5
PICKUP_DISPUTE_REPEATS = 3     # households saying "no pickup today" this often in a week is a pattern
PICKUP_DISPUTE_WINDOW_DAYS = 7


class Blocked(Exception):
    def __init__(self, rule: str, message: str, evidence: dict | None = None):
        super().__init__(message)
        self.rule = rule
        self.message = message
        self.evidence = evidence or {}


def raise_flag(conn, *, entity_type, entity_id, rule, detail, evidence=None,
               collector_id=None, dealer_id=None, dedupe_hours=24) -> int | None:
    """Write a flag unless an identical open one was raised recently."""
    dup = conn.execute(
        "SELECT id FROM fraud_flags WHERE rule = ? AND entity_type = ? AND entity_id = ? "
        "AND status = 'open' AND created_at >= ?",
        (rule, entity_type, entity_id, clock.ago(hours=dedupe_hours)),
    ).fetchone()
    if dup:
        return None
    cur = conn.execute(
        "INSERT INTO fraud_flags (entity_type, entity_id, rule, detail, evidence_json, "
        "collector_id, dealer_id, status, created_at) VALUES (?,?,?,?,?,?,?, 'open', ?)",
        (entity_type, entity_id, rule, detail, json.dumps(evidence or {}),
         collector_id, dealer_id, clock.ts()),
    )
    return cur.lastrowid


# ---------- Duplicate photo (at POST /requests) ----------

def find_duplicate_photo(conn, new_hash: str) -> dict | None:
    since = clock.ago(days=DUP_PHOTO_WINDOW_DAYS)
    best = None
    for r in conn.execute(
        "SELECT id, collector_id, photo_phash, created_at FROM sale_requests "
        "WHERE photo_phash IS NOT NULL AND created_at >= ?",
        (since,),
    ):
        d = phash.distance(new_hash, r["photo_phash"])
        if d <= DUP_PHOTO_MAX_DISTANCE and (best is None or d < best["distance"]):
            best = {"request_id": r["id"], "collector_id": r["collector_id"],
                    "distance": int(d), "created_at": r["created_at"]}
    return best


# ---------- Photo vs selected material (at POST /requests, and again when the dealer confirms) ----------

def photo_verdict(selected: str, check) -> dict:
    """Turn a PhotoVerifier answer into one of four verdicts. An AI guess never blocks a sale on its
    own: the worst it can do is 'mismatch', which warns the collector and is shown to the dealer."""
    if not check.available:
        return {"verdict": "unchecked", "material": None, "confidence": None, "real_scene": None,
                "notes": check.notes}
    seen, conf = check.material, check.confidence or 0.0
    if seen == "not_scrap" or check.real_scene is False:
        verdict = "mismatch"
    elif conf < PHOTO_MATCH_CONFIDENCE or seen == "mixed":
        # Not sure enough to say either way — includes a genuinely mixed load.
        verdict = "uncertain"
    elif seen == selected:
        verdict = "match"
    else:
        verdict = "mismatch"
    notes = check.notes
    if check.approx_quantity:
        notes = f"{notes} ({check.approx_quantity})" if notes else f"About {check.approx_quantity}"
    return {"verdict": verdict, "material": seen, "confidence": round(conf, 2),
            "real_scene": check.real_scene, "notes": notes}


def count_photo_mismatches(conn, collector_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM sale_requests WHERE collector_id = ? AND ai_verdict = 'mismatch' "
        "AND created_at >= ?",
        (collector_id, clock.ago(days=PHOTO_MISMATCH_WINDOW_DAYS)),
    ).fetchone()[0]


def check_photo_mismatch(conn, req: dict) -> int | None:
    """One mismatch is only recorded on the request. Three in a week is a pattern worth Satin's time,
    so it becomes a holding flag (see score.HOLDING_RULES)."""
    repeats = count_photo_mismatches(conn, req["collector_id"])
    if repeats < PHOTO_MISMATCH_REPEATS:
        return None
    return raise_flag(
        conn, entity_type="collector", entity_id=req["collector_id"], rule="photo_mismatch",
        detail=f"Photo did not match the material chosen on {repeats} sales in "
               f"{PHOTO_MISMATCH_WINDOW_DAYS} days (latest: chose {req['material']}, "
               f"photo looked like {req['ai_material'] or 'something else'})",
        evidence={"repeats": repeats, "request_id": req["id"], "chose": req["material"],
                  "ai_material": req["ai_material"], "ai_confidence": req["ai_confidence"],
                  "ai_verdict": req["ai_verdict"], "ai_notes": req["ai_notes"],
                  "ai_real_scene": req["ai_real_scene"], "photo_url": req["photo_url"]},
        collector_id=req["collector_id"], dedupe_hours=24,
    )


def check_material_override(conn, req: dict, dealer_material: str) -> int | None:
    """The dealer had the scrap in their hands and confirmed a different material than the collector
    chose. That is a human saying the listing was wrong, so it flags on the first occurrence."""
    if dealer_material == req["material"]:
        return None
    return raise_flag(
        # Flagged against the request, so each disputed sale gets its own card for Satin.
        conn, entity_type="request", entity_id=req["id"], rule="photo_mismatch",
        detail=f"Dealer weighed this load as {dealer_material}, not the {req['material']} the "
               f"collector chose (request #{req['id']})",
        evidence={"request_id": req["id"], "chose": req["material"], "dealer_material": dealer_material,
                  "ai_material": req["ai_material"], "ai_confidence": req["ai_confidence"],
                  "ai_verdict": req["ai_verdict"], "ai_notes": req["ai_notes"],
                  "ai_real_scene": req["ai_real_scene"], "photo_url": req["photo_url"]},
        collector_id=req["collector_id"], dealer_id=req["dealer_id"],
    )


# ---------- Location (at /accept) ----------

def haversine_m(lat1, lng1, lat2, lng2) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def check_location(req: dict, dealer_lat: float, dealer_lng: float) -> float:
    if req["lat"] is None or req["lng"] is None:
        raise Blocked("location_mismatch", "Collector location missing — ask them to turn on GPS")
    d = haversine_m(req["lat"], req["lng"], dealer_lat, dealer_lng)
    if d > GPS_MAX_DISTANCE_M:
        raise Blocked("location_mismatch",
                      f"Phones are {d:,.0f} m apart (limit {GPS_MAX_DISTANCE_M} m). "
                      "Collector and dealer must be together.",
                      {"distance_m": round(d)})
    return d


# ---------- Weight gap + volume outlier (at /weigh) ----------

def weight_gap(est_kg: float, scale_kg: float) -> float:
    return abs(scale_kg - est_kg) / est_kg if est_kg else 0.0


def check_weight_gap(conn, req: dict, scale_kg: float) -> dict | None:
    gap = weight_gap(req["est_kg"], scale_kg)
    if gap <= WEIGHT_GAP_PCT:
        return None
    since = clock.ago(days=WEIGHT_GAP_WINDOW_DAYS)
    recent = conn.execute(
        "SELECT est_kg, scale_kg FROM sale_requests WHERE collector_id = ? AND scale_kg IS NOT NULL "
        "AND created_at >= ? AND id != ?",
        (req["collector_id"], since, req["id"]),
    ).fetchall()
    repeats = 1 + sum(1 for r in recent if weight_gap(r["est_kg"], r["scale_kg"]) > WEIGHT_GAP_PCT)
    flag_id = None
    if repeats >= WEIGHT_GAP_REPEATS:
        flag_id = raise_flag(
            conn, entity_type="collector", entity_id=req["collector_id"], rule="weight_gap",
            detail=f"Estimate off by more than 10% on {repeats} sales in 7 days "
                   f"(latest: said {req['est_kg']:g} kg, scale {scale_kg:g} kg)",
            evidence={"repeats": repeats, "request_id": req["id"],
                      "est_kg": req["est_kg"], "scale_kg": scale_kg},
            collector_id=req["collector_id"], dealer_id=req["dealer_id"],
        )
    return {"gap_pct": round(gap * 100, 1), "repeats_7d": repeats, "flag_id": flag_id}


def check_volume_outlier(conn, req: dict, scale_kg: float, equipment: str) -> int | None:
    cap = DAILY_KG_CAP.get(equipment, DAILY_KG_CAP["hand_cart"])
    day = clock.ts()[:10]
    today = conn.execute(
        "SELECT COALESCE(SUM(scale_kg), 0) FROM transactions "
        "WHERE collector_id = ? AND substr(created_at, 1, 10) = ?",
        (req["collector_id"], day),
    ).fetchone()[0]
    total = today + scale_kg
    if total <= cap:
        return None
    return raise_flag(
        conn, entity_type="collector", entity_id=req["collector_id"], rule="volume_outlier",
        detail=f"{total:,.0f} kg in one day — more than a {equipment.replace('_', ' ')} can carry ({cap} kg)",
        evidence={"day": day, "kg_today": round(total, 1), "cap_kg": cap},
        collector_id=req["collector_id"], dealer_id=req["dealer_id"],
    )


# ---------- Circular payment (at payment webhook and on observed UPI transfers) ----------

def check_circular(conn, event: dict) -> int | None:
    """event: a upi_events row. Flags when money a dealer paid a collector flows back to that
    dealer within 48 h, checked from whichever side of the pair arrives second."""
    window = timedelta(hours=CIRCULAR_WINDOW_H)
    at = clock.parse(event["at"])

    def party(vpa):
        c = conn.execute("SELECT id, name FROM collectors WHERE upi_vpa = ?", (vpa,)).fetchone()
        d = conn.execute("SELECT id, shop_name FROM dealers WHERE upi_vpa = ?", (vpa,)).fetchone()
        return c, d

    from_c, from_d = party(event["from_vpa"])
    to_c, to_d = party(event["to_vpa"])

    if from_c and to_d:
        # Collector → dealer: was there a dealer → collector payout in the 48 h before?
        payout = conn.execute(
            "SELECT * FROM upi_events WHERE from_vpa = ? AND to_vpa = ? AND at >= ? AND at <= ? "
            "ORDER BY at DESC LIMIT 1",
            (event["to_vpa"], event["from_vpa"], clock.ts(at - window), event["at"]),
        ).fetchone()
        back = event
        collector, dealer = from_c, to_d
    elif from_d and to_c:
        # Dealer → collector: did the collector already send money back (out-of-order feed)?
        payout = event
        back = conn.execute(
            "SELECT * FROM upi_events WHERE from_vpa = ? AND to_vpa = ? AND at >= ? AND at <= ? "
            "ORDER BY at LIMIT 1",
            (event["to_vpa"], event["from_vpa"], event["at"], clock.ts(at + window)),
        ).fetchone()
        collector, dealer = to_c, from_d
    else:
        return None
    if not payout or not back:
        return None
    payout, back = dict(payout), dict(back)
    hours = (clock.parse(back["at"]) - clock.parse(payout["at"])).total_seconds() / 3600
    when = f"{hours:.0f} h" if hours >= 1 else f"{hours * 60:.0f} min"
    detail = (f"Circular payment: ₹{back['amount']:,.0f} returned to {dealer['shop_name']} "
              f"within {when} of a ₹{payout['amount']:,.0f} payout to {collector['name']}")
    evidence = {"payout": payout, "return": back, "hours": round(hours, 2)}
    # One flag naming both parties; confirming it freezes the collector and docks the dealer.
    return raise_flag(conn, entity_type="collector", entity_id=collector["id"], rule="circular_payment",
                      detail=detail, evidence=evidence,
                      collector_id=collector["id"], dealer_id=dealer["id"])


# ---------- Pair frequency (after a transaction) ----------

def check_pair_frequency(conn, dealer_id: int, collector_id: int) -> int | None:
    since = clock.ago(days=30)
    counts = {r["collector_id"]: r["n"] for r in conn.execute(
        "SELECT collector_id, COUNT(*) n FROM transactions WHERE dealer_id = ? AND created_at >= ? "
        "GROUP BY collector_id", (dealer_id, since))}
    n = counts.get(collector_id, 0)
    if len(counts) < PAIR_FREQ_MIN_COLLECTORS or n < PAIR_FREQ_MIN_COUNT:
        return None
    median = statistics.median(counts.values())
    if n <= PAIR_FREQ_MULTIPLE * median:
        return None
    return raise_flag(
        conn, entity_type="collector", entity_id=collector_id, rule="pair_frequency",
        detail=f"{n} sales to the same dealer in 30 days — {n / median:.1f}× that dealer's "
               f"usual {median:g} per collector",
        evidence={"pair_count": n, "dealer_median": median},
        collector_id=collector_id, dealer_id=dealer_id, dedupe_hours=24 * 7,
    )


# ---------- Mass balance (at POST /recycler-sales) ----------

def mass_balance(conn, dealer_id: int) -> dict:
    since = clock.ago(days=MASS_BALANCE_WINDOW_DAYS)
    bought = conn.execute(
        "SELECT COALESCE(SUM(scale_kg),0) FROM transactions WHERE dealer_id = ? AND created_at >= ?",
        (dealer_id, since)).fetchone()[0]
    sold = conn.execute(
        "SELECT COALESCE(SUM(kg),0) FROM recycler_sales WHERE dealer_id = ? AND sold_at >= ?",
        (dealer_id, since)).fetchone()[0]
    gap = (bought - sold) / sold if sold else None
    return {"bought_kg": round(bought, 1), "sold_kg": round(sold, 1),
            "gap_pct": round(gap * 100, 1) if gap is not None else None}


def check_mass_balance(conn, dealer_id: int) -> int | None:
    mb = mass_balance(conn, dealer_id)
    if mb["gap_pct"] is None or mb["gap_pct"] <= MASS_BALANCE_GAP * 100 or mb["bought_kg"] < MASS_BALANCE_MIN_KG:
        return None
    shop = conn.execute("SELECT shop_name FROM dealers WHERE id = ?", (dealer_id,)).fetchone()[0]
    detail = (f"{shop} bought {mb['bought_kg']:,.0f} kg but sold only {mb['sold_kg']:,.0f} kg "
              f"to recyclers in 30 days ({mb['gap_pct']:.0f}% gap) — purchases may be inflated")
    # One open mass-balance flag per dealer, kept current, instead of a new one every sale.
    existing = conn.execute(
        "SELECT id FROM fraud_flags WHERE rule = 'mass_balance' AND dealer_id = ? AND status = 'open'",
        (dealer_id,)).fetchone()
    if existing:
        conn.execute("UPDATE fraud_flags SET detail = ?, evidence_json = ? WHERE id = ?",
                     (detail, json.dumps(mb), existing[0]))
        return existing[0]
    return raise_flag(conn, entity_type="dealer", entity_id=dealer_id, rule="mass_balance",
                      detail=detail, evidence=mb, dealer_id=dealer_id)


# ---------- Door-to-door pickups (Phase 2) ----------

def find_duplicate_pickup_photo(conn, new_hash: str) -> dict | None:
    """A door-to-door collector reusing one photo of separated waste for every door."""
    since = clock.ago(days=DUP_PHOTO_WINDOW_DAYS)
    best = None
    for r in conn.execute(
        "SELECT id, collector_id, photo_phash, created_at FROM pickups "
        "WHERE photo_phash IS NOT NULL AND created_at >= ?", (since,)):
        d = phash.distance(new_hash, r["photo_phash"])
        if d <= DUP_PHOTO_MAX_DISTANCE and (best is None or d < best["distance"]):
            best = {"pickup_id": r["id"], "collector_id": r["collector_id"],
                    "distance": int(d), "created_at": r["created_at"]}
    return best


def check_pickup_burst(conn, collector_id: int) -> int | None:
    """Scanning many doors in a few minutes means stickers are being scanned without the rounds."""
    n = conn.execute("SELECT COUNT(*) FROM pickups WHERE collector_id = ? AND created_at >= ?",
                     (collector_id, clock.ago(minutes=PICKUP_BURST_WINDOW_MIN))).fetchone()[0]
    if n <= PICKUP_BURST_MAX:
        return None
    return raise_flag(
        conn, entity_type="collector", entity_id=collector_id, rule="pickup_burst",
        detail=f"{n} doors scanned in {PICKUP_BURST_WINDOW_MIN} minutes (a real round manages at most "
               f"{PICKUP_BURST_MAX})",
        evidence={"doors": n, "window_min": PICKUP_BURST_WINDOW_MIN}, collector_id=collector_id,
        dedupe_hours=12)


def check_pickup_disputes(conn, collector_id: int) -> int | None:
    """One household saying "no pickup today" is recorded on the pickup. Three in a week is a pattern."""
    n = conn.execute("SELECT COUNT(*) FROM pickups WHERE collector_id = ? AND status = 'disputed' "
                     "AND disputed_at >= ?",
                     (collector_id, clock.ago(days=PICKUP_DISPUTE_WINDOW_DAYS))).fetchone()[0]
    if n < PICKUP_DISPUTE_REPEATS:
        return None
    return raise_flag(
        conn, entity_type="collector", entity_id=collector_id, rule="pickup_disputed",
        detail=f"Households reported {n} scanned pickups that did not happen in "
               f"{PICKUP_DISPUTE_WINDOW_DAYS} days",
        evidence={"disputes": n, "window_days": PICKUP_DISPUTE_WINDOW_DAYS}, collector_id=collector_id)


RULE_LABELS = {
    "duplicate_photo": "Duplicate photo",
    "location_mismatch": "Location mismatch",
    "weight_gap": "Weight gap",
    "volume_outlier": "Volume outlier",
    "circular_payment": "Circular payment",
    "pair_frequency": "Pair frequency",
    "mass_balance": "Mass balance",
    "photo_mismatch": "Photo mismatch",
    "pickup_burst": "Too many doors too fast",
    "pickup_disputed": "Pickups disputed by households",
}
