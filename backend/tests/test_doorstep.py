"""Phase 2: door-to-door pickups, the household's Green Wallet (UPI AutoPay), points, disputes, and
the pilot revenue streams."""
import hashlib

import pytest
from fastapi.testclient import TestClient

from app import households, main, revenue
from tests.conftest import (DEMO_KEY_HEADER, MEENA_PHONE, RAJU, RAJU_PHONE, SATIN_PHONE, env, ids, login,
                            photo, reset)

SUNIL_PHONE = "9810000006"
VIKAS_PHONE = "9810000007"
ANITA_PHONE = "9814000001"
HOTEL_PHONE = "9814000002"
OPS_PHONE = "9813000001"
GUPTA_PHONE = "9811000002"


def door(phone: str) -> str:
    """Door QR of a seeded household (seed.py derives it from the phone number)."""
    return "WWH-" + hashlib.sha256(f"door:{phone}".encode()).hexdigest()[:8].upper()


def household_id(phone: str) -> int:
    return main._db.execute("SELECT id FROM households WHERE phone = ?", (phone,)).fetchone()[0]


def scan(client, qr, segregation="separated", loc=RAJU, img=None):
    data = {"door_qr": qr, "segregation": segregation, "lat": loc[0], "lng": loc[1]}
    files = {"photo": ("w.jpg", img, "image/jpeg")} if img else None
    return client.post("/api/pickups", data=data, files=files)


def fresh_home(phone: str, *, plan="per_pickup", mandate=True, limit=300.0) -> str:
    """A new home on Sunil's route at the demo spot, so tests don't depend on seeded history."""
    sunil = main._db.execute("SELECT id FROM collectors WHERE phone = ?", (SUNIL_PHONE,)).fetchone()[0]
    qr = "WWH-T" + phone[-7:]
    with main._tx() as conn:
        conn.execute(
            "INSERT INTO households (kind, name, phone, pin_hash, ward, lat, lng, door_qr, collector_id, fee_plan, "
            "fee_per_pickup, monthly_fee, mandate_vpa, mandate_status, mandate_limit, created_at) "
            "VALUES ('home', ?, ?, (SELECT pin_hash FROM households WHERE phone = ?), 'Test ward', ?, ?, ?, ?, ?, "
            "5, 150, ?, ?, ?, '2026-01-01 00:00:00')",
            (f"Test {phone}", phone, ANITA_PHONE, RAJU[0], RAJU[1], qr, sunil, plan,
             f"{phone}@upi" if mandate else None, "active" if mandate else "none", limit))
    return qr


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        reset(c)
        login(c, "satin", SATIN_PHONE)
        yield c


# ---------- the pickup ----------

def test_sunil_scans_anitas_door(client):
    login(client, "collector", SUNIL_PHONE)
    route = client.get("/api/collectors/me/route").json()
    assert any(h["name"].startswith("B-204") and not h["today_status"] for h in route["homes"])
    assert all("door_qr" not in h for h in route["homes"]), "door codes are on the doors, not in the app"

    r = scan(client, door(ANITA_PHONE), img=photo(9001))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["pickup"]["segregation"] == "separated" and body["pickup"]["photo_url"]
    assert body["points"] in (5, 25)  # 25 when it completes a 7-pickup streak
    assert body["fee"]["status"] == "accrued" and body["fee"]["fee"] == 5 and body["fee"]["platform_fee"] == 0.5

    login(client, "household", ANITA_PHONE)
    me = client.get("/api/households/me").json()
    assert me["today"]["id"] == body["pickup"]["id"]
    assert me["wallet"]["upcoming"] >= 5.5
    assert "AutoPay" in me["messages"][0]["text"] and "पॉइंट" in me["messages"][0]["text"]


def test_one_pickup_per_door_per_day(client):
    login(client, "collector", SUNIL_PHONE)
    r = scan(client, door(ANITA_PHONE))
    assert r.status_code == 409 and r.json()["rule"] == "already_picked_today"


def test_scan_must_be_at_the_door(client):
    qr = fresh_home("9814900001")
    login(client, "collector", SUNIL_PHONE)
    r = scan(client, qr, loc=(RAJU[0] + 0.002, RAJU[1]))  # ~220 m away
    assert r.status_code == 403 and r.json()["rule"] == "gps_far_from_home"


def test_only_the_route_collector_and_only_door_to_door(client):
    qr = fresh_home("9814900002")
    login(client, "collector", VIKAS_PHONE)
    r = scan(client, qr)
    assert r.status_code == 403 and r.json()["rule"] == "not_on_route"
    login(client, "collector", MEENA_PHONE)
    assert scan(client, qr).status_code == 403
    login(client, "collector", SUNIL_PHONE)
    assert scan(client, "WWH-NOPE0000").status_code == 404


def test_a_reused_photo_is_refused(client):
    a, b = fresh_home("9814900003"), fresh_home("9814900004")
    login(client, "collector", SUNIL_PHONE)
    assert scan(client, a, img=photo(9100)).status_code == 201
    r = scan(client, b, img=photo(9100))
    assert r.status_code == 409 and r.json()["rule"] == "duplicate_photo"
    flags = [f for f in client.get("/api/flags").json() if f["rule"] == "duplicate_photo"
             and "pickup photo" in f["detail"]]
    assert flags, "the refused attempt is still recorded for Satin"


def test_mixed_waste_earns_no_points(client):
    qr = fresh_home("9814900005")
    login(client, "collector", SUNIL_PHONE)
    r = scan(client, qr, segregation="mixed").json()
    assert r["points"] == 0 and r["fee"]["fee"] == 5  # the collector still did the work


# ---------- Green Wallet ----------

def test_autopay_debits_after_the_notice_and_pays_the_collector(client):
    qr = fresh_home("9814900006")
    login(client, "collector", SUNIL_PHONE)
    fee = scan(client, qr).json()["fee"]
    with main._tx() as conn:
        households.settle_ready(conn)  # the pre-debit notice has not run its 24 hours yet
        assert conn.execute("SELECT status FROM fee_payments WHERE id = ?", (fee["id"],)).fetchone()[0] == "accrued"
        before =conn.execute("SELECT COALESCE(SUM(amount),0) FROM revenue WHERE stream = 'pickup_fee'").fetchone()[0]
    login(client, "household", "9814900006")
    paid = client.post("/api/demo/households/me/settle").json()
    assert paid["paid"] == 1 and paid["debited"] == 5.5 and paid["upi_ref"]
    after = main._db.execute("SELECT COALESCE(SUM(amount),0) FROM revenue WHERE stream = 'pickup_fee'").fetchone()[0]
    assert round(after - before, 2) == 0.5
    me = client.get("/api/households/me").json()
    assert me["wallet"]["spent_month"] >= 5.5 and me["pickups"][0]["fee_status"] == "paid"


def test_no_mandate_means_due_until_autopay_is_turned_on(client):
    qr = fresh_home("9814900007", mandate=False)
    login(client, "collector", SUNIL_PHONE)
    assert scan(client, qr).status_code == 201  # the waste is still collected
    login(client, "household", "9814900007")
    assert client.post("/api/demo/households/me/settle").json()["reason"] == "no_mandate"
    assert client.get("/api/households/me").json()["wallet"]["due"] == 5.5
    assert client.post("/api/households/me/mandate", json={"limit": 10}).status_code == 400
    r = client.post("/api/households/me/mandate", json={"limit": 200}).json()
    assert r["paid"] == 1
    assert client.get("/api/households/me").json()["wallet"]["due"] == 0


def test_a_debit_over_the_monthly_limit_waits(client):
    qr = fresh_home("9814900008", limit=50)
    with main._tx() as conn:
        hid = household_id("9814900008")
        conn.execute("INSERT INTO pickups (household_id, collector_id, day, segregation, lat, lng, distance_m, "
                     "created_at) VALUES (?, 6, '2000-01-01', 'mixed', 0, 0, 0, ?)", (hid, main.clock.ts()))
        pid = conn.execute("SELECT MAX(id) FROM pickups").fetchone()[0]
        conn.execute("INSERT INTO fee_payments (household_id, collector_id, pickup_id, day, plan, fee, platform_fee, "
                     "debited, status, created_at, paid_at) VALUES (?, 6, ?, '2000-01-01', 'per_pickup', 47, 0, 47, "
                     "'paid', ?, ?)", (hid, pid, main.clock.ts(), main.clock.ts()))
    login(client, "collector", SUNIL_PHONE)
    scan(client, qr)
    login(client, "household", "9814900008")
    assert client.post("/api/demo/households/me/settle").json()["reason"] == "over_limit"


def test_points_redeem_against_the_fee(client):
    login(client, "household", ANITA_PHONE)
    me = client.get("/api/households/me").json()
    assert me["points"]["balance"] >= 100
    assert client.post("/api/households/me/redeem", json={"points": 50}).status_code == 400
    assert client.post("/api/households/me/redeem", json={"points": 100_000}).status_code == 409
    r = client.post("/api/households/me/redeem", json={"points": 100}).json()
    assert r["credit"] == 5.0
    before = main._db.execute("SELECT COALESCE(SUM(amount),0) FROM revenue WHERE stream = 'rewards'").fetchone()[0]
    paid = client.post("/api/demo/households/me/settle").json()
    assert paid["credit_used"] > 0
    after = main._db.execute("SELECT COALESCE(SUM(amount),0) FROM revenue WHERE stream = 'rewards'").fetchone()[0]
    assert round(before - after, 2) == paid["credit_used"], "rewards are a cost to us"


def test_monthly_plan_waits_for_the_month_end(client):
    qr = fresh_home("9814900009", plan="monthly")
    login(client, "collector", SUNIL_PHONE)
    fee = scan(client, qr).json()["fee"]
    assert fee["plan"] == "monthly" and fee["fee"] < 5.5  # ₹150 / days in month
    with main._tx() as conn:
        households.settle_ready(conn)
        assert conn.execute("SELECT status FROM fee_payments WHERE id = ?", (fee["id"],)).fetchone()[0] == "accrued"


# ---------- disputes ----------

def test_no_pickup_today_cancels_the_fee_and_the_points(client):
    qr = fresh_home("9814900010")
    login(client, "collector", SUNIL_PHONE)
    body = scan(client, qr).json()
    login(client, "household", "9814900010")
    me = client.get("/api/households/me").json()
    assert me["points"]["balance"] == body["points"] and me["pickups"][0]["can_dispute"]
    r = client.post(f"/api/households/me/pickups/{body['pickup']['id']}/dispute", json={"reason": "Nobody came"})
    assert r.status_code == 200 and r.json()["status"] == "disputed"
    me = client.get("/api/households/me").json()
    assert me["points"]["balance"] == 0 and me["pickups"][0]["fee_status"] == "cancelled"
    assert client.post(f"/api/households/me/pickups/{body['pickup']['id']}/dispute", json={}).status_code == 409


def test_a_household_cannot_dispute_someone_elses_pickup(client):
    login(client, "household", ANITA_PHONE)
    other = main._db.execute("SELECT id FROM pickups WHERE household_id != ? ORDER BY id DESC LIMIT 1",
                             (household_id(ANITA_PHONE),)).fetchone()[0]
    assert client.post(f"/api/households/me/pickups/{other}/dispute", json={}).status_code == 404


def test_three_disputes_in_a_week_hold_the_collectors_loan(client):
    login(client, "collector", SUNIL_PHONE)
    sunil = client.get("/api/auth/me?role=collector").json()["user"]["id"]
    assert client.get(f"/api/collectors/{sunil}").json()["eligibility"]["eligible"]
    for i in range(3):
        phone = f"98149001{i + 11}"
        qr = fresh_home(phone)
        login(client, "collector", SUNIL_PHONE)
        pid = scan(client, qr).json()["pickup"]["id"]
        login(client, "household", phone)
        assert client.post(f"/api/households/me/pickups/{pid}/dispute", json={}).status_code == 200
    flags = [f for f in client.get("/api/flags").json() if f["rule"] == "pickup_disputed"]
    assert flags and flags[0]["collector_id"] == sunil
    el = client.get(f"/api/collectors/{sunil}").json()["eligibility"]
    assert not el["eligible"] and not next(c for c in el["checks"] if c["key"] == "review")["ok"]


# ---------- score and Satin ----------

def test_a_door_to_door_collector_is_scored_on_pickups(client):
    reset(client)
    login(client, "satin", SATIN_PHONE)
    collectors, _ = ids(client)
    sunil = collectors["Sunil"]
    assert sunil["kind"] == "door_to_door" and sunil["pickup_days"] >= 20 and sunil["sales"] == 0
    p = client.get(f"/api/collectors/{sunil['id']}").json()
    assert p["eligibility"]["eligible"], p["eligibility"]
    assert p["score"]["inputs"]["D"]["label"] == "Homes served"
    assert p["pickups"] and sum(w["value"] for w in p["income_by_week"]) > 0
    vikas = collectors["Vikas"]
    flags = [f for f in client.get("/api/flags").json() if f["rule"] == "pickup_burst"]
    assert flags and flags[0]["collector_id"] == vikas["id"]


def test_satin_loan_earns_a_lead_fee(client):
    collectors, _ = ids(client)
    before = main._db.execute("SELECT COALESCE(SUM(amount),0) FROM revenue WHERE stream = 'loan_lead'").fetchone()[0]
    r = client.post("/api/loans", json={"collector_id": collectors["Sunil"]["id"]})
    assert r.status_code == 201, r.text
    after = main._db.execute("SELECT COALESCE(SUM(amount),0) FROM revenue WHERE stream = 'loan_lead'").fetchone()[0]
    assert round(after - before, 2) == r.json()["principal"] * revenue.LOAN_LEAD_FEE_PCT


# ---------- other revenue streams ----------

def test_purchase_bills_are_a_pro_feature(client):
    login(client, "dealer", GUPTA_PHONE)
    tx = main._db.execute("SELECT id FROM transactions WHERE dealer_id = 2 LIMIT 1").fetchone()[0]
    r = client.get(f"/api/dealers/me/bills/{tx}")
    assert r.status_code == 402 and r.json()["rule"] == "needs_pro"
    assert client.post("/api/dealers/me/plan").json()["plan"] == "pro"
    bill = client.get(f"/api/dealers/me/bills/{tx}").json()
    assert bill["bill_no"].startswith("WW-02-") and bill["amount"] > 0
    raju_tx = main._db.execute("SELECT id FROM transactions WHERE dealer_id = 1 LIMIT 1").fetchone()[0]
    assert client.get(f"/api/dealers/me/bills/{raju_tx}").status_code == 404, "only your own sales"


def test_insurance_enrolment_earns_a_commission(client):
    login(client, "collector", SUNIL_PHONE)
    assert client.get("/api/collectors/me/insurance").json()["policy"] is None
    r = client.post("/api/collectors/me/insurance").json()
    assert r["policy"]["status"] == "active" and r["policy"]["cover"] == revenue.INSURANCE_COVER
    again = client.post("/api/collectors/me/insurance").json()
    assert again["policy"]["id"] == r["policy"]["id"], "enrolling twice does not sell a second policy"


def test_compliance_report_is_for_bulk_generators(client):
    login(client, "household", ANITA_PHONE)
    assert client.get("/api/households/me/compliance").status_code == 404
    login(client, "household", HOTEL_PHONE)
    rep = client.get("/api/households/me/compliance").json()
    assert rep["subscribed"] and rep["handed_over"] >= 0 and rep["days"] >= 1
    assert client.get("/api/households/me/compliance?month=oops").status_code == 400
    me = client.get("/api/households/me").json()
    assert me["compliance"]["name"] == "Hotel Shiv Sagar"


# ---------- the WorthyWaste team, and who may see what ----------

def test_ops_dashboard(client):
    with TestClient(main.app) as anon:
        assert anon.get("/api/ops/overview").status_code == 401
        login(anon, "satin", SATIN_PHONE)
        assert anon.get("/api/ops/overview").status_code == 401, "Satin is the lender, not us"
        login(anon, "ops", OPS_PHONE)
        o = anon.get("/api/ops/overview").json()
        streams = {s["stream"]: s for s in o["revenue"]["streams"]}
        assert set(streams) == set(revenue.STREAMS)
        for k in ("pickup_fee", "loan_lead", "compliance", "dealer_pro", "insurance"):
            assert streams[k]["total"] > 0, k
        assert streams["rewards"]["total"] < 0
        assert o["wards"] and o["wards"][0]["homes"] >= 60
        assert any(c["name"].startswith("Sunil") for c in o["collectors"])
        assert anon.post("/api/ops/billing/run", json={}).status_code == 200
        with env(WW_DEMO_MODE=None):
            assert anon.post("/api/ops/billing/run", json={"force": True}).status_code == 403
            assert anon.post("/api/demo/households/me/settle").status_code == 404


def test_household_pages_need_a_household(client):
    with TestClient(main.app) as anon:
        assert anon.get("/api/households/me").status_code == 401
        login(anon, "collector", SUNIL_PHONE)
        assert anon.get("/api/households/me").status_code == 401
        assert anon.post("/api/households/me/redeem", json={"points": 100}).status_code == 401


def test_demo_door_scan_only_in_demo_mode(client):
    login(client, "collector", SUNIL_PHONE)
    hid = household_id(ANITA_PHONE)
    body = {"household_id": hid, "segregation": "separated", "lat": RAJU[0], "lng": RAJU[1]}
    with env(WW_DEMO_MODE=None):
        assert client.post("/api/demo/pickups/simulate-scan", json=body).status_code == 404
    r = client.post("/api/demo/pickups/simulate-scan", json=body)
    assert r.status_code in (201, 409), r.text
    login(client, "collector", VIKAS_PHONE)
    assert client.post("/api/demo/pickups/simulate-scan", json=body).status_code == 404, "not his door"


def test_reset_still_works(client):
    r = client.post("/api/demo/reset", headers=DEMO_KEY_HEADER)
    assert r.status_code == 200
    login(client, "dealer", RAJU_PHONE)
    assert client.get("/api/dealers/me/plan").json()["plan"] == "pro"
