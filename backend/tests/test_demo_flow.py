"""Runs the Design Doc's demo click path end to end against a fresh database.

Environment, fixtures and helpers come from conftest.py.
"""
import time

from tests.conftest import RAJU, ids, login, new_request, photo, signed


def test_seeded_frauds_present(client):
    rules = {f["rule"] for f in client.get("/api/flags?status=open").json()}
    assert {"circular_payment", "mass_balance", "volume_outlier"} <= rules
    circ = next(f for f in client.get("/api/flags").json() if f["rule"] == "circular_payment")
    assert "₹340 returned to Gupta Scrap Traders within 2 h" in circ["detail"]


def test_demo_click_path(client):
    collectors, dealers = ids(client)
    meena, raju = collectors["Meena"], dealers["Raju"]
    img = photo(1)

    # 1. Collector raises the request.
    r = new_request(client, meena["id"], img)
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "open"

    # 2. Dealer scans QR; location matches.
    r = client.post(f"/api/requests/{req['id']}/accept",
                    json={"dealer_id": raju["id"], "qr_token": meena["qr_token"], "lat": RAJU[0] + 0.0001,
                          "lng": RAJU[1]})
    assert r.status_code == 200, r.text
    assert r.json()["gps_distance_m"] < 50

    # 3. Weigh: 28 kg estimate → 27.4 kg, within 10%.
    w = client.post(f"/api/requests/{req['id']}/weigh", json={"dealer_id": raju["id"]}).json()
    assert w["scale_kg"] == 27.4
    assert not w["gap_warning"]
    assert w["amount"] == 340

    # 4. Dealer confirms the material (pre-selected: the collector's choice) and pays.
    a = client.post(f"/api/requests/{req['id']}/approve",
                    json={"dealer_id": raju["id"], "material": "plastic"})
    assert a.status_code == 200, a.text
    for _ in range(30):
        got = client.get(f"/api/requests/{req['id']}").json()
        if got["transaction"]:
            break
        time.sleep(0.1)
    tx = got["transaction"]
    assert tx and tx["amount"] == 340 and tx["scale_kg"] == 27.4 and tx["material"] == "plastic"

    # 5. Collector sees ₹340 · 27.4 kg and a message.
    prof = client.get(f"/api/collectors/{meena['id']}").json()
    assert "₹340" in prof["messages"][0]["text"]

    # 6. Fraud 1: same photo again is blocked.
    r = new_request(client, meena["id"], img)
    assert r.status_code == 409
    assert r.json()["error"] == "This photo was already used"

    # The refused attempt is still on record for Satin, but doesn't hold her loan (no money moved).
    dup_flags = [f for f in client.get("/api/flags?status=open").json()
                 if f["rule"] == "duplicate_photo" and f["collector_id"] == meena["id"]]
    assert len(dup_flags) == 1

    # 8. Meena's profile: 642, starter loan unlocked.
    prof = client.get(f"/api/collectors/{meena['id']}").json()
    assert prof["score"]["score"] == 642, prof["score"]
    assert prof["eligibility"]["eligible"] and prof["eligibility"]["limit"] == 5000


def test_location_mismatch_blocks(client):
    collectors, dealers = ids(client)
    r = new_request(client, collectors["Sunita"]["id"], photo(2), kg=10)
    req = r.json()
    r = client.post(f"/api/requests/{req['id']}/accept",
                    json={"dealer_id": dealers["Raju"]["id"], "qr_token": collectors["Sunita"]["qr_token"],
                          "lat": RAJU[0] + 0.01, "lng": RAJU[1]})
    assert r.status_code == 403 and r.json()["rule"] == "location_mismatch"


def test_wrong_qr_blocks(client):
    collectors, dealers = ids(client)
    req = new_request(client, collectors["Sunita"]["id"], photo(3), kg=10).json()
    r = client.post(f"/api/requests/{req['id']}/accept",
                    json={"dealer_id": dealers["Raju"]["id"], "qr_token": collectors["Meena"]["qr_token"],
                          "lat": RAJU[0], "lng": RAJU[1]})
    assert r.status_code == 403


def test_cannot_pay_before_weighing(client):
    collectors, dealers = ids(client)
    req = new_request(client, collectors["Farida"]["id"], photo(4), kg=10).json()
    client.post(f"/api/requests/{req['id']}/accept",
                json={"dealer_id": dealers["Raju"]["id"], "qr_token": collectors["Farida"]["qr_token"],
                      "lat": RAJU[0], "lng": RAJU[1]})
    r = client.post(f"/api/requests/{req['id']}/approve", json={"dealer_id": dealers["Raju"]["id"]})
    assert r.status_code == 409


def test_sunita_not_yet_eligible(client):
    collectors, _ = ids(client)
    el = client.get(f"/api/collectors/{collectors['Sunita']['id']}").json()["eligibility"]
    assert not el["eligible"] and el["sales_to_unlock"] == 11


def test_ivr_path(client):
    collectors, dealers = ids(client)
    s = collectors["Sunita"]
    r = client.post("/api/ivr/start", json={"dealer_id": dealers["Raju"]["id"], "qr_token": s["qr_token"],
                                        "material": "paper", "est_kg": 12}).json()
    rid = r["request"]["id"]
    bad = signed(client, "/api/ivr/confirm",
                 {"request_id": rid, "caller_phone": "9999999999", "digit": "1"})
    assert bad.status_code == 403
    ok = signed(client, "/api/ivr/confirm",
                {"request_id": rid, "caller_phone": s["phone"], "digit": "1"})
    assert ok.json()["status"] == "accepted"


def test_open_sale_flag_holds_eligibility(client):
    collectors, _ = ids(client)
    farida = collectors["Farida"]["id"]
    el = client.get(f"/api/collectors/{farida}").json()["eligibility"]
    review = next(c for c in el["checks"] if c["key"] == "review")
    assert not el["eligible"] and not review["ok"] and "volume outlier" in review["detail"]
    flag = next(f for f in client.get("/api/flags?status=open").json()
                if f["collector_id"] == farida and f["rule"] == "volume_outlier")
    client.post(f"/api/flags/{flag['id']}", json={"status": "dismissed"})
    assert client.get(f"/api/collectors/{farida}").json()["eligibility"]["eligible"]
    assert client.post("/api/loans", json={"collector_id": collectors["Ramesh"]["id"]}).status_code == 409


def test_newcomer_consistency_is_neutral(client):
    collectors, _ = ids(client)
    c = client.get(f"/api/collectors/{collectors['Sunita']['id']}").json()["score"]["inputs"]["C"]
    assert c["value"] == 0.5


def test_confirmation_carries_voice_fields(client):
    collectors, _ = ids(client)
    msg = client.get(f"/api/collectors/{collectors['Meena']['id']}").json()["messages"][0]
    assert msg["meta"] == {"kind": "sale_confirmation", "amount": 340, "kg": 27.4,
                           "material": "plastic", "credits": 27}


def test_login_and_sessions(client):
    collectors, dealers = ids(client)
    bad = client.post("/api/auth/login", json={"role": "collector", "phone": "9810000001", "pin": "0000"})
    assert bad.status_code == 401
    assert login(client, "collector", "9810000001")["name"] == "Meena Devi"
    assert client.get("/api/auth/me?role=collector").json()["user"]["id"] == collectors["Meena"]["id"]
    # A collector can't raise a request in someone else's name.
    r = client.post("/api/requests", data={"collector_id": collectors["Sunita"]["id"], "material": "plastic",
                                           "est_kg": 5}, files={"photo": ("p.jpg", photo(9), "image/jpeg")})
    assert r.status_code == 403
    # A dealer can't act as another dealer, and nobody can act as a dealer without logging in.
    assert client.get(f"/api/dealers/{dealers['Gupta']['id']}/queue").status_code == 403
    client.post("/api/auth/logout", json={"role": "dealer"})
    assert client.get(f"/api/dealers/{dealers['Raju']['id']}/queue").status_code == 401
    login(client, "dealer", "9811000001")


def test_photo_served_from_database(client):
    collectors, _ = ids(client)
    req = new_request(client, collectors["Lakshmi"]["id"], photo(11), kg=10).json()
    r = client.get(req["photo_url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == bytes([0xFF, 0xD8])
