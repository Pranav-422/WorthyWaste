"""Deterministic demo data. History is replayed through the real transaction code with the clock
pinned to each sale's time, so seeded flags come from the same fraud rules the live demo uses.

Story (Design Doc, 'Demo click path'):
  * Meena — the hero. Sells mostly to Raju; after the live 27.4 kg sale her score is 642 and her
    starter loan is unlocked.
  * Ramesh — got ₹340 from Gupta Scrap, sent ₹340 back 2 h later → circular-payment flag.
  * Gupta Scrap — buys far more than it sells to recyclers → mass-balance flag.
  * Farida — 180 kg in one day on a hand cart → volume-outlier flag.
  * Sunita — new, 9 sales, loan unlocks in 11 more.
  * Lakshmi — repaid her first loan on time, second cycle running.

Phase 2 (door-to-door collection, see _build_phase2):
  * Sunil — door-to-door collector, 30 doors in Shanti Apartments, two months of verified pickups:
    eligible for a first loan on pickup fees alone.
  * Anita (B-204) — separates almost every day; Green Wallet AutoPay on, points to redeem. The live
    demo scans her door. Her home sits on the demo spot, so ?demo=1 is standing at her door.
  * Hotel Shiv Sagar — a bulk generator on the monthly plan with the compliance report.
  * Vikas — new on the job; scanned 30 doors in 4 minutes → "too many doors too fast" flag.
"""
import hashlib
import random
from datetime import datetime, timedelta

from . import adapters, auth, clock, fraud, households, revenue, score, services
from .db import TABLES, Database, init_db, transaction

# Sample logins for the demo (shown on the login page). Every seeded account uses this PIN.
DEMO_PIN = "1234"

CITY = "Delhi"
RAJU = (28.67312, 77.28654)     # Raju Kabadi Store
GUPTA = (28.67921, 77.29433)    # Gupta Scrap Traders (~1 km away)

MEENA_CALIBRATION_KG = 8.0

GROUP = "Swachh Sakhi Mahila Samooh"

COLLECTORS = [
    # name, phone, lang, days on platform, group guarantee, equipment, vpa, qr
    ("Meena Devi", "9810000001", "hi", 100, 1, "hand_cart", "meena@okaxis", "WWC-MEENA001"),
    ("Sunita Kumari", "9810000002", "hi", 18, 1, "sack", "sunita@ybl", "WWC-SUNITA02"),
    ("Lakshmi Bai", "9810000003", "hi", 240, 1, "cycle_rickshaw", "lakshmi@okhdfc", "WWC-LAKSHMI3"),
    ("Ramesh Yadav", "9810000004", "hi", 75, 0, "hand_cart", "ramesh@paytm", "WWC-RAMESH04"),
    ("Farida Khatoon", "9810000005", "hi", 60, 1, "hand_cart", "farida@ybl", "WWC-FARIDA05"),
]

DEALERS = [
    ("Raju Kabadi Store", "Raju Prasad", "9811000001", *RAJU, "SCALE-RAJU-01", "rajukabadi@okicici", 86),
    ("Gupta Scrap Traders", "Anil Gupta", "9811000002", *GUPTA, "SCALE-GUPTA-01", "guptascrap@ybl", 74),
]

# Satin branch staff who review flags and disburse loans (name, phone, branch).
SATIN_USERS = [
    ("Priya Sharma", "9812000001", "Satin Creditcare · Narela branch"),
]

# The WorthyWaste team (revenue, wards, billing).
OPS_USERS = [("WorthyWaste Ops", "9813000001")]

# ---------- Phase 2 ----------
WARD = "Shanti Nagar (pilot ward)"
DOOR_GROUP = "Safai Mitra Samooh"
DOOR_COLLECTORS = [
    # name, phone, days on platform, vpa, qr
    ("Sunil Kumar", "9810000006", 75, "sunil@okaxis", "WWC-SUNIL006"),
    ("Vikas Paswan", "9810000007", 24, "vikas@ybl", "WWC-VIKAS007"),
]
ANITA_PHONE = "9814000001"
HOTEL_PHONE = "9814000002"


def ensure_satin_users(conn: Database) -> None:
    """Databases seeded before the Satin login existed have no branch staff, so add the sample
    account. Never touches a database that already has any."""
    if conn.execute("SELECT COUNT(*) FROM satin_users").fetchone()[0]:
        return
    with transaction(conn):
        for name, phone, branch in SATIN_USERS:
            conn.execute(
                "INSERT INTO satin_users (name, phone, pin_hash, branch, created_at) VALUES (?,?,?,?,?)",
                (name, phone, auth.hash_pin(DEMO_PIN), branch, clock.ts()))


def _wipe(conn):
    for t in reversed(TABLES):
        if t != "materials":
            conn.execute(f"DELETE FROM {t}")


def _at(base: datetime, days_ago: int, hour: int, minute: int = 0) -> datetime:
    # Sales happen 9:00–18:00 IST (03:30–12:30 UTC).
    d = (base - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0)
    return d + timedelta(hours=hour, minutes=minute)


def seed(db: Database, wipe: bool = False) -> None:
    """Postgres: build in an in-memory SQLite (thousands of small queries, fast locally), then bulk-copy,
    so a reset over the network takes seconds rather than minutes."""
    if not db.is_pg:
        _build(db, wipe)
        return
    mem = Database(path=":memory:")
    _build(mem, wipe=False)
    _copy(mem, db)


def _copy(src: Database, dst: Database) -> None:
    with transaction(dst):
        dst.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
        for t in TABLES:
            data = [dict(r) for r in src.execute(f"SELECT * FROM {t}").fetchall()]
            if not data:
                continue
            cols = list(data[0].keys())
            dst.executemany(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                            [tuple(r[c] for c in cols) for r in data])
            if "id" in cols:
                dst.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), (SELECT MAX(id) FROM {t}))")


def _build(conn: Database, wipe: bool) -> None:
    rng = random.Random(42)
    real_now = clock.now()
    init_db(conn)
    with transaction(conn):
        if wipe:
            _wipe(conn)
        conn.execute("INSERT INTO groups (id, name, leader_id, city) VALUES (1, ?, NULL, ?)", (GROUP, CITY))
        cids = {}
        for name, phone, lang, days, guarantee, equip, vpa, qr in COLLECTORS:
            joined = clock.ts(real_now - timedelta(days=days, hours=2))
            cur = conn.execute(
                "INSERT INTO collectors (name, phone, pin_hash, language, id_type, id_ref_hash, group_id, "
                "group_guarantee, qr_token, upi_vpa, equipment, consent_at, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (name, phone, auth.hash_pin(DEMO_PIN), lang, "e-Shram",
                 hashlib.sha256(f"demo-salt:{phone}".encode()).hexdigest(),
                 1, guarantee, qr, vpa, equip, joined, joined))
            cids[name.split()[0]] = cur.lastrowid
        conn.execute("UPDATE groups SET leader_id = ? WHERE id = 1", (cids["Lakshmi"],))
        dids = {}
        for shop, owner, phone, lat, lng, scale_id, vpa, rep in DEALERS:
            cur = conn.execute(
                "INSERT INTO dealers (shop_name, owner_name, phone, pin_hash, lat, lng, scale_id, upi_vpa, "
                "reputation, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (shop, owner, phone, auth.hash_pin(DEMO_PIN), lat, lng, scale_id, vpa, rep,
                 clock.ts(real_now - timedelta(days=300))))
            dids[shop.split()[0]] = cur.lastrowid
        for name, phone, branch in SATIN_USERS:
            conn.execute(
                "INSERT INTO satin_users (name, phone, pin_hash, branch, created_at) VALUES (?,?,?,?,?)",
                (name, phone, auth.hash_pin(DEMO_PIN), branch, clock.ts(real_now - timedelta(days=300))))
        dealer_vpa = {dids["Raju"]: DEALERS[0][6], dids["Gupta"]: DEALERS[1][6]}
        dealer_loc = {dids["Raju"]: RAJU, dids["Gupta"]: GUPTA}
        coll_vpa = {cids[c[0].split()[0]]: c[6] for c in COLLECTORS}

        sales = []  # (datetime, collector_id, dealer_id, material, est_kg, scale_kg)

        def add(cid, did, days_ago, kg, material="plastic", hour=None, est=None):
            h = hour if hour is not None else rng.randint(4, 11)
            when = _at(real_now, days_ago, h, rng.randint(0, 59))
            sales.append((when, cid, did, material, est or round(kg * rng.uniform(0.95, 1.05), 0) or 1, kg))

        # --- Meena: tuned so the live 27.4 kg sale lands her on 642 (see tests/test_demo_flow.py).
        m = cids["Meena"]
        meena_days = {
            # 30-day window → (days ago list)
            0: [1, 2, 4, 5, 7, 9, 11, 12, 15, 17, 19, 22, 25, 27],          # 14 days before today
            1: [31, 32, 33, 34, 35, 36, 38, 39, 40, 41, 42, 44, 45, 47, 48, 50, 52, 53, 55, 57, 58],
            2: [61, 63, 64, 66, 68, 70, 73, 75, 78, 81, 84, 86, 89, 92, 95, 98],
        }
        for window, days in meena_days.items():
            for i, d in enumerate(days):
                kg = round(rng.uniform(22, 30), 1)
                did = dids["Gupta"] if i % 6 == 5 else dids["Raju"]
                mat = "cardboard" if i % 4 == 3 else "plastic"
                add(m, did, d, kg, mat)

        # --- Sunita: new, 9 small sales.
        for d in [1, 3, 5, 6, 8, 10, 12, 14, 16]:
            add(cids["Sunita"], dids["Raju"], d, round(rng.uniform(8, 14), 1), rng.choice(["plastic", "paper"]))

        # --- Lakshmi: long tenure, steady, three dealers' worth of spread (two exist; fine).
        for d in range(1, 235):
            if rng.random() < 0.72:
                add(cids["Lakshmi"], rng.choice(list(dids.values())), d, round(rng.uniform(35, 55), 1),
                    rng.choice(["plastic", "metal", "cardboard", "paper"]))

        # --- Ramesh: regular seller to Gupta.
        for d in range(2, 74, 3):
            add(cids["Ramesh"], dids["Gupta"], d, round(rng.uniform(18, 26), 1), "plastic")

        # --- Farida: normal days, then one impossible day.
        for d in range(3, 58, 2):
            add(cids["Farida"], rng.choice(list(dids.values())), d, round(rng.uniform(15, 25), 1),
                rng.choice(["plastic", "cardboard"]))
        for h in (4, 7, 10):
            add(cids["Farida"], dids["Gupta"], 1, 60.0, "metal", hour=h, est=60)

        # Calibration sale: pins Meena's post-demo score to the 642 shown in the Design Doc.
        add(m, dids["Raju"], 37, MEENA_CALIBRATION_KG, "paper", hour=5, est=MEENA_CALIBRATION_KG)

        # Recycler sales every 3 days. Raju sells what he buys; Gupta has been selling only
        # ~75% for the last six weeks, so its purchases look inflated (mass-balance flag).
        recycle_rng = random.Random(7)
        events = [(x[0], "sale", x[1:]) for x in sales]
        for days_ago in range(229, 0, -3):
            for did in dids.values():
                frac = 0.75 if did == dids["Gupta"] and days_ago <= 42 else 0.985
                events.append((_at(real_now, days_ago, 12), "recycle", (did, frac)))
        events.sort(key=lambda e: e[0])
        try:
            for when, kind, payload in events:
                clock.freeze(when)
                if kind == "sale":
                    cid, did, mat, est, kg = payload
                    _replay_sale(conn, cid, did, mat, est, kg, dealer_loc[did], dealer_vpa[did], coll_vpa[cid])
                else:
                    did, frac = payload
                    for mat, open_kg in conn.execute(
                            "SELECT material, SUM(total_kg) FROM batches WHERE dealer_id = ? "
                            "AND recycler_sale_id IS NULL GROUP BY material", (did,)).fetchall():
                        if open_kg >= 1:
                            services.recycler_sale(
                                conn, dealer_id=did, recycler_name="GreenLoop Recyclers, Bawana",
                                material_code=mat, kg=round(open_kg * frac * recycle_rng.uniform(0.99, 1.0), 1),
                                invoice_ref=f"GLR-{recycle_rng.randint(10000, 99999)}")

            # --- Ramesh's circular payment: ₹340 payout from Gupta, ₹340 back 2 h later.
            clock.freeze(real_now - timedelta(hours=3, minutes=5))
            _replay_sale(conn, cids["Ramesh"], dids["Gupta"], "plastic", 28, 27.4, GUPTA,
                         dealer_vpa[dids["Gupta"]], coll_vpa[cids["Ramesh"]])
            clock.freeze(real_now - timedelta(hours=1, minutes=3))
            services.observe_upi(conn, coll_vpa[cids["Ramesh"]], dealer_vpa[dids["Gupta"]], 340)

            clock.freeze(real_now - timedelta(minutes=1))
            for did in dids.values():
                fraud.check_mass_balance(conn, did)
        finally:
            clock.freeze(None)

        # --- Lakshmi's loans: cycle 1 repaid on time, cycle 2 running.
        conn.execute(
            "INSERT INTO loans (collector_id, group_id, principal, tenure_m, status, instalments_due, "
            "instalments_on_time, disbursed_at) VALUES (?,1,5000,6,'repaid',6,6,?), (?,1,10000,6,'active',1,1,?)",
            (cids["Lakshmi"], clock.ts(real_now - timedelta(days=220)),
             cids["Lakshmi"], clock.ts(real_now - timedelta(days=40))))

        _build_phase2(conn, real_now, dids["Raju"], cids)

        conn.execute("DELETE FROM messages")
        score.recompute_all(conn)


def _monthly(conn, real_now, start_days_ago: int, stream: str, amount: float, **ref):
    """A subscription billed every 30 days since it started, as it would have been."""
    try:
        for d in range(start_days_ago, 0, -30):
            clock.freeze(real_now - timedelta(days=d))
            revenue.record(conn, stream, amount, **ref)
    finally:
        clock.freeze(None)


def _build_phase2(conn: Database, real_now: datetime, raju_id: int, cids: dict) -> None:
    """Households, door-to-door collectors and two months of pickups, replayed through the real
    pickup and AutoPay code, plus the other pilot revenue streams."""
    rng = random.Random(2026)
    for name, phone in OPS_USERS:
        conn.execute("INSERT INTO ops_users (name, phone, pin_hash, created_at) VALUES (?,?,?,?)",
                     (name, phone, auth.hash_pin(DEMO_PIN), clock.ts(real_now - timedelta(days=300))))
    conn.execute("INSERT INTO groups (id, name, leader_id, city) VALUES (2, ?, NULL, ?)", (DOOR_GROUP, CITY))
    door = {}
    for name, phone, days, vpa, qr in DOOR_COLLECTORS:
        joined = clock.ts(real_now - timedelta(days=days, hours=2))
        cur = conn.execute(
            "INSERT INTO collectors (name, phone, pin_hash, language, id_type, id_ref_hash, group_id, "
            "group_guarantee, qr_token, upi_vpa, equipment, kind, consent_at, created_at) "
            "VALUES (?,?,?, 'hi', 'e-Shram', ?, 2, 1, ?, ?, 'cycle_rickshaw', 'door_to_door', ?, ?)",
            (name, phone, auth.hash_pin(DEMO_PIN), hashlib.sha256(f"demo-salt:{phone}".encode()).hexdigest(),
             qr, vpa, joined, joined))
        door[name.split()[0]] = cur.lastrowid
    conn.execute("UPDATE groups SET leader_id = ? WHERE id = 2", (door["Sunil"],))

    onboarded = clock.ts(real_now - timedelta(days=63))
    homes = []  # (id, separate_rate or None for "improves over time", collector)

    def home(name, phone, lat, lng, collector, *, kind="home", plan="per_pickup", fee=None, monthly=None,
             mandate=True, contact=None, rate=None):
        cur = conn.execute(
            "INSERT INTO households (kind, name, contact_name, phone, pin_hash, language, ward, lat, lng, door_qr, "
            "collector_id, fee_plan, fee_per_pickup, monthly_fee, mandate_vpa, mandate_status, mandate_limit, "
            "created_at) VALUES (?,?,?,?,?, 'hi', ?,?,?,?,?,?,?,?,?,?,?,?)",
            (kind, name, contact, phone, auth.hash_pin(DEMO_PIN), WARD, lat, lng,
             "WWH-" + hashlib.sha256(f"door:{phone}".encode()).hexdigest()[:8].upper(), collector, plan,
             fee or households.DEFAULT_FEE_PER_PICKUP, monthly or households.DEFAULT_MONTHLY_FEE,
             f"{phone}@upi" if mandate else None, "active" if mandate else "none",
             300.0 if kind == "home" else 3000.0 if mandate else 0, onboarded))
        homes.append((cur.lastrowid, rate, collector))
        return cur.lastrowid

    lat0, lng0 = RAJU  # the demo spot: Anita's building
    anita = home("B-204, Shanti Apartments", ANITA_PHONE, lat0, lng0, door["Sunil"], contact="Anita Verma",
                 rate=0.93)
    hotel = home("Hotel Shiv Sagar", HOTEL_PHONE, lat0 + 0.0009, lng0 + 0.0006, door["Sunil"], kind="bulk",
                 plan="monthly", fee=50.0, monthly=1500.0, contact="Front office", rate=0.85)
    n = 0
    for block in "ABCD":
        for flat in (101, 102, 201, 202, 301, 302, 401):
            if len([h for h in homes if h[2] == door["Sunil"]]) >= 30:
                break
            if (block, flat) == ("B", 204):
                continue
            n += 1
            home(f"{block}-{flat}, Shanti Apartments", f"98140001{n:02d}",
                 lat0 + rng.uniform(-0.0012, 0.0012), lng0 + rng.uniform(-0.0012, 0.0012), door["Sunil"],
                 plan="monthly" if n % 5 == 0 else "per_pickup", mandate=n % 9 != 0)
    for i in range(1, 31):
        home(f"House {i}, Gali 4, Shanti Nagar", f"98140002{i:02d}", lat0 + 0.006 + rng.uniform(-0.001, 0.001),
             lng0 + 0.004 + rng.uniform(-0.001, 0.001), door["Vikas"], mandate=i % 4 != 0)
    loc = {h["id"]: (h["lat"], h["lng"]) for h in conn.execute("SELECT id, lat, lng FROM households")}

    def pick(hid, collector, when, separated):
        clock.freeze(when)
        lat, lng = loc[hid]
        households.record_pickup(conn, collector_id=collector, door_qr=conn.execute(
            "SELECT door_qr FROM households WHERE id = ?", (hid,)).fetchone()[0],
            segregation="separated" if separated else "mixed", lat=lat + 0.00005, lng=lng, notify=hid == anita)

    try:
        day0 = (real_now + clock.IST).replace(hour=0, minute=0, second=0) - clock.IST  # today 00:00 IST, in UTC
        for days_ago in range(62, 0, -1):
            start = day0 - timedelta(days=days_ago) + timedelta(hours=1, minutes=30 + rng.randint(0, 40))  # ~7:15 IST
            clock.freeze(start)
            households.settle_ready(conn)
            # Segregation catches on over the two months: about a third at first, most homes by now.
            base = 0.35 + 0.5 * (62 - days_ago) / 62
            for collector, joined_days in ((door["Sunil"], 62), (door["Vikas"], 20)):
                if days_ago > joined_days or rng.random() < 0.1:  # not yet working, or a day off
                    continue
                t = start
                for hid, rate, who in homes:
                    if who != collector or rng.random() > 0.93:
                        continue
                    t += timedelta(seconds=rng.randint(50, 110))
                    pick(hid, collector, t, rng.random() < (rate or base))
            if days_ago == 3:
                # Vikas's burst: 30 doors in 4 minutes, from the lane outside.
                t = start + timedelta(hours=3)
                for hid, _, who in homes:
                    if who == door["Vikas"] and not conn.execute(
                            "SELECT 1 FROM pickups WHERE household_id = ? AND day = ?",
                            (hid, clock.ist_day(t))).fetchone():
                        t += timedelta(seconds=8)
                        pick(hid, door["Vikas"], t, True)
            if days_ago in (40, 20):
                clock.freeze(start + timedelta(hours=10))
                households.redeem(conn, anita, 100)
            if days_ago in (47, 26):
                # Two isolated "no pickup today" reports on Sunil's route: recorded, not a pattern.
                victim = homes[5 + days_ago % 7][0]
                p = conn.execute("SELECT id FROM pickups WHERE household_id = ? ORDER BY id DESC LIMIT 1",
                                 (victim,)).fetchone()
                if p:
                    clock.freeze(start + timedelta(hours=6))
                    households.dispute(conn, victim, p[0], "Nobody came")

        # This morning: Sunil has done half his round. Anita's door is next, scanned live in the demo.
        t = real_now - timedelta(minutes=50)
        clock.freeze(t)
        households.settle_ready(conn)
        for hid, rate, who in homes[2:17]:
            t += timedelta(seconds=rng.randint(60, 100))
            pick(hid, door["Sunil"], t, rng.random() < (rate or 0.85))
    finally:
        clock.freeze(None)

    # Other revenue streams: Raju on Pro, two insured collectors, the hotel's compliance plan, and
    # the lead fee on Lakshmi's two Satin loans.
    conn.execute("UPDATE dealers SET plan = 'pro', plan_since = ? WHERE id = ?",
                 (clock.ts(real_now - timedelta(days=75)), raju_id))
    _monthly(conn, real_now, 75, "dealer_pro", revenue.DEALER_PRO_MONTHLY_FEE, ref_type="dealer", ref_id=raju_id)
    for cid, since in ((cids["Lakshmi"], 118), (cids["Meena"], 50)):
        conn.execute(
            "INSERT INTO insurance_policies (collector_id, partner, cover, monthly_premium, commission_pct, status, "
            "started_at) VALUES (?,?,?,?,?, 'active', ?)",
            (cid, revenue.INSURANCE_PARTNER, revenue.INSURANCE_COVER, revenue.INSURANCE_MONTHLY_PREMIUM,
             revenue.INSURANCE_COMMISSION_PCT, clock.ts(real_now - timedelta(days=since))))
        _monthly(conn, real_now, since, "insurance",
                 revenue.INSURANCE_MONTHLY_PREMIUM * revenue.INSURANCE_COMMISSION_PCT, ref_type="collector",
                 ref_id=cid)
    conn.execute("UPDATE households SET compliance_plan = 1 WHERE id = ?", (hotel,))
    _monthly(conn, real_now, 58, "compliance", revenue.COMPLIANCE_MONTHLY_FEE, ref_type="household", ref_id=hotel)
    for principal, days in ((5000, 220), (10000, 40)):
        clock.freeze(real_now - timedelta(days=days))
        try:
            revenue.record(conn, "loan_lead", principal * revenue.LOAN_LEAD_FEE_PCT, ref_type="collector",
                           ref_id=cids["Lakshmi"], note=f"₹{principal:,} loan")
        finally:
            clock.freeze(None)


def _replay_sale(conn, cid, did, mat, est, kg, loc, payer_vpa, payee_vpa):
    now = clock.ts()
    cur = conn.execute(
        "INSERT INTO sale_requests (collector_id, dealer_id, material, est_kg, lat, lng, status, dealer_lat, "
        "dealer_lng, gps_distance_m, scale_kg, scale_source, created_at, expires_at) "
        "VALUES (?,?,?,?,?,?, 'weighed', ?,?, 4.0, ?, 'sim:seed', ?, ?)",
        (cid, did, mat, est, loc[0], loc[1], loc[0], loc[1], kg, now, now))
    req = dict(conn.execute("SELECT * FROM sale_requests WHERE id = ?", (cur.lastrowid,)).fetchone())
    equipment = conn.execute("SELECT equipment FROM collectors WHERE id = ?", (cid,)).fetchone()[0]
    fraud.check_weight_gap(conn, req, kg)
    fraud.check_volume_outlier(conn, req, kg, equipment)
    rate = conn.execute("SELECT rate_per_kg FROM materials WHERE code = ?", (mat,)).fetchone()[0]
    services.record_transaction(conn, req, amount=services.pay_amount(kg, rate), upi_ref=adapters.new_upi_ref(),
                                payer_vpa=payer_vpa, payee_vpa=payee_vpa, notify=False)


if __name__ == "__main__":
    from .db import connect
    c = connect()
    init_db(c)
    seed(c, wipe=True)
    for r in c.execute("SELECT c.name, s.score FROM collectors c JOIN scores s ON s.collector_id = c.id"):
        print(f"{r[0]:<16} {r[1]}")
    for r in c.execute("SELECT rule, detail FROM fraud_flags"):
        print(f"[{r[0]}] {r[1]}")
