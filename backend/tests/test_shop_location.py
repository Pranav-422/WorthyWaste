"""A dealer pins their shop from their phone; collectors near that spot can then pick it."""
from fastapi.testclient import TestClient

from app import main
from tests.conftest import MEENA_PHONE, login, reset

# Somewhere far from the seeded Delhi shops (Lucknow), so the list there starts empty.
FAR = {"lat": 26.8467, "lng": 80.9462}


def test_a_dealer_pins_their_shop_and_nearby_collectors_can_pick_it(client):
    reset(client)
    with TestClient(main.app) as meena, TestClient(main.app) as gupta:
        login(meena, "collector", MEENA_PHONE)
        login(gupta, "dealer", "9811000002")
        assert meena.get("/api/dealers/nearby", params=FAR).json() == []

        r = gupta.post("/api/dealers/me/location", json={**FAR, "accuracy_m": 12})
        assert r.status_code == 200, r.text
        assert r.json()["location_set_at"]
        assert gupta.get("/api/dealers/2").json()["dealer"]["location_set_at"]

        near = meena.get("/api/dealers/nearby", params=FAR).json()
        assert [d["shop_name"] for d in near] == ["Gupta Scrap Traders"]
        assert near[0]["distance_m"] == 0


def test_a_coarse_or_empty_gps_fix_is_refused(client):
    reset(client)
    with TestClient(main.app) as gupta:
        login(gupta, "dealer", "9811000002")
        # A laptop's Wi-Fi fix (±167 m) is fine for a 5 km shop list; only a very coarse one is refused.
        assert gupta.post("/api/dealers/me/location", json={**FAR, "accuracy_m": 167}).status_code == 200
        r = gupta.post("/api/dealers/me/location", json={**FAR, "accuracy_m": 2500})
        assert r.status_code == 400 and r.json()["rule"] == "gps_inaccurate"
        assert gupta.post("/api/dealers/me/location", json={"lat": 0, "lng": 0}).status_code == 400
        assert gupta.post("/api/dealers/me/location", json={"lat": 123, "lng": 0}).status_code == 422


def test_only_a_dealer_can_pin_a_shop(client):
    with TestClient(main.app) as anon, TestClient(main.app) as meena:
        assert anon.post("/api/dealers/me/location", json=FAR).status_code == 401
        login(meena, "collector", MEENA_PHONE)
        assert meena.post("/api/dealers/me/location", json=FAR).status_code == 401
