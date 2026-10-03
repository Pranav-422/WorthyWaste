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
