"""Fixes from reviewing PR #1 on its Vercel preview.

1. The setup lock leaked behind a pooled Postgres URL and stalled every later cold start.
2. The photo check (a network call of up to ~8 s) ran inside the instance lock and a transaction.
3. Databases seeded before the Satin login had no branch staff to log in as.
"""
import pytest

from app import adapters
from app import db as dbmod
from app import main
from app.seed import SATIN_USERS, ensure_satin_users
from tests.conftest import MEENA_PHONE, SATIN_PHONE, ids, login, new_request, photo, reset


class LockSpyVerifier(adapters.PhotoVerifier):
    """Records whether the API's instance lock was held while the photo was being checked."""

    def __init__(self):
        self.lock_held: list[bool] = []

    def check(self, jpeg: bytes, selected_material: str):
        self.lock_held.append(main._lock.locked())
        return adapters.PhotoCheck(available=True, material=selected_material, confidence=0.95,
                                   real_scene=True, approx_quantity="one sack", notes="spy")


def test_photo_check_runs_outside_the_lock_and_transaction(client):
    reset(client)
    collectors, _ = ids(client)
    spy = LockSpyVerifier()
    before = adapters.photo_verifier
    adapters.photo_verifier = spy
    try:
        r = new_request(client, collectors["Lakshmi"]["id"], photo(701), kg=10)
    finally:
        adapters.photo_verifier = before
    assert r.status_code == 201, r.text
    assert r.json()["ai_verdict"] == "match"
    assert spy.lock_held == [False]


def test_satin_staff_are_backfilled_on_an_existing_database(client):
    reset(client)
    conn = main._db
    with dbmod.transaction(conn):
        conn.execute("DELETE FROM satin_users")
    ensure_satin_users(conn)
    ensure_satin_users(conn)  # idempotent
    assert conn.execute("SELECT COUNT(*) FROM satin_users").fetchone()[0] == len(SATIN_USERS)
    assert login(client, "satin", SATIN_PHONE)["name"] == SATIN_USERS[0][0]
    login(client, "collector", MEENA_PHONE)


@pytest.mark.skipif(not dbmod.DATABASE_URL, reason="needs Postgres: set DATABASE_URL")
def test_setup_lock_is_released_and_never_left_behind(client):
    conn = main._db

    def held():
        return conn.execute("SELECT COUNT(*) FROM pg_locks WHERE locktype = 'advisory' AND granted").fetchone()[0]

    with main._setup_lock():
        assert held() == 1
    assert held() == 0
    # A second setup can take it straight away, and a reset still works end to end.
    with main._setup_lock():
        pass
    assert held() == 0
    reset(client)
    assert held() == 0


def test_nobody_logged_in_cannot_read_a_request_without_a_dealer(client):
    """Requests from before dealer choice have dealer_id NULL. A visitor with no session at all must
    not 'match' that missing dealer."""
    reset(client)
    from app import clock
    cur = main._db.execute(
        "INSERT INTO sale_requests (collector_id, material, est_kg, lat, lng, photo_url, status, created_at, "
        "expires_at) VALUES (1, 'plastic', 20, 28.67312, 77.28654, '/api/photos/x.jpg', 'expired', ?, ?)",
        (clock.ts(), clock.ts()))
    rid = cur.lastrowid
    from fastapi.testclient import TestClient
    with TestClient(main.app) as anon:
        assert anon.get(f"/api/requests/{rid}").status_code == 404
    with TestClient(main.app) as gupta:  # a dealer, but not this request's, and nobody else's cookies
        login(gupta, "dealer", "9811000002")
        assert gupta.get(f"/api/requests/{rid}").status_code == 404
    with TestClient(main.app) as meena:
        login(meena, "collector", MEENA_PHONE)
        assert meena.get(f"/api/requests/{rid}").status_code == 200  # her own


class CountingVerifier(adapters.PhotoVerifier):
    def __init__(self):
        self.calls = 0

    def check(self, jpeg: bytes, selected_material: str):
        self.calls += 1
        return adapters.PhotoCheck(available=True, material=selected_material, confidence=0.95,
                                   real_scene=True, approx_quantity="one sack", notes="counted")


def test_a_reused_photo_is_refused_before_the_photo_check(client):
    reset(client)
    collectors, _ = ids(client)
    spy = CountingVerifier()
    before = adapters.photo_verifier
    adapters.photo_verifier = spy
    try:
        assert new_request(client, collectors["Lakshmi"]["id"], photo(801), kg=10).status_code == 201
        assert spy.calls == 1
        again = new_request(client, collectors["Lakshmi"]["id"], photo(801), kg=10)
    finally:
        adapters.photo_verifier = before
    assert again.status_code == 409 and again.json()["rule"] == "duplicate_photo"
    assert spy.calls == 1  # no model call for the reused photo
