"""Phase 2: door-to-door collection, the household's Green Wallet and points.

A pickup is one scan of the QR on a home's door by the collector whose route it is on, standing at the
door (GPS), marked separated or mixed. Each pickup:

  * earns the household points if the waste was separated (more for a streak, capped per month),
  * owes the collector their fee, paid from the household's Green Wallet, and
  * adds a verified working day to the collector's record, which feeds the same score as Phase 1.

The Green Wallet is not money we hold. It is a UPI AutoPay mandate on the household's own bank
account, so no prepaid-wallet licence is needed. UPI AutoPay requires a pre-debit notice 24 hours
before each debit; the WhatsApp message sent at pickup is that notice, and it doubles as the
household's window to say "no pickup today" before any money moves. Per-pickup fees are therefore
debited the next day, monthly-plan fees once the month is over.

Fees, points and their rupee value are pilot assumptions.
"""
import calendar
import uuid
from datetime import date, timedelta

from . import adapters, clock, fraud, revenue, score
from .db import one, rows
from .services import ApiError

DEFAULT_FEE_PER_PICKUP = 5.0
DEFAULT_MONTHLY_FEE = 150.0
PLATFORM_FEE_PER_PICKUP = 0.5
PRE_DEBIT_NOTICE_H = 24
DISPUTE_WINDOW_H = 48

POINTS_SEPARATED = 5
STREAK_PICKUPS = 7            # every 7th separated pickup in a row earns the bonus
STREAK_BONUS = 20
MONTHLY_POINTS_CAP = 300
POINT_VALUE = 0.05            # ₹ per point: 100 points = ₹5 off the collection fee
REDEEM_STEP = 100
MANDATE_LIMIT_RANGE = (50, 5000)


# ---------- helpers ----------

def _month_start_utc() -> str:
    """Start of the current India calendar month, as a UTC timestamp."""
    ist = clock.now() + clock.IST
    return clock.ts(ist.replace(day=1, hour=0, minute=0, second=0) - clock.IST)


def _in(ids) -> str:
    return ",".join("?" * len(ids))


def household(conn, household_id: int) -> dict:
    h = one(conn.execute("SELECT * FROM households WHERE id = ?", (household_id,)))
    if not h:
        raise ApiError(404, "Household not found")
    return h


def _public(h: dict) -> dict:
    return {k: v for k, v in h.items() if k not in ("pin_hash",)}


def send(conn, h: dict, text: str) -> None:
    """WhatsApp to the household. Stored and shown in their app in the demo, like collectors' messages."""
    conn.execute("INSERT INTO household_messages (household_id, channel, language, text, created_at) "
                 "VALUES (?, 'whatsapp', ?, ?, ?)", (h["id"], h["language"], text, clock.ts()))


def money(x: float) -> str:
    return f"₹{x:,.2f}".replace(".00", "")


# ---------- the pickup ----------

def record_pickup(conn, *, collector_id: int, door_qr: str, segregation: str, lat: float | None,
                  lng: float | None, photo: tuple[bytes, str] | None = None, notify: bool = True) -> dict:
    """`photo` is (re-encoded JPEG, perceptual hash), prepared by the caller outside the transaction."""
    if segregation not in ("separated", "mixed"):
        raise ApiError(400, "Mark the waste as separated or mixed")
    c = one(conn.execute("SELECT id, name, kind FROM collectors WHERE id = ?", (collector_id,)))
    if not c or c["kind"] != "door_to_door":
        raise ApiError(403, "Only door-to-door collectors record pickups")
    h = one(conn.execute("SELECT * FROM households WHERE door_qr = ?", (door_qr.strip().upper(),)))
    if not h:
        raise ApiError(404, "This QR is not a registered door", rule="unknown_door")
    if h["collector_id"] != collector_id:
        raise ApiError(403, f"{h['name']} is on another collector's route", rule="not_on_route")
    if lat is None or lng is None:
        raise ApiError(400, "Location needed — turn on GPS and scan again", rule="location_missing")
    distance = fraud.haversine_m(lat, lng, h["lat"], h["lng"])
    if distance > fraud.PICKUP_GPS_MAX_M:
        raise ApiError(403, f"You are {distance:,.0f} m from {h['name']} (limit {fraud.PICKUP_GPS_MAX_M} m). "
                            "Scan the QR at the door.", rule="gps_far_from_home",
                       evidence={"distance_m": round(distance)})
    day = clock.ist_day()
    if one(conn.execute("SELECT id FROM pickups WHERE household_id = ? AND day = ?", (h["id"], day))):
        raise ApiError(409, f"{h['name']} was already picked up today", rule="already_picked_today")

    photo_url = phash_hex = None
    if photo is not None:
        clean, phash_hex = photo
        dup = fraud.find_duplicate_pickup_photo(conn, phash_hex)
        if dup:
            flag = lambda cn: fraud.raise_flag(  # noqa: E731
                cn, entity_type="collector", entity_id=collector_id, rule="duplicate_photo",
                detail=f"Reused a pickup photo from pickup #{dup['pickup_id']} (hash distance {dup['distance']})",
                evidence=dup, collector_id=collector_id, dedupe_hours=1)
            raise ApiError(409, "This photo was already used", rule="duplicate_photo", evidence=dup, persist=[flag])
        name = f"{uuid.uuid4().hex}.jpg"
        conn.execute("INSERT INTO photos (name, data, created_at) VALUES (?,?,?)", (name, clean, clock.ts()))
        photo_url = f"/api/photos/{name}"

    try:
        cur = conn.execute(
            "INSERT INTO pickups (household_id, collector_id, day, segregation, photo_url, photo_phash, lat, lng, "
            "distance_m, status, created_at) VALUES (?,?,?,?,?,?,?,?,?, 'done', ?)",
            (h["id"], collector_id, day, segregation, photo_url, phash_hex, lat, lng, round(distance, 1),
             clock.ts()))
    except Exception as e:  # the UNIQUE (household_id, day) guard, when two scans race
        if "unique" in str(e).lower():
            raise ApiError(409, f"{h['name']} was already picked up today", rule="already_picked_today")
        raise
    pickup_id = cur.lastrowid
    pts = _award_points(conn, h, pickup_id, day) if segregation == "separated" else 0
    fee = _new_fee(conn, h, collector_id, pickup_id, day)
    fraud.check_pickup_burst(conn, collector_id)
    if notify:
        _notify_pickup(conn, household(conn, h["id"]), c["name"], segregation, pts, fee)
        score.recompute(conn, collector_id)
    return {"pickup": one(conn.execute("SELECT * FROM pickups WHERE id = ?", (pickup_id,))),
            "fee": fee, "points": pts,
            "household": {"id": h["id"], "name": h["name"], "kind": h["kind"]}}


def streak(conn, household_id: int) -> int:
    """Separated pickups in a row, most recent first. Days without a pickup don't break it: the
    household can't help it if the collector took Sunday off."""
    n = 0
    for r in conn.execute("SELECT segregation FROM pickups WHERE household_id = ? AND status = 'done' "
                          "ORDER BY day DESC LIMIT 60", (household_id,)):
        if r["segregation"] != "separated":
            break
        n += 1
    return n


def _award_points(conn, h: dict, pickup_id: int, day: str) -> int:
    earned = conn.execute(
        "SELECT COALESCE(SUM(e.points),0) FROM points_events e JOIN pickups p ON p.id = e.pickup_id "
        "WHERE e.household_id = ? AND e.reason IN ('separated','streak') AND p.status = 'done' AND p.day >= ?",
        (h["id"], day[:7] + "-01")).fetchone()[0]
    want = [("separated", POINTS_SEPARATED)]
    if streak(conn, h["id"]) % STREAK_PICKUPS == 0:
        want.append(("streak", STREAK_BONUS))
    room = max(0, MONTHLY_POINTS_CAP - int(earned))
    total = 0
    for reason, pts in want:
        give = min(pts, room - total)
        if give <= 0:
            break
        conn.execute("INSERT INTO points_events (household_id, pickup_id, reason, points, created_at) "
                     "VALUES (?,?,?,?,?)", (h["id"], pickup_id, reason, give, clock.ts()))
        total += give
    if total:
        conn.execute("UPDATE households SET points = points + ? WHERE id = ?", (total, h["id"]))
        conn.execute("UPDATE pickups SET points = ? WHERE id = ?", (total, pickup_id))
    return total


def _new_fee(conn, h: dict, collector_id: int, pickup_id: int, day: str) -> dict:
    if h["fee_plan"] == "monthly":
        days_in_month = calendar.monthrange(int(day[:4]), int(day[5:7]))[1]
        fee = round(h["monthly_fee"] / days_in_month, 2)
    else:
        fee = h["fee_per_pickup"]
    cur = conn.execute(
        "INSERT INTO fee_payments (household_id, collector_id, pickup_id, day, plan, fee, platform_fee, status, "
        "created_at) VALUES (?,?,?,?,?,?,?, 'accrued', ?)",
        (h["id"], collector_id, pickup_id, day, h["fee_plan"], fee, PLATFORM_FEE_PER_PICKUP, clock.ts()))
    return one(conn.execute("SELECT * FROM fee_payments WHERE id = ?", (cur.lastrowid,)))


def _notify_pickup(conn, h: dict, collector_name: str, segregation: str, pts: int, fee: dict) -> None:
    first = collector_name.split()[0]
    amount = fee["fee"] + fee["platform_fee"]
    hi = h["language"] == "hi"
    if segregation == "separated":
        head = (f"आज आपका कचरा अलग मिला — +{pts} पॉइंट।" if hi else f"Your waste was separated today — +{pts} points.")
    else:
        head = ("आज कचरा मिला-जुला था, पॉइंट नहीं मिले। कल गीला-सूखा अलग रखें।" if hi
                else "Today's waste was mixed, so no points. Keep wet and dry apart tomorrow.")
    if fee["plan"] == "monthly":
        pay = (f"{money(amount)} इस महीने के बिल में जुड़े।" if hi else f"{money(amount)} added to this month's bill.")
    elif h["mandate_status"] != "active":
        pay = (f"{money(amount)} बाकी — Green Wallet में AutoPay चालू करें।" if hi
               else f"{money(amount)} due — turn on AutoPay in your Green Wallet.")
    else:
        pay = (f"{money(amount)} कल AutoPay से कटेंगे।" if hi else f"{money(amount)} will be debited by AutoPay tomorrow.")
    tail = (f"({first}, पिकअप #{fee['pickup_id']}) पिकअप नहीं हुआ? ऐप में बताएँ, पैसा नहीं कटेगा।" if hi
            else f"({first}, pickup #{fee['pickup_id']}) No pickup? Tell us in the app and nothing is charged.")
    send(conn, h, f"{head} {pay} {tail}")


# ---------- paying the collector ----------

def spent_this_month(conn, household_id: int) -> float:
    return conn.execute("SELECT COALESCE(SUM(debited),0) FROM fee_payments WHERE household_id = ? "
                        "AND status = 'paid' AND paid_at >= ?", (household_id, _month_start_utc())).fetchone()[0]


def charge(conn, household_id: int, payment_ids: list[int], *, book_fee: bool = True) -> dict:
    """Pay these fees: redeemed-points credit first, then one AutoPay debit for the rest.

    All or nothing: if the mandate is missing or the debit would cross its monthly limit, the fees
    stay 'due' and the household sees one clear amount to settle."""
    if not payment_ids:
        return {"paid": 0, "due": 0, "debited": 0.0, "credit_used": 0.0}
    h = household(conn, household_id)
    fees = rows(conn.execute(f"SELECT * FROM fee_payments WHERE id IN ({_in(payment_ids)}) "
                             "AND status IN ('accrued','due') ORDER BY id", payment_ids))
    if not fees:
        return {"paid": 0, "due": 0, "debited": 0.0, "credit_used": 0.0}
    total = round(sum(f["fee"] + f["platform_fee"] for f in fees), 2)
    credit = round(min(h["fee_credit"], total), 2)
    to_debit = round(total - credit, 2)
    ids = [f["id"] for f in fees]
    if to_debit > 0:
        if h["mandate_status"] != "active":
            reason = "no_mandate"
        elif spent_this_month(conn, household_id) + to_debit > h["mandate_limit"] + 1e-6:
            reason = "over_limit"
        else:
            reason = None
        if reason:
            conn.execute(f"UPDATE fee_payments SET status = 'due' WHERE id IN ({_in(ids)}) "
                         "AND status IN ('accrued','due')", ids)
            return {"paid": 0, "due": len(ids), "debited": 0.0, "credit_used": 0.0, "reason": reason}
    upi_ref = adapters.new_upi_ref() if to_debit > 0 else None
    left, now = credit, clock.ts()
    for f in fees:
        amount = f["fee"] + f["platform_fee"]
        use = min(left, amount)
        left -= use
        conn.execute("UPDATE fee_payments SET status = 'paid', credit_used = ?, debited = ?, upi_ref = ?, "
                     "paid_at = ? WHERE id = ? AND status IN ('accrued','due')",
                     (round(use, 2), round(amount - use, 2), upi_ref, now, f["id"]))
    if credit:
        conn.execute("UPDATE households SET fee_credit = fee_credit - ? WHERE id = ?", (credit, household_id))
        revenue.record(conn, "rewards", -credit, ref_type="household", ref_id=household_id,
                       note="Points redeemed against collection fees")
    platform = round(sum(f["platform_fee"] for f in fees), 2)
    if book_fee:
        revenue.record(conn, "pickup_fee", platform, ref_type="household", ref_id=household_id,
                       note=f"{len(fees)} pickup(s)")
    return {"paid": len(fees), "due": 0, "debited": to_debit, "credit_used": credit, "upi_ref": upi_ref,
            "platform_fee": platform}


def settle_ready(conn, *, force: bool = False) -> int:
    """Debit every fee whose notice period is over: per-pickup fees a day after the pickup, monthly-plan
    fees once their month has ended, and earlier 'due' fees again. One debit per household.

    Run lazily whenever someone looks at a wallet, a route or the ops dashboard (no background timer,
    so it works on serverless); a daily cron can call the ops billing route in the pilot. `force`
    skips the waiting periods: demo only."""
    if force:
        ready = rows(conn.execute("SELECT id, household_id FROM fee_payments WHERE status IN ('accrued','due')"))
    else:
        month_start = (clock.now() + clock.IST).strftime("%Y-%m-01")
        ready = rows(conn.execute(
            "SELECT id, household_id FROM fee_payments WHERE status = 'due' "
            "OR (status = 'accrued' AND plan = 'per_pickup' AND created_at <= ?) "
            "OR (status = 'accrued' AND plan = 'monthly' AND day < ?)",
            (clock.ago(hours=PRE_DEBIT_NOTICE_H), month_start)))
    by_household: dict[int, list[int]] = {}
    for r in ready:
        by_household.setdefault(r["household_id"], []).append(r["id"])
    # One revenue entry per billing run, not one per household.
    paid, platform = 0, 0.0
    for hid, ids in by_household.items():
        r = charge(conn, hid, ids, book_fee=False)
        paid += r["paid"]
        platform += r.get("platform_fee", 0.0)
    revenue.record(conn, "pickup_fee", platform, note=f"AutoPay run: {paid} pickup(s), {len(by_household)} home(s)")
    return paid


# ---------- what the household can do ----------

def set_mandate(conn, household_id: int, limit: float) -> dict:
    lo, hi = MANDATE_LIMIT_RANGE
    if not (lo <= limit <= hi):
        raise ApiError(400, f"Monthly limit must be between ₹{lo} and ₹{hi:,}")
    h = household(conn, household_id)
    # Mock: in the pilot the household approves the mandate in their own UPI app and the payment
    # provider tells us its id and their VPA.
    conn.execute("UPDATE households SET mandate_status = 'active', mandate_limit = ?, mandate_vpa = ? WHERE id = ?",
                 (limit, h["mandate_vpa"] or f"{h['phone']}@upi", household_id))
    due = [r["id"] for r in rows(conn.execute(
        "SELECT id FROM fee_payments WHERE household_id = ? AND status = 'due'", (household_id,)))]
    return charge(conn, household_id, due)


def cancel_mandate(conn, household_id: int) -> None:
    conn.execute("UPDATE households SET mandate_status = 'none' WHERE id = ?", (household_id,))


def set_plan(conn, household_id: int, plan: str) -> None:
    """Applies from the next pickup; fees already recorded keep the plan they were made under."""
    if plan not in ("per_pickup", "monthly"):
        raise ApiError(400, "Plan must be per_pickup or monthly")
    conn.execute("UPDATE households SET fee_plan = ? WHERE id = ?", (plan, household_id))


def redeem(conn, household_id: int, points: int) -> dict:
    h = household(conn, household_id)
    if points <= 0 or points % REDEEM_STEP:
        raise ApiError(400, f"Redeem in steps of {REDEEM_STEP} points")
    if points > h["points"]:
        raise ApiError(409, f"You have {h['points']} points")
    credit = round(points * POINT_VALUE, 2)
    cur = conn.execute("UPDATE households SET points = points - ?, fee_credit = fee_credit + ? "
                       "WHERE id = ? AND points >= ?", (points, credit, household_id, points))
    if cur.rowcount == 0:
        raise ApiError(409, "Points changed — try again")
    conn.execute("INSERT INTO points_events (household_id, pickup_id, reason, points, created_at) "
                 "VALUES (?, NULL, 'redeemed', ?, ?)", (household_id, -points, clock.ts()))
    return {"points": points, "credit": credit}


def dispute(conn, household_id: int, pickup_id: int, reason: str | None) -> dict:
    """"No pickup today." Before the debit, the fee is simply cancelled; after it, refunded. Points
    for the pickup are taken back, and a pattern of disputes flags the collector for Satin."""
    p = one(conn.execute("SELECT * FROM pickups WHERE id = ? AND household_id = ?", (pickup_id, household_id)))
    if not p:
        raise ApiError(404, "Pickup not found")
    if p["status"] != "done":
        raise ApiError(409, "Already reported")
    if p["created_at"] < clock.ago(hours=DISPUTE_WINDOW_H):
        raise ApiError(409, f"Pickups can be reported within {DISPUTE_WINDOW_H} hours")
    cur = conn.execute("UPDATE pickups SET status = 'disputed', dispute_reason = ?, disputed_at = ? "
                       "WHERE id = ? AND status = 'done'",
                       ((reason or "No pickup")[:200], clock.ts(), pickup_id))
    if cur.rowcount == 0:
        raise ApiError(409, "Already reported")
    f = one(conn.execute("SELECT * FROM fee_payments WHERE pickup_id = ?", (pickup_id,)))
    if f and f["status"] in ("accrued", "due"):
        conn.execute("UPDATE fee_payments SET status = 'cancelled' WHERE id = ?", (f["id"],))
    elif f and f["status"] == "paid":
        # Mock refund of the debit to the household's bank; the points credit goes back to them.
        conn.execute("UPDATE fee_payments SET status = 'refunded' WHERE id = ?", (f["id"],))
        if f["credit_used"]:
            conn.execute("UPDATE households SET fee_credit = fee_credit + ? WHERE id = ?",
                         (f["credit_used"], household_id))
            revenue.record(conn, "rewards", f["credit_used"], ref_type="pickup", ref_id=pickup_id,
                           note="Refunded pickup: credit returned")
        revenue.record(conn, "pickup_fee", -f["platform_fee"], ref_type="pickup", ref_id=pickup_id,
                       note="Refunded pickup")
    h = household(conn, household_id)
    take = min(p["points"], max(0, h["points"]))
    if take:
        conn.execute("UPDATE households SET points = points - ? WHERE id = ?", (take, household_id))
        conn.execute("INSERT INTO points_events (household_id, pickup_id, reason, points, created_at) "
                     "VALUES (?,?, 'reversed', ?, ?)", (household_id, pickup_id, -take, clock.ts()))
    fraud.check_pickup_disputes(conn, p["collector_id"])
    send(conn, h, "शिकायत दर्ज हो गई। इस पिकअप का पैसा नहीं कटेगा।" if h["language"] == "hi"
         else "Reported. You will not be charged for this pickup.")
    score.recompute(conn, p["collector_id"])
    return one(conn.execute("SELECT * FROM pickups WHERE id = ?", (pickup_id,)))


# ---------- views ----------

def _fee_sum(conn, household_id: int, status: str) -> float:
    return round(conn.execute("SELECT COALESCE(SUM(fee + platform_fee),0) FROM fee_payments "
                              "WHERE household_id = ? AND status = ?", (household_id, status)).fetchone()[0], 2)


def household_view(conn, household_id: int) -> dict:
    settle_ready(conn)
    h = household(conn, household_id)
    today = clock.ist_day()
    month_first = today[:7] + "-01"
    collector = one(conn.execute("SELECT name FROM collectors WHERE id = ?", (h["collector_id"],))) \
        if h["collector_id"] else None
    month = one(conn.execute(
        "SELECT COUNT(*) AS pickups, COALESCE(SUM(CASE WHEN segregation = 'separated' THEN 1 ELSE 0 END),0) "
        "AS separated FROM pickups WHERE household_id = ? AND status = 'done' AND day >= ?",
        (household_id, month_first)))
    earned = conn.execute(
        "SELECT COALESCE(SUM(e.points),0) FROM points_events e JOIN pickups p ON p.id = e.pickup_id "
        "WHERE e.household_id = ? AND e.reason IN ('separated','streak') AND p.status = 'done' AND p.day >= ?",
        (household_id, month_first)).fetchone()[0]
    pickups = rows(conn.execute(
        "SELECT p.id, p.day, p.segregation, p.points, p.status, p.created_at, p.photo_url, "
        "f.fee, f.platform_fee, f.debited, f.credit_used, f.status AS fee_status, f.plan, f.paid_at "
        "FROM pickups p LEFT JOIN fee_payments f ON f.pickup_id = p.id "
        "WHERE p.household_id = ? ORDER BY p.day DESC LIMIT 30", (household_id,)))
    window = clock.ago(hours=DISPUTE_WINDOW_H)
    for p in pickups:
        p["can_dispute"] = p["status"] == "done" and p["created_at"] >= window
    return {
        "household": _public(h),
        "collector_name": collector["name"] if collector else None,
        "wallet": {
            "mandate_status": h["mandate_status"], "mandate_limit": h["mandate_limit"],
            "mandate_vpa": h["mandate_vpa"], "spent_month": round(spent_this_month(conn, household_id), 2),
            "upcoming": _fee_sum(conn, household_id, "accrued"), "due": _fee_sum(conn, household_id, "due"),
            "fee_credit": round(h["fee_credit"], 2), "fee_plan": h["fee_plan"],
            "fee_per_pickup": h["fee_per_pickup"], "monthly_fee": h["monthly_fee"],
            "platform_fee": PLATFORM_FEE_PER_PICKUP,
        },
        "points": {
            "balance": h["points"], "value": POINT_VALUE, "redeem_step": REDEEM_STEP,
            "earned_month": int(earned), "monthly_cap": MONTHLY_POINTS_CAP, "streak": streak(conn, household_id),
            "streak_every": STREAK_PICKUPS, "streak_bonus": STREAK_BONUS, "per_separated": POINTS_SEPARATED,
        },
        "month": month,
        "today": next((p for p in pickups if p["day"] == today), None),
        "pickups": pickups,
        "messages": rows(conn.execute("SELECT * FROM household_messages WHERE household_id = ? "
                                      "ORDER BY id DESC LIMIT 10", (household_id,))),
        "compliance": compliance_report(conn, household_id) if h["kind"] == "bulk" else None,
    }


def compliance_report(conn, household_id: int, month: str | None = None) -> dict:
    """For bulk waste generators: a day-by-day record that waste was handed over to an authorised
    collector, and whether it was segregated. The subscription is what makes it downloadable."""
    h = household(conn, household_id)
    today = clock.ist_day()
    month = month or today[:7]
    y, m = int(month[:4]), int(month[5:7])
    last = min(calendar.monthrange(y, m)[1], int(today[8:]) if month == today[:7] else 31)
    days = [date(y, m, d).isoformat() for d in range(1, last + 1)]
    picks = {p["day"]: p for p in rows(conn.execute(
        "SELECT p.day, p.segregation, p.status, p.created_at, p.photo_url, c.name AS collector_name "
        "FROM pickups p JOIN collectors c ON c.id = p.collector_id WHERE p.household_id = ? AND p.day LIKE ? "
        "ORDER BY p.day", (household_id, month + "%")))}
    done = [p for p in picks.values() if p["status"] == "done"]
    separated = sum(1 for p in done if p["segregation"] == "separated")
    return {
        "subscribed": bool(h["compliance_plan"]), "monthly_fee": revenue.COMPLIANCE_MONTHLY_FEE,
        "month": month, "name": h["name"], "ward": h["ward"],
        "days": len(days), "handed_over": len(done), "separated": separated,
        "separated_pct": round(100 * separated / len(done)) if done else None,
        "missed": [d for d in days if d not in picks or picks[d]["status"] != "done"],
        "log": [{"day": d, **picks[d]} for d in days if d in picks],
    }


def collector_route(conn, collector_id: int) -> dict:
    """The door-to-door collector's day: the doors on their route, which are done, and what they've earned.
    Door QR codes are not included: those are on the doors."""
    settle_ready(conn)
    today = clock.ist_day()
    homes = rows(conn.execute(
        "SELECT h.id, h.name, h.kind, h.lat, h.lng, p.segregation AS today_segregation, p.status AS today_status, "
        "(SELECT MAX(day) FROM pickups x WHERE x.household_id = h.id AND x.status = 'done') AS last_day "
        "FROM households h LEFT JOIN pickups p ON p.household_id = h.id AND p.day = ? "
        "WHERE h.collector_id = ? ORDER BY h.id", (today, collector_id)))
    month_first = today[:7] + "-01"
    earn = one(conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN day = ? THEN fee ELSE 0 END),0) AS today, "
        "COALESCE(SUM(CASE WHEN status = 'paid' THEN fee ELSE 0 END),0) AS month_paid, "
        "COALESCE(SUM(CASE WHEN status IN ('accrued','due') THEN fee ELSE 0 END),0) AS month_pending "
        "FROM fee_payments WHERE collector_id = ? AND day >= ? AND status IN ('accrued','due','paid')",
        (today, collector_id, month_first)))
    done = [h for h in homes if h["today_status"]]
    return {
        "day": today,
        "homes": homes,
        "done": len(done),
        "separated": sum(1 for h in done if h["today_segregation"] == "separated"),
        "earnings": {k: round(v, 2) for k, v in earn.items()},
        "recent": rows(conn.execute(
            "SELECT p.id, p.day, p.segregation, p.status, p.created_at, h.name, f.fee, f.status AS fee_status "
            "FROM pickups p JOIN households h ON h.id = p.household_id "
            "LEFT JOIN fee_payments f ON f.pickup_id = p.id WHERE p.collector_id = ? "
            "ORDER BY p.id DESC LIMIT 15", (collector_id,))),
    }


def ward_overview(conn) -> dict:
    """The WorthyWaste team's (and later the ward officer's) view: coverage, segregation, missed doors."""
    settle_ready(conn)
    today = clock.ist_day()
    d30 = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
    d2 = (date.fromisoformat(today) - timedelta(days=2)).isoformat()
    wards = rows(conn.execute(
        "SELECT h.ward, COUNT(*) AS homes, "
        "COALESCE(SUM(CASE WHEN h.mandate_status = 'active' THEN 1 ELSE 0 END),0) AS mandates, "
        "COALESCE(SUM(CASE WHEN h.kind = 'bulk' THEN 1 ELSE 0 END),0) AS bulk, "
        "COALESCE(SUM(CASE WHEN p.id IS NOT NULL THEN 1 ELSE 0 END),0) AS picked_today "
        # At most one pickup per door per day, so the join cannot double-count homes.
        "FROM households h LEFT JOIN pickups p ON p.household_id = h.id AND p.day = ? AND p.status = 'done' "
        "GROUP BY h.ward ORDER BY h.ward", (today,)))
    for w in wards:
        s = one(conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN p.segregation = 'separated' THEN 1 ELSE 0 END),0) AS sep "
            "FROM pickups p JOIN households h ON h.id = p.household_id WHERE h.ward = ? AND p.day >= ? "
            "AND p.status = 'done'", (w["ward"], d30)))
        w["separated_pct_30d"] = round(100 * s["sep"] / s["n"]) if s["n"] else None
    weekly = []
    base = date.fromisoformat(today)
    for i in reversed(range(8)):
        end = base - timedelta(days=7 * i)
        start = end - timedelta(days=6)
        s = one(conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN segregation = 'separated' THEN 1 ELSE 0 END),0) AS sep "
            "FROM pickups WHERE status = 'done' AND day >= ? AND day <= ?", (start.isoformat(), end.isoformat())))
        weekly.append({"week_start": start.isoformat(), "value": round(100 * s["sep"] / s["n"]) if s["n"] else 0})
    missed = rows(conn.execute(
        "SELECT h.id, h.name, h.ward, c.name AS collector_name, "
        "(SELECT MAX(day) FROM pickups p WHERE p.household_id = h.id AND p.status = 'done') AS last_day "
        "FROM households h LEFT JOIN collectors c ON c.id = h.collector_id ORDER BY h.id"))
    missed = [m for m in missed if not m["last_day"] or m["last_day"] < d2]
    collectors = rows(conn.execute(
        "SELECT c.id, c.name, s.score, "
        "(SELECT COUNT(*) FROM households h WHERE h.collector_id = c.id) AS homes, "
        "(SELECT COUNT(*) FROM pickups p WHERE p.collector_id = c.id AND p.day = ? AND p.status = 'done') AS today, "
        "(SELECT COUNT(*) FROM pickups p WHERE p.collector_id = c.id AND p.status = 'disputed' AND p.day >= ?) "
        "AS disputes_30d, "
        "(SELECT COUNT(*) FROM fraud_flags f WHERE f.collector_id = c.id AND f.status = 'open') AS open_flags "
        "FROM collectors c LEFT JOIN scores s ON s.collector_id = c.id WHERE c.kind = 'door_to_door' ORDER BY c.id",
        (today, d30)))
    liability = conn.execute("SELECT COALESCE(SUM(points),0) FROM households").fetchone()[0] * POINT_VALUE
    return {"day": today, "wards": wards, "separated_by_week": weekly, "missed": missed,
            "collectors": collectors, "points_liability": round(liability, 2),
            "dues": round(conn.execute("SELECT COALESCE(SUM(fee + platform_fee),0) FROM fee_payments "
                                       "WHERE status = 'due'").fetchone()[0], 2)}


def new_door_qr() -> str:
    import secrets
    return "WWH-" + secrets.token_hex(4).upper()
