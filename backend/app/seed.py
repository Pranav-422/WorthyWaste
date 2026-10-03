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
"""
import hashlib
import random
from datetime import datetime, timedelta

from . import adapters, auth, clock, fraud, score, services
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

        conn.execute("DELETE FROM messages")
        score.recompute_all(conn)


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
