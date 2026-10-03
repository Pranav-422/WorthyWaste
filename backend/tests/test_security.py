"""Problems 1–4: the demo's open doors, closed.

Each test here is the automated form of one of the manual checks in the PR description.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import (DEMO_KEY_HEADER, MEENA_PHONE, RAJU, RAJU_PHONE, SATIN_PHONE,
                            env, ids, login, new_request, photo, signed)


@pytest.fixture
def anon():
    """A client with no cookies at all: the drive-by attacker."""
    with TestClient(app) as c:
        yield c


# ---------- Problem 1: anyone could wipe the demo data ----------

def test_reset_needs_the_demo_key(anon):
    assert anon.post("/api/demo/reset").status_code == 403
    assert anon.post("/api/demo/reset", headers={"X-Demo-Key": "guess"}).status_code == 403
    with env(WW_DEMO_KEY=None):
        # No key configured must not mean "no key needed".
        assert anon.post("/api/demo/reset", headers=DEMO_KEY_HEADER).status_code == 403


def test_reset_is_off_unless_switched_on(anon):
    with env(WW_ALLOW_RESET="0"):
        r = anon.post("/api/demo/reset", headers=DEMO_KEY_HEADER)
    assert r.status_code == 403 and "disabled" in r.json()["error"]


def test_reset_works_with_the_key(anon):
    assert anon.post("/api/demo/reset", headers=DEMO_KEY_HEADER).status_code == 200


# ---------- Problem 2: the Satin dashboard and its actions ----------

SATIN_GETS = ["/api/collectors", "/api/flags", "/api/flags?status=open", "/api/groups",
              "/api/satin/overview"]
SATIN_POSTS = [("/api/scores/recompute", {}), ("/api/loans", {"collector_id": 1}),
               ("/api/flags/1", {"status": "dismissed"})]


@pytest.mark.parametrize("path", SATIN_GETS)
def test_satin_reads_need_a_satin_session(anon, path):
    assert anon.get(path).status_code == 401


@pytest.mark.parametrize("path,body", SATIN_POSTS)
def test_satin_actions_need_a_satin_session(anon, path, body):
    assert anon.post(path, json=body).status_code == 401


def test_a_dealer_session_is_not_a_satin_session(anon):
    login(anon, "dealer", RAJU_PHONE)
    for path in SATIN_GETS:
        assert anon.get(path).status_code == 401, path
    assert anon.post("/api/loans", json={"collector_id": 1}).status_code == 401


def test_batch_trace_needs_satin(anon):
    code = "WW-D01-PLA-000000-001"
    # Refused before the batch is even looked up; with a Satin session it gets as far as "no such batch".
    assert anon.get(f"/api/batches/{code}").status_code == 401
    login(anon, "satin", SATIN_PHONE)
    assert anon.get(f"/api/batches/{code}").status_code == 404


def test_a_collector_profile_is_for_that_collector_or_satin(anon, client):
    collectors, _ = ids(client)
    meena, sunita = collectors["Meena"]["id"], collectors["Sunita"]["id"]
    assert anon.get(f"/api/collectors/{meena}").status_code == 401
    login(anon, "collector", MEENA_PHONE)
    assert anon.get(f"/api/collectors/{meena}").status_code == 200
    assert anon.get(f"/api/collectors/{sunita}").status_code == 403
    login(anon, "satin", SATIN_PHONE)
    assert anon.get(f"/api/collectors/{sunita}").status_code == 200


def test_a_dealer_never_learns_a_collectors_qr_token_phone_or_upi(anon, client):
    collectors, dealers = ids(client)
    meena = collectors["Meena"]
    login(anon, "dealer", RAJU_PHONE)
    # Satin's own views carry the identifying fields; a dealer cannot reach them at all.
    assert {"qr_token", "phone"} <= meena.keys()
    assert "upi_vpa" in client.get(f"/api/collectors/{meena['id']}").json()["collector"]
    # A dealer session is neither the collector's nor Satin's, so the profile is simply not theirs.
    assert anon.get(f"/api/collectors/{meena['id']}").status_code == 401

    card = anon.get(f"/api/collectors/by-qr/{meena['qr_token']}")
    assert card.status_code == 200
    body = card.json()
    assert body["name"] == "Meena Devi"
    assert not ({"qr_token", "phone", "upi_vpa", "pin_hash", "id_ref_hash"} & body.keys())

    # The request queue a dealer works from carries names, not contact details.
    req = new_request(client, meena["id"], photo(201), kg=9)
    assert req.status_code == 201, req.text
    queue = anon.get(f"/api/dealers/{dealers['Raju']['id']}/queue").json()
    row = next(r for r in queue if r["id"] == req.json()["id"])
    assert row["collector_name"] == "Meena Devi"
    assert not ({"qr_token", "phone", "upi_vpa"} & row.keys())

    # And the public dealer list keeps dealers' own contact details out of it.
    for d in anon.get("/api/dealers").json():
        assert not ({"phone", "upi_vpa", "pin_hash"} & d.keys())


def test_a_sale_cannot_be_read_by_a_stranger(anon, client):
    collectors, _ = ids(client)
    req = new_request(client, collectors["Lakshmi"]["id"], photo(202), kg=9).json()
    assert anon.get(f"/api/requests/{req['id']}").status_code == 403
    login(anon, "collector", MEENA_PHONE)
    assert anon.get(f"/api/requests/{req['id']}").status_code == 403
    login(anon, "satin", SATIN_PHONE)
    assert anon.get(f"/api/requests/{req['id']}").status_code == 200


def test_satin_can_log_in_with_phone_and_pin(anon):
    user = login(anon, "satin", SATIN_PHONE)
    assert user["name"] == "Priya Sharma"
    assert anon.get("/api/auth/me?role=satin").json()["user"]["name"] == "Priya Sharma"
    assert anon.post("/api/auth/login",
                     json={"role": "satin", "phone": SATIN_PHONE, "pin": "0000"}).status_code == 401


# ---------- Problem 3: the provider endpoints ----------

PROVIDER_POSTS = [
    ("/api/payments/webhook", {"provider_ref": "UPI000000000000", "status": "success"}),
    ("/api/upi/observed", {"from_vpa": "a@x", "to_vpa": "b@y", "amount": 340}),
    ("/api/ivr/confirm", {"request_id": 1, "caller_phone": "9810000001", "digit": "1"}),
]


@pytest.mark.parametrize("path,body", PROVIDER_POSTS)
def test_provider_endpoints_refuse_unsigned_calls(anon, path, body):
    assert anon.post(path, json=body).status_code == 401
    assert anon.post(path, json=body, headers={"X-Provider-Signature": "00"}).status_code == 401


@pytest.mark.parametrize("path,body", PROVIDER_POSTS)
def test_provider_endpoints_refuse_a_signature_for_a_different_body(anon, path, body):
    import json as _json

    from app import auth
    other = auth.sign_provider_body(_json.dumps({"tampered": True}).encode())
    r = anon.post(path, content=_json.dumps(body).encode(),
                  headers={"Content-Type": "application/json", "X-Provider-Signature": other})
    assert r.status_code == 401


def test_a_signed_webhook_is_accepted(anon):
    # A valid signature on an unknown payment gets past the gate and is refused on its merits.
    r = signed(anon, "/api/payments/webhook",
               {"provider_ref": "UPI999999999999", "status": "success"})
    assert r.status_code == 404 and r.json()["error"] == "Unknown payment"


def test_a_signed_upi_observation_runs_the_circular_rule(anon, client):
    r = signed(anon, "/api/upi/observed",
               {"from_vpa": "meena@okaxis", "to_vpa": "rajukabadi@okicici", "amount": 100})
    assert r.status_code == 200, r.text
    assert r.json()["event"]["amount"] == 100


def test_without_a_provider_secret_nothing_is_accepted(anon):
    body = {"provider_ref": "UPI999999999999", "status": "success"}
    with env(WW_PROVIDER_SECRET=None):
        assert anon.post("/api/payments/webhook", json=body).status_code == 401
        assert anon.post("/api/payments/webhook", json=body,
                         headers={"X-Provider-Signature": "0" * 64}).status_code == 401


def test_the_mock_settlement_still_works_without_a_signature(client):
    """services.settle_mock_payment stands in for the provider's webhook and must stay internal."""
    import time

    collectors, dealers = ids(client)
    sunita, raju = collectors["Sunita"], dealers["Raju"]
    req = new_request(client, sunita["id"], photo(203), kg=10).json()
    client.post(f"/api/requests/{req['id']}/accept",
                json={"dealer_id": raju["id"], "qr_token": sunita["qr_token"],
                      "lat": RAJU[0], "lng": RAJU[1]})
    client.post(f"/api/requests/{req['id']}/weigh", json={"dealer_id": raju["id"]})
    client.post(f"/api/requests/{req['id']}/approve", json={"dealer_id": raju["id"]})
    for _ in range(30):
        got = client.get(f"/api/requests/{req['id']}").json()
        if got["transaction"]:
            break
        time.sleep(0.1)
    assert got["transaction"], "mock UPI should still settle on the next status check"


# ---------- Problem 4: demo shortcuts off in production ----------

def test_simulate_scan_is_demo_only(client):
    collectors, _ = ids(client)
    req = new_request(client, collectors["Meena"]["id"], photo(204), kg=9).json()
    path = f"/api/demo/requests/{req['id']}/simulate-scan"
    body = {"lat": RAJU[0], "lng": RAJU[1]}
    with env(WW_DEMO_MODE=None):
        assert client.post(path, json=body).status_code == 404
    r = client.post(path, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted"


def test_simulate_scan_still_needs_a_dealer_login(anon, client):
    collectors, _ = ids(client)
    req = new_request(client, collectors["Sunita"]["id"], photo(205), kg=9).json()
    r = anon.post(f"/api/demo/requests/{req['id']}/simulate-scan",
                  json={"lat": RAJU[0], "lng": RAJU[1]})
    assert r.status_code == 401


def test_demo_ivr_confirm_is_demo_only(client):
    collectors, dealers = ids(client)
    sunita, raju = collectors["Sunita"], dealers["Raju"]
    started = client.post("/api/ivr/start", json={"dealer_id": raju["id"], "qr_token": sunita["qr_token"],
                                                  "material": "paper", "est_kg": 12}).json()
    rid = started["request"]["id"]
    with env(WW_DEMO_MODE=None):
        assert client.post(f"/api/demo/requests/{rid}/ivr-confirm").status_code == 404
    r = client.post(f"/api/demo/requests/{rid}/ivr-confirm")
    assert r.status_code == 200 and r.json()["status"] == "accepted"


def test_over_estimated_load_is_demo_only(client):
    collectors, dealers = ids(client)
    farida, raju = collectors["Farida"], dealers["Raju"]
    req = new_request(client, farida["id"], photo(206), kg=20).json()
    client.post(f"/api/requests/{req['id']}/accept",
                json={"dealer_id": raju["id"], "qr_token": farida["qr_token"],
                      "lat": RAJU[0], "lng": RAJU[1]})
    path = f"/api/requests/{req['id']}/weigh"
    with env(WW_DEMO_MODE=None):
        r = client.post(path, json={"dealer_id": raju["id"], "mode": "overstated"})
        assert r.status_code == 403
        # The real scale still works with the demo switch off.
        assert client.post(path, json={"dealer_id": raju["id"]}).status_code == 200
    assert client.post(path, json={"dealer_id": raju["id"], "mode": "overstated"}).status_code == 200


def test_demo_photo_mismatch_trigger_is_demo_only(client):
    collectors, _ = ids(client)
    sunita = collectors["Sunita"]["id"]
    with env(WW_DEMO_MODE=None):
        r = new_request(client, sunita, photo(207), kg=9, demo_ai_material="cardboard")
        assert r.status_code == 201 and r.json()["ai_verdict"] == "unchecked"
    r = new_request(client, sunita, photo(208), kg=9, demo_ai_material="cardboard")
    assert r.status_code == 409 and r.json()["rule"] == "photo_mismatch"
    assert r.json()["evidence"]["material"] == "cardboard"
    assert r.json()["evidence"]["confidence"] == 0.87
