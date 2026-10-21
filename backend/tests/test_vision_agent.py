"""The vision agent in the pickup flow, with a fake Lambda: retake, hold for a person, review, fallback."""
import pytest
from fastapi.testclient import TestClient

from app import adapters, main
from tests.conftest import RAJU, SATIN_PHONE, login, photo, reset
from tests.test_doorstep import OPS_PHONE, SUNIL_PHONE, fresh_home, household_id, scan


class FakeVision:
    def __init__(self):
        self.next: dict | Exception = {}
        self.calls: list[tuple] = []

    def analyze(self, jpeg, *, marked, attempt, source, ref=None, return_safe=False):
        self.calls.append(("analyze", marked, attempt, source))
        if isinstance(self.next, Exception):
            raise self.next
        return {"run_id": f"run{len(self.calls)}", "trace": [{"kind": "decision", "title": "x"}],
                "result": {"confidence": 0.9}, "image_urls": {}, "message": "msg", **self.next}

    def call(self, method, path, body=None, timeout=40):
        self.calls.append((method, path, body))
        return {"ok": True, "source": "demo"}


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        reset(c)
        yield c


@pytest.fixture
def vision(monkeypatch):
    v = FakeVision()
    monkeypatch.setattr(adapters, "vision", v)
    return v


def points(phone):
    return main._db.execute("SELECT points FROM households WHERE phone = ?", (phone,)).fetchone()[0]


def test_a_photo_it_cannot_judge_asks_for_a_retake(client, vision):
    qr = fresh_home("9814900201")
    login(client, "collector", SUNIL_PHONE)
    vision.next = {"action": "recapture", "message": "Photo is blurry. Take the photo again."}
    r = scan(client, qr, img=photo(901))
    assert r.status_code == 422 and r.json()["rule"] == "recapture" and r.json()["evidence"]["trace"]
    hid = household_id("9814900201")
    assert main._db.execute("SELECT COUNT(*) FROM pickups WHERE household_id = ?", (hid,)).fetchone()[0] == 0
    # the second photo is judged; the attempt number reaches the agent
    vision.next = {"action": "accept", "segregation": "separated"}
    r = client.post("/api/pickups", data={"door_qr": qr, "segregation": "separated", "lat": RAJU[0],
                                           "lng": RAJU[1], "attempt": 2}, files={"photo": ("w.jpg", photo(902), "image/jpeg")})
    assert r.status_code == 201, r.text
    assert vision.calls[-1][2] == 2 and r.json()["points"] > 0 and not r.json()["held"]


def test_disagreement_holds_points_until_a_person_decides(client, vision):
    phone = "9814900202"
    qr = fresh_home(phone)
    login(client, "collector", SUNIL_PHONE)
    vision.next = {"action": "needs_approval", "segregation": "separated"}
    before = points(phone)
    r = scan(client, qr, img=photo(903)).json()
    assert r["held"] and r["points"] == 0 and r["pickup"]["review"] == "pending" and points(phone) == before

    login(client, "ops", OPS_PHONE)
    queue = client.get("/api/ops/reviews").json()
    assert any(p["id"] == r["pickup"]["id"] for p in queue)
    done = client.post(f"/api/ops/reviews/{r['pickup']['id']}", json={"mixed": False})
    assert done.status_code == 200 and done.json()["points_released"] > 0 and points(phone) > before
    assert ("POST", "/runs/run1/review") in [c[:2] for c in vision.calls]  # the human step reaches the trace
    assert client.post(f"/api/ops/reviews/{r['pickup']['id']}", json={"mixed": True}).status_code == 409


def test_reviewer_agrees_with_the_camera(client, vision):
    qr = fresh_home("9814900203")
    login(client, "collector", SUNIL_PHONE)
    vision.next = {"action": "needs_approval", "segregation": "separated"}
    pid = scan(client, qr, img=photo(904)).json()["pickup"]["id"]
    login(client, "ops", OPS_PHONE)
    p = client.post(f"/api/ops/reviews/{pid}", json={"mixed": True}).json()
    assert p["segregation"] == "mixed" and p["points_released"] == 0
    login(client, "satin", SATIN_PHONE)
    flags = [f for f in client.get("/api/flags").json() if f["rule"] == "vision_mismatch"]
    assert flags and str(pid) in flags[0]["detail"]


def test_vision_down_records_as_marked_and_holds(client, vision):
    qr = fresh_home("9814900204")
    login(client, "collector", SUNIL_PHONE)
    vision.next = adapters.VisionError("timeout")
    r = scan(client, qr, img=photo(905))
    assert r.status_code == 201 and r.json()["held"] and r.json()["pickup"]["vision_action"] == "accept_unverified"


def test_ops_routes_need_ops(client, vision):
    login(client, "collector", SUNIL_PHONE)
    client.cookies.clear()
    assert client.get("/api/ops/reviews").status_code == 401
    assert client.post("/api/ops/reviews/1", json={"mixed": True}).status_code == 401


def test_demo_endpoint_without_vision_says_so(client, monkeypatch):
    monkeypatch.setattr(adapters, "vision", None)
    r = client.post("/api/vision/analyze", files={"photo": ("w.jpg", photo(906), "image/jpeg")})
    assert r.status_code == 503 and r.json()["rule"] == "vision_off"


def test_a_refused_scan_never_reaches_vision(client, vision):
    qr = fresh_home("9814900205")
    login(client, "collector", SUNIL_PHONE)
    far = (RAJU[0] + 0.01, RAJU[1])  # ~1 km away
    r = client.post("/api/pickups", data={"door_qr": qr, "segregation": "separated", "lat": far[0], "lng": far[1]},
                    files={"photo": ("w.jpg", photo(911), "image/jpeg")})
    assert r.status_code == 403 and r.json()["rule"] == "gps_far_from_home"
    assert not [c for c in vision.calls if c[0] == "analyze"]  # no Lambda run, no photo stored on AWS


def test_a_disputed_pickup_leaves_the_review_queue(client, vision):
    phone = "9814900206"
    qr = fresh_home(phone)
    login(client, "collector", SUNIL_PHONE)
    vision.next = {"action": "needs_approval", "segregation": "separated"}
    pid = scan(client, qr, img=photo(912)).json()["pickup"]["id"]
    login(client, "household", phone)
    assert client.post(f"/api/households/me/pickups/{pid}/dispute", json={}).status_code == 200
    login(client, "ops", OPS_PHONE)
    assert all(p["id"] != pid for p in client.get("/api/ops/reviews").json())
    assert client.post(f"/api/ops/reviews/{pid}", json={"mixed": True}).status_code == 409


def test_an_old_database_with_double_policies_still_starts():
    """Before the unique index, a double tap could enrol a collector twice; init_db must not crash on that."""
    from app.db import Database, init_db

    db = Database(path=":memory:")
    init_db(db)
    db.execute("DROP INDEX idx_policy_active")
    db.execute("PRAGMA foreign_keys = OFF")
    for _ in range(2):
        db.execute("INSERT INTO insurance_policies (collector_id, partner, cover, monthly_premium, commission_pct, "
                   "status, started_at) VALUES (1, 'p', 1, 1, 0.1, 'active', 'x')")
    init_db(db)  # the next start
    assert db.execute("SELECT COUNT(*) FROM insurance_policies WHERE status = 'active'").fetchone()[0] == 1
