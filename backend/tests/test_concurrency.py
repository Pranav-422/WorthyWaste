"""Problem 6: the same request must not be accepted or paid twice.

The in-process lock in main.py cannot help here — on Vercel each request may land on a different
instance with its own database connection. Every state change is therefore a guarded UPDATE, and the
loser of a race sees 409. The Postgres test at the bottom runs two real connections at once, which
is the only way to exercise that guard rather than the lock.
"""
import threading
import time

import pytest

from app import db as dbmod
from app import services
from app.services import ApiError
from tests.conftest import RAJU, ids, new_request, photo, signed


def accepted(client, req, dealer, collector, **kw):
    return client.post(f"/api/requests/{req['id']}/accept",
                       json={"dealer_id": dealer["id"], "qr_token": collector["qr_token"],
                             "lat": RAJU[0], "lng": RAJU[1], **kw})


def test_a_request_can_only_be_accepted_once(client):
    collectors, dealers = ids(client)
    sunita, raju = collectors["Sunita"], dealers["Raju"]
    req = new_request(client, sunita["id"], photo(301), kg=9).json()
    assert accepted(client, req, raju, sunita).status_code == 200
    second = accepted(client, req, raju, sunita)
    assert second.status_code == 409, second.text


def test_weighing_stops_once_the_sale_is_being_paid(client):
    collectors, dealers = ids(client)
    sunita, raju = collectors["Sunita"], dealers["Raju"]
    req = new_request(client, sunita["id"], photo(302), kg=9).json()
    accepted(client, req, raju, sunita)
    # Re-weighing before payment is allowed on purpose: the scrap can go back on the scale.
    assert client.post(f"/api/requests/{req['id']}/weigh", json={"dealer_id": raju["id"]}).status_code == 200
    assert client.post(f"/api/requests/{req['id']}/weigh", json={"dealer_id": raju["id"]}).status_code == 200
    assert client.post(f"/api/requests/{req['id']}/approve", json={"dealer_id": raju["id"]}).status_code == 200
    late = client.post(f"/api/requests/{req['id']}/weigh", json={"dealer_id": raju["id"]})
    assert late.status_code == 409, late.text


def test_approving_twice_pays_once(client):
    collectors, dealers = ids(client)
    lakshmi, raju = collectors["Lakshmi"], dealers["Raju"]
    req = new_request(client, lakshmi["id"], photo(303), kg=9).json()
    accepted(client, req, raju, lakshmi)
    client.post(f"/api/requests/{req['id']}/weigh", json={"dealer_id": raju["id"]})
    first = client.post(f"/api/requests/{req['id']}/approve", json={"dealer_id": raju["id"]})
    second = client.post(f"/api/requests/{req['id']}/approve", json={"dealer_id": raju["id"]})
    assert first.status_code == second.status_code == 200
    # The repeat tap shows the payment already running instead of starting a second transfer.
    assert first.json()["payment"]["provider_ref"] == second.json()["payment"]["provider_ref"]

    for _ in range(30):
        got = client.get(f"/api/requests/{req['id']}").json()
        if got["transaction"]:
            break
        time.sleep(0.1)
    assert got["transaction"]
    paid = [t for t in client.get(f"/api/dealers/{raju['id']}").json()["log"]
            if t["request_id"] == req["id"]]
    assert len(paid) == 1


def test_a_replayed_webhook_books_the_sale_once(client):
    collectors, dealers = ids(client)
    farida, raju = collectors["Farida"], dealers["Raju"]
    req = new_request(client, farida["id"], photo(304), kg=9).json()
    accepted(client, req, raju, farida)
    client.post(f"/api/requests/{req['id']}/weigh", json={"dealer_id": raju["id"]})
    ref = client.post(f"/api/requests/{req['id']}/approve",
                      json={"dealer_id": raju["id"]}).json()["payment"]["provider_ref"]

    first = signed(client, "/api/payments/webhook", {"provider_ref": ref, "status": "success"})
    assert first.status_code == 200 and first.json()["transaction"]
    # Providers retry. The second delivery must not create a second transaction or more credits.
    credits = client.get(f"/api/collectors/{farida['id']}").json()["collector"]["credits"]
    for _ in range(3):
        again = signed(client, "/api/payments/webhook", {"provider_ref": ref, "status": "success"})
        assert again.status_code == 200 and again.json().get("duplicate") is True
    assert client.get(f"/api/collectors/{farida['id']}").json()["collector"]["credits"] == credits
    paid = [t for t in client.get(f"/api/dealers/{raju['id']}").json()["log"]
            if t["request_id"] == req["id"]]
    assert len(paid) == 1


def test_an_ivr_keypress_counts_once(client):
    collectors, dealers = ids(client)
    sunita, raju = collectors["Sunita"], dealers["Raju"]
    started = client.post("/api/ivr/start",
                          json={"dealer_id": raju["id"], "qr_token": sunita["qr_token"],
                                "material": "paper", "est_kg": 11}).json()
    rid = started["request"]["id"]
    body = {"request_id": rid, "caller_phone": sunita["phone"], "digit": "1"}
    assert signed(client, "/api/ivr/confirm", body).status_code == 200
    assert signed(client, "/api/ivr/confirm", body).status_code == 409


# ---------- The guard itself ----------

def test_the_guard_matches_nothing_once_the_state_has_moved(client):
    """What makes a second accept or a retried webhook harmless, at the level it works on.

    Each state change is `UPDATE ... WHERE id = ? AND <expected state>`, run on its own connection
    in autocommit. Once the row has moved on, the same statement matches no row — and matching no
    row is what services.py turns into a 409. Drop the `AND` and the second call here claims the
    sale all over again.
    """
    collectors, dealers = ids(client)
    sunita, raju = collectors["Sunita"], dealers["Raju"]
    req = new_request(client, sunita["id"], photo(311), kg=9).json()
    conn = dbmod.connect()

    take = "UPDATE sale_requests SET status='accepted', dealer_id=? WHERE id=? AND status='open'"
    assert conn.execute(take, (raju["id"], req["id"])).rowcount == 1
    assert conn.execute(take, (raju["id"], req["id"])).rowcount == 0

    # Weighing again before payment is deliberate — the scrap can go back on the scale.
    weigh = ("UPDATE sale_requests SET status='weighed', scale_kg=9 "
             "WHERE id=? AND status IN ('accepted','weighed')")
    assert conn.execute(weigh, (req["id"],)).rowcount == 1
    assert conn.execute(weigh, (req["id"],)).rowcount == 1

    ref = client.post(f"/api/requests/{req['id']}/approve",
                      json={"dealer_id": raju["id"]}).json()["payment"]["provider_ref"]
    assert conn.execute(weigh, (req["id"],)).rowcount == 0   # now paying: too late to re-weigh

    settle = "UPDATE payments SET status='success' WHERE provider_ref=? AND status='pending'"
    assert conn.execute(settle, (ref,)).rowcount == 1
    assert conn.execute(settle, (ref,)).rowcount == 0


# ---------- Two threads, as the brief asks (Postgres only) ----------

@pytest.mark.skipif(not dbmod.DATABASE_URL, reason="needs Postgres: set DATABASE_URL")
def test_two_connections_accepting_at_once_only_one_wins(client):
    """Two Vercel instances taking the same request at the same moment.

    Each thread gets its own connection, so main.py's process-wide lock is out of the picture.
    Note that PGlite (the local stand-in for Neon) runs transactions one at a time, so the two
    really overlap only against a real Postgres — which is why the guard also has the direct test
    above, and why Pranav re-runs the double-accept check on the preview deploy.
    """
    collectors, dealers = ids(client)
    meena, raju = collectors["Meena"], dealers["Raju"]
    req = new_request(client, meena["id"], photo(310), kg=9).json()
    assert req["status"] == "open"

    gate = threading.Barrier(2, timeout=20)
    results: list = []
    lock = threading.Lock()

    def take():
        conn = dbmod.connect()
        try:
            gate.wait()
            with dbmod.transaction(conn):
                services.accept_request(conn, req["id"], dealer_id=raju["id"],
                                        qr_token=meena["qr_token"], lat=RAJU[0], lng=RAJU[1])
            outcome = "accepted"
        except ApiError as e:
            outcome = e.status
        except Exception as e:  # noqa: BLE001 - reported, so a surprise cannot pass as success
            outcome = f"{type(e).__name__}: {e}"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=take) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive(), "a racing accept never finished"

    assert results.count("accepted") == 1, results
    assert results.count(409) == 1, results
    assert client.get(f"/api/requests/{req['id']}").json()["request"]["status"] == "accepted"
