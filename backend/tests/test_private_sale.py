"""A sale is between one collector and one dealer.

The collector picks the shop when they raise the request; no other dealer learns the request
exists, and no other collector can read it.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app import fraud
from app.main import app
from tests.conftest import GUPTA, RAJU, ids, login, new_request, photo

GUPTA_PHONE = "9811000002"
# Far enough that no seeded dealer is within DEALER_CHOICE_MAX_M (Connaught Place, ~12 km away).
FAR = (28.6304, 77.2177)


@pytest.fixture
def gupta():
    """A second dealer, in their own browser, with nothing else signed in."""
    with TestClient(app) as c:
        login(c, "dealer", GUPTA_PHONE)
        yield c


@pytest.fixture
def as_collector(client):
    """A browser holding one collector's session and nothing else.

    The shared `client` fixture is signed in as Satin as well, and Satin is allowed to read any
    collector's sale — so testing what a *collector* may see needs a session that is only that.
    """
    opened = []

    def _open(name):
        phone = next(c["phone"] for c in client.get("/api/collectors").json()
                     if c["name"].startswith(name))
        c = TestClient(app)
        c.__enter__()
        opened.append(c)
        login(c, "collector", phone)
        return c

    try:
        yield _open
    finally:
        for c in opened:
            c.__exit__(None, None, None)


def pay_off(client, req, dealer):
    """Walk a request all the way to a paid transaction."""
    client.post(f"/api/requests/{req['id']}/weigh", json={"dealer_id": dealer["id"]})
    client.post(f"/api/requests/{req['id']}/approve", json={"dealer_id": dealer["id"]})
    for _ in range(40):
        got = client.get(f"/api/requests/{req['id']}").json()
        if got["transaction"]:
            return got
        time.sleep(0.1)
    raise AssertionError("payment never settled")


# ---------- Picking a shop ----------

def test_nearby_lists_shops_by_distance_and_hides_their_contact_details(client):
    collectors, _ = ids(client)
    login(client, "collector", next(c["phone"] for c in client.get("/api/collectors").json()
                                    if c["id"] == collectors["Meena"]["id"]))
    rows = client.get(f"/api/dealers/nearby?lat={RAJU[0]}&lng={RAJU[1]}").json()
    assert [r["shop_name"] for r in rows] == ["Raju Kabadi Store", "Gupta Scrap Traders"]
    assert rows == sorted(rows, key=lambda r: r["distance_m"])
    assert rows[0]["distance_m"] == 0
    assert 800 < rows[1]["distance_m"] < 1200          # Gupta is about 1 km from Raju
    for r in rows:
        assert set(r) == {"id", "shop_name", "distance_m", "last_used"}


def test_nearby_excludes_shops_further_than_five_km(client):
    collectors, _ = ids(client)
    login(client, "collector", next(c["phone"] for c in client.get("/api/collectors").json()
                                    if c["id"] == collectors["Meena"]["id"]))
    assert fraud.DEALER_CHOICE_MAX_M == 5000
    assert client.get(f"/api/dealers/nearby?lat={FAR[0]}&lng={FAR[1]}").json() == []
    # Just outside, then just inside, along a line of longitude.
    deg = 0.055   # ~6.1 km
    assert client.get(f"/api/dealers/nearby?lat={RAJU[0] + deg}&lng={RAJU[1]}").json() == []
    near = client.get(f"/api/dealers/nearby?lat={RAJU[0] + 0.03}&lng={RAJU[1]}").json()
    assert {r["shop_name"] for r in near} == {"Raju Kabadi Store", "Gupta Scrap Traders"}
    assert all(r["distance_m"] <= fraud.DEALER_CHOICE_MAX_M for r in near)


def test_nearby_marks_the_shop_the_collector_sold_to_last(client):
    collectors, _ = ids(client)
    login(client, "collector", next(c["phone"] for c in client.get("/api/collectors").json()
                                    if c["id"] == collectors["Meena"]["id"]))
    rows = client.get(f"/api/dealers/nearby?lat={RAJU[0]}&lng={RAJU[1]}").json()
    # Meena's most recent seeded sale is to Raju, so the demo's shop is preselected.
    assert [r["last_used"] for r in rows] == [True, False]


def test_nearby_needs_a_collector_session(client):
    login(client, "dealer", "9811000001")
    r = TestClient(app)
    with r as anon:
        assert anon.get(f"/api/dealers/nearby?lat={RAJU[0]}&lng={RAJU[1]}").status_code == 401


def test_a_request_must_name_a_shop_within_reach(client):
    collectors, _ = ids(client)
    sunita = collectors["Sunita"]["id"]
    # No shop at all.
    r = new_request(client, sunita, photo(401), kg=9, dealer_id=None)
    assert r.status_code == 400 and "shop" in r.json()["error"]
    # A shop that does not exist.
    r = new_request(client, sunita, photo(402), kg=9, dealer_id=9999)
    assert r.status_code == 404
    # A real shop, but the collector is 12 km away from it.
    r = new_request(client, sunita, photo(403), kg=9, loc=FAR, dealer_id=1)
    assert r.status_code == 403, r.text
    assert r.json()["rule"] == "dealer_too_far"
    assert r.json()["evidence"]["distance_m"] > 5000
    # Without GPS there is nothing to measure against.
    phone = next(c["phone"] for c in client.get("/api/collectors").json() if c["id"] == sunita)
    login(client, "collector", phone)
    r = client.post("/api/requests", data={"material": "plastic", "est_kg": 9, "dealer_id": 1},
                    files={"photo": ("p.jpg", photo(404), "image/jpeg")})
    assert r.status_code == 400 and r.json()["rule"] == "location_missing"


def test_the_chosen_shop_is_stored_at_creation(client):
    collectors, dealers = ids(client)
    req = new_request(client, collectors["Sunita"]["id"], photo(405), kg=9,
                      dealer_id=dealers["Gupta"]["id"], loc=GUPTA).json()
    assert req["dealer_id"] == dealers["Gupta"]["id"]
    assert req["status"] == "open"


# ---------- Another dealer learns nothing ----------

def test_another_dealer_cannot_see_or_touch_the_request(client, gupta):
    collectors, dealers = ids(client)
    meena, raju = collectors["Meena"], dealers["Raju"]
    req = new_request(client, meena["id"], photo(410), kg=9, dealer_id=raju["id"]).json()
    rid = req["id"]

    # Not in Gupta's queue…
    queue = gupta.get(f"/api/dealers/{dealers['Gupta']['id']}/queue").json()
    assert all(r["id"] != rid for r in queue), queue

    # …and 404 everywhere else, so its existence is never confirmed.
    assert gupta.get(f"/api/requests/{rid}").status_code == 404
    assert gupta.post(f"/api/requests/{rid}/accept",
                      json={"dealer_id": dealers["Gupta"]["id"], "qr_token": meena["qr_token"],
                            "lat": RAJU[0], "lng": RAJU[1]}).status_code == 404
    assert gupta.post(f"/api/demo/requests/{rid}/simulate-scan",
                      json={"lat": RAJU[0], "lng": RAJU[1]}).status_code == 404
    assert gupta.post(f"/api/requests/{rid}/weigh",
                      json={"dealer_id": dealers["Gupta"]["id"]}).status_code == 404
    assert gupta.post(f"/api/requests/{rid}/approve",
                      json={"dealer_id": dealers["Gupta"]["id"]}).status_code == 404
    assert gupta.post(f"/api/demo/requests/{rid}/ivr-confirm").status_code == 404

    # The chosen dealer still can.
    assert client.post(f"/api/demo/requests/{rid}/simulate-scan",
                       json={"lat": RAJU[0], "lng": RAJU[1]}).status_code == 200


def test_a_dealers_queue_holds_only_their_own_requests(client, gupta):
    collectors, dealers = ids(client)
    raju, gupta_d = dealers["Raju"], dealers["Gupta"]
    to_raju = new_request(client, collectors["Sunita"]["id"], photo(411), kg=9,
                          dealer_id=raju["id"]).json()
    to_gupta = new_request(client, collectors["Lakshmi"]["id"], photo(412), kg=9,
                           dealer_id=gupta_d["id"], loc=GUPTA).json()

    raju_queue = {r["id"] for r in client.get(f"/api/dealers/{raju['id']}/queue").json()}
    gupta_queue = {r["id"] for r in gupta.get(f"/api/dealers/{gupta_d['id']}/queue").json()}
    assert to_raju["id"] in raju_queue and to_raju["id"] not in gupta_queue
    assert to_gupta["id"] in gupta_queue and to_gupta["id"] not in raju_queue
    # Every row in a queue names that dealer, with no broadcast left.
    for row in client.get(f"/api/dealers/{raju['id']}/queue").json():
        assert row["dealer_id"] == raju["id"]


def test_a_collector_cannot_read_another_collectors_request(client, as_collector):
    collectors, _ = ids(client)
    req = new_request(client, collectors["Lakshmi"]["id"], photo(413), kg=9).json()
    sunita = as_collector("Sunita")
    assert sunita.get(f"/api/requests/{req['id']}").status_code == 404
    assert sunita.post(f"/api/requests/{req['id']}/cancel").status_code == 404
    # Nor does it turn up in their own list.
    assert all(r["id"] != req["id"] for r in sunita.get("/api/collectors/me/requests").json())
    # Its owner can still read it.
    assert as_collector("Lakshmi").get(f"/api/requests/{req['id']}").status_code == 200


# ---------- The collector's own list ----------

def test_the_collectors_list_follows_a_sale_through_to_paid(client):
    collectors, dealers = ids(client)
    sunita, raju = collectors["Sunita"], dealers["Raju"]
    req = new_request(client, sunita["id"], photo(420), kg=10, dealer_id=raju["id"]).json()
    rid = req["id"]

    def mine():
        return next(r for r in client.get("/api/collectors/me/requests").json() if r["id"] == rid)

    row = mine()
    assert row["status"] == "open"
    assert row["shop_name"] == "Raju Kabadi Store"
    assert row["amount"] is None
    assert row["created_at"] and row["expires_at"]

    client.post(f"/api/requests/{rid}/accept", json={"dealer_id": raju["id"],
                "qr_token": sunita["qr_token"], "lat": RAJU[0], "lng": RAJU[1]})
    assert mine()["status"] == "accepted"
    client.post(f"/api/requests/{rid}/weigh", json={"dealer_id": raju["id"]})
    assert mine()["status"] == "weighed"
    client.post(f"/api/requests/{rid}/approve", json={"dealer_id": raju["id"]})

    # "paying" settles on the next look, so the list itself nudges the mock payment along.
    for _ in range(40):
        row = mine()
        if row["status"] == "completed":
            break
        assert row["status"] in ("paying", "completed")
        time.sleep(0.1)
    assert row["status"] == "completed"
    assert row["amount"] == round(row["scale_kg"] * 12.4)
    assert row["shop_name"] == "Raju Kabadi Store"


def test_cancel_works_for_the_owner_while_the_request_is_open(client):
    collectors, dealers = ids(client)
    farida, raju = collectors["Farida"], dealers["Raju"]
    req = new_request(client, farida["id"], photo(421), kg=9, dealer_id=raju["id"]).json()
    r = client.post(f"/api/requests/{req['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    # Cancelling twice, and cancelling once a dealer has it, both refuse.
    assert client.post(f"/api/requests/{req['id']}/cancel").status_code == 409
    assert client.post(f"/api/requests/{req['id']}/accept",
                       json={"dealer_id": raju["id"], "qr_token": farida["qr_token"],
                             "lat": RAJU[0], "lng": RAJU[1]}).status_code == 409

    taken = new_request(client, farida["id"], photo(422), kg=9, dealer_id=raju["id"]).json()
    client.post(f"/api/requests/{taken['id']}/accept",
                json={"dealer_id": raju["id"], "qr_token": farida["qr_token"],
                      "lat": RAJU[0], "lng": RAJU[1]})
    phone = next(c["phone"] for c in client.get("/api/collectors").json() if c["id"] == farida["id"])
    login(client, "collector", phone)
    assert client.post(f"/api/requests/{taken['id']}/cancel").status_code == 409


def test_a_cancelled_request_leaves_the_dealers_queue(client):
    collectors, dealers = ids(client)
    raju = dealers["Raju"]
    req = new_request(client, collectors["Sunita"]["id"], photo(423), kg=9,
                      dealer_id=raju["id"]).json()
    assert any(r["id"] == req["id"] for r in client.get(f"/api/dealers/{raju['id']}/queue").json())
    client.post(f"/api/requests/{req['id']}/cancel")
    assert all(r["id"] != req["id"] for r in client.get(f"/api/dealers/{raju['id']}/queue").json())


# ---------- Satin ----------

def test_satin_sees_completed_sales_but_not_ones_in_flight(client, as_collector):
    collectors, dealers = ids(client)
    lakshmi, raju = collectors["Lakshmi"], dealers["Raju"]
    open_req = new_request(client, lakshmi["id"], photo(430), kg=9, dealer_id=raju["id"]).json()
    done = new_request(client, lakshmi["id"], photo(431), kg=9, dealer_id=raju["id"]).json()
    client.post(f"/api/requests/{done['id']}/accept", json={"dealer_id": raju["id"],
                "qr_token": lakshmi["qr_token"], "lat": RAJU[0], "lng": RAJU[1]})
    pay_off(client, done, raju)

    # The collector sees both; Satin sees only the one that completed.
    own = {r["id"] for r in as_collector("Lakshmi")
           .get(f"/api/collectors/{lakshmi['id']}").json()["requests"]}
    assert {open_req["id"], done["id"]} <= own

    with TestClient(app) as s:
        login(s, "satin", "9812000001")
        satin_view = s.get(f"/api/collectors/{lakshmi['id']}").json()
    seen = {r["id"] for r in satin_view["requests"]}
    assert done["id"] in seen
    assert open_req["id"] not in seen
    assert all(r["status"] == "completed" for r in satin_view["requests"])
    # The completed sale is still in the transactions Satin scores on.
    assert any(t["request_id"] == done["id"] for t in satin_view["transactions"])


# ---------- The demo script is unchanged ----------

def test_the_scripted_sale_still_lands_on_642(client):
    collectors, dealers = ids(client)
    meena, raju = collectors["Meena"], dealers["Raju"]
    req = new_request(client, meena["id"], photo(1), dealer_id=raju["id"]).json()
    client.post(f"/api/demo/requests/{req['id']}/simulate-scan",
                json={"lat": RAJU[0] + 0.0001, "lng": RAJU[1]})
    w = client.post(f"/api/requests/{req['id']}/weigh", json={"dealer_id": raju["id"]}).json()
    assert w["scale_kg"] == 27.4 and w["amount"] == 340
    client.post(f"/api/requests/{req['id']}/approve",
                json={"dealer_id": raju["id"], "material": "plastic"})
    for _ in range(40):
        got = client.get(f"/api/requests/{req['id']}").json()
        if got["transaction"]:
            break
        time.sleep(0.1)
    assert got["transaction"]["amount"] == 340
    prof = client.get(f"/api/collectors/{meena['id']}").json()
    assert prof["score"]["score"] == 642, prof["score"]
    assert prof["eligibility"]["eligible"] and prof["eligibility"]["limit"] == 5000
