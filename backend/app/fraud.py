"""Fraud rules engine (Tech Spec). Each rule runs at the step it guards and either blocks
or writes a flag with a one-line reason. Thresholds are starting values to tune in the pilot."""
import json
import math
import statistics
from datetime import timedelta

import imagehash

from . import clock

DUP_PHOTO_MAX_DISTANCE = 6
DUP_PHOTO_WINDOW_DAYS = 30
GPS_MAX_DISTANCE_M = 50
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

def find_duplicate_photo(conn, phash: str) -> dict | None:
    new = imagehash.hex_to_hash(phash)
    since = clock.ago(days=DUP_PHOTO_WINDOW_DAYS)
    best = None
    for r in conn.execute(
        "SELECT id, collector_id, photo_phash, created_at FROM sale_requests "
        "WHERE photo_phash IS NOT NULL AND created_at >= ?",
        (since,),
    ):
        d = new - imagehash.hex_to_hash(r["photo_phash"])
        if d <= DUP_PHOTO_MAX_DISTANCE and (best is None or d < best["distance"]):
            best = {"request_id": r["id"], "collector_id": r["collector_id"],
                    "distance": int(d), "created_at": r["created_at"]}
    return best


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


RULE_LABELS = {
    "duplicate_photo": "Duplicate photo",
    "location_mismatch": "Location mismatch",
    "weight_gap": "Weight gap",
    "volume_outlier": "Volume outlier",
    "circular_payment": "Circular payment",
    "pair_frequency": "Pair frequency",
    "mass_balance": "Mass balance",
}
