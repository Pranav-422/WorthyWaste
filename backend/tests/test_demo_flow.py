"""Runs the Design Doc's demo click path end to end against a fresh database."""
import io
import os
import random
import tempfile
import time

import pytest

os.environ["WW_SCRIPTED"] = "1"
os.environ["WW_DATA_DIR"] = tempfile.mkdtemp(prefix="ww-test-")
os.environ.pop("WW_DB", None)

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402

RAJU = (28.67312, 77.28654)


def photo(seed: int) -> bytes:
    rng = random.Random(seed)
    img = Image.new("RGB", (64, 64))
    img.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(64 * 64)])
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        c.post("/demo/reset")
        yield c


def ids(client):
    collectors = {c["name"].split()[0]: c for c in client.get("/collectors").json()}
    dealers = {d["shop_name"].split()[0]: d for d in client.get("/dealers").json()}
    return collectors, dealers


def new_request(client, cid, img, kg=28, loc=RAJU):
    return client.post("/requests", data={"collector_id": cid, "material": "plastic", "est_kg": kg,
                                          "lat": loc[0], "lng": loc[1]},
                       files={"photo": ("p.jpg", img, "image/jpeg")})


def test_seeded_frauds_present(client):
    rules = {f["rule"] for f in client.get("/flags?status=open").json()}
    assert {"circular_payment", "mass_balance", "volume_outlier"} <= rules
    circ = next(f for f in client.get("/flags").json() if f["rule"] == "circular_payment")
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
    r = client.post(f"/requests/{req['id']}/accept",
                    json={"dealer_id": raju["id"], "qr_token": meena["qr_token"], "lat": RAJU[0] + 0.0001,
                          "lng": RAJU[1]})
    assert r.status_code == 200, r.text
    assert r.json()["gps_distance_m"] < 50

    # 3. Weigh: 28 kg estimate → 27.4 kg, within 10%.
    w = client.post(f"/requests/{req['id']}/weigh", json={"dealer_id": raju["id"]}).json()
    assert w["scale_kg"] == 27.4
    assert not w["gap_warning"]
    assert w["amount"] == 340

    # 4. Approve and pay → mock webhook creates the transaction.
    a = client.post(f"/requests/{req['id']}/approve", json={"dealer_id": raju["id"]})
    assert a.status_code == 200, a.text
    for _ in range(30):
        got = client.get(f"/requests/{req['id']}").json()
        if got["transaction"]:
            break
        time.sleep(0.1)
    tx = got["transaction"]
    assert tx and tx["amount"] == 340 and tx["scale_kg"] == 27.4

    # 5. Collector sees ₹340 · 27.4 kg and a message.
    prof = client.get(f"/collectors/{meena['id']}").json()
    assert "₹340" in prof["messages"][0]["text"]

    # 6. Fraud 1: same photo again is blocked.
    r = new_request(client, meena["id"], img)
    assert r.status_code == 409
    assert r.json()["error"] == "This photo was already used"

    # 8. Meena's profile: 642, starter loan unlocked.
    prof = client.get(f"/collectors/{meena['id']}").json()
    assert prof["score"]["score"] == 642, prof["score"]
    assert prof["eligibility"]["eligible"] and prof["eligibility"]["limit"] == 5000


def test_location_mismatch_blocks(client):
    collectors, dealers = ids(client)
    r = new_request(client, collectors["Sunita"]["id"], photo(2), kg=10)
    req = r.json()
    r = client.post(f"/requests/{req['id']}/accept",
                    json={"dealer_id": dealers["Raju"]["id"], "qr_token": collectors["Sunita"]["qr_token"],
                          "lat": RAJU[0] + 0.01, "lng": RAJU[1]})
    assert r.status_code == 403 and r.json()["rule"] == "location_mismatch"


def test_wrong_qr_blocks(client):
    collectors, dealers = ids(client)
    req = new_request(client, collectors["Sunita"]["id"], photo(3), kg=10).json()
    r = client.post(f"/requests/{req['id']}/accept",
                    json={"dealer_id": dealers["Raju"]["id"], "qr_token": collectors["Meena"]["qr_token"],
                          "lat": RAJU[0], "lng": RAJU[1]})
    assert r.status_code == 403


def test_cannot_pay_before_weighing(client):
    collectors, dealers = ids(client)
    req = new_request(client, collectors["Farida"]["id"], photo(4), kg=10).json()
    client.post(f"/requests/{req['id']}/accept",
                json={"dealer_id": dealers["Raju"]["id"], "qr_token": collectors["Farida"]["qr_token"],
                      "lat": RAJU[0], "lng": RAJU[1]})
    r = client.post(f"/requests/{req['id']}/approve", json={"dealer_id": dealers["Raju"]["id"]})
    assert r.status_code == 409


def test_sunita_not_yet_eligible(client):
    collectors, _ = ids(client)
    el = client.get(f"/collectors/{collectors['Sunita']['id']}").json()["eligibility"]
    assert not el["eligible"] and el["sales_to_unlock"] == 11


def test_ivr_path(client):
    collectors, dealers = ids(client)
    s = collectors["Sunita"]
    r = client.post("/ivr/start", json={"dealer_id": dealers["Raju"]["id"], "qr_token": s["qr_token"],
                                        "material": "paper", "est_kg": 12}).json()
    rid = r["request"]["id"]
    bad = client.post("/ivr/confirm", json={"request_id": rid, "caller_phone": "9999999999", "digit": "1"})
    assert bad.status_code == 403
    ok = client.post("/ivr/confirm", json={"request_id": rid, "caller_phone": s["phone"], "digit": "1"})
    assert ok.json()["status"] == "accepted"
