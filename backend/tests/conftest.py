"""Shared test setup. Everything the API reads from the environment is pinned here, before
`app` is imported, so tests never depend on the developer's shell.

The photo verifier is the mock one (no GEMINI_API_KEY), so no test ever calls the network.
"""
import io
import json
import os
import random
import tempfile
from contextlib import contextmanager

import pytest

os.environ["WW_SCRIPTED"] = "1"
os.environ["WW_DATA_DIR"] = tempfile.mkdtemp(prefix="ww-test-")
os.environ.pop("WW_DB", None)
# The demo switches are on for tests, so the demo-only routes can be exercised; individual tests
# turn them off again with the `env` helper to prove they are closed in production.
os.environ["WW_DEMO_MODE"] = "1"
os.environ["WW_ALLOW_RESET"] = "1"
os.environ["WW_DEMO_KEY"] = "test-demo-key"
os.environ["WW_PROVIDER_SECRET"] = "test-provider-secret"
os.environ.pop("GEMINI_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import adapters, auth  # noqa: E402
from app.main import app  # noqa: E402

RAJU = (28.67312, 77.28654)
GUPTA = (28.67921, 77.29433)
DEMO_KEY_HEADER = {"X-Demo-Key": "test-demo-key"}

# Seeded accounts (backend/app/seed.py), PIN 1234.
MEENA_PHONE = "9810000001"
RAJU_PHONE = "9811000001"
SATIN_PHONE = "9812000001"


def photo(seed: int) -> bytes:
    """A unique noise image per seed, so its perceptual hash is nowhere near any other test photo."""
    rng = random.Random(seed)
    img = Image.new("RGB", (64, 64))
    img.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(64 * 64)])
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def login(client, role, phone, pin="1234"):
    r = client.post("/api/auth/login", json={"role": role, "phone": phone, "pin": pin})
    assert r.status_code == 200, r.text
    return r.json()["user"]


def reset(client):
    r = client.post("/api/demo/reset", headers=DEMO_KEY_HEADER)
    assert r.status_code == 200, r.text


def ids(client):
    """Name → row for the seeded collectors and dealers. Needs the Satin session (the collector
    list is Satin's, not the world's)."""
    collectors = {c["name"].split()[0]: c for c in client.get("/api/collectors").json()}
    dealers = {d["shop_name"].split()[0]: d for d in client.get("/api/dealers").json()}
    return collectors, dealers


def new_request(client, cid, img, kg=28, loc=RAJU, dealer_id=1, **extra):
    """Logs in as that collector (their own session), then raises a sale request to one shop.

    `dealer_id` defaults to 1 (Raju Kabadi Store), the dealer the demo script uses."""
    phone = next(c["phone"] for c in client.get("/api/collectors").json() if c["id"] == cid)
    login(client, "collector", phone)
    data = {"material": "plastic", "est_kg": kg, "lat": loc[0], "lng": loc[1],
            "dealer_id": dealer_id, **extra}
    return client.post("/api/requests", data=data, files={"photo": ("p.jpg", img, "image/jpeg")})


def signed(client, path: str, payload: dict):
    """POST as a payment or IVR provider would: raw JSON plus its HMAC."""
    raw = json.dumps(payload).encode()
    return client.post(path, content=raw, headers={
        "Content-Type": "application/json",
        "X-Provider-Signature": auth.sign_provider_body(raw),
    })


@contextmanager
def env(**kw):
    """Temporarily set (or with None, unset) environment variables."""
    before = {k: os.environ.get(k) for k in kw}
    try:
        for k, v in kw.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        yield
    finally:
        for k, v in before.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


@contextmanager
def verifier(check: adapters.PhotoCheck | None):
    """Swap in a scripted photo-check answer for the duration of the block."""
    before = adapters.photo_verifier
    adapters.photo_verifier = adapters.MockPhotoVerifier(check)
    try:
        yield
    finally:
        adapters.photo_verifier = before


class ExplodingVerifier(adapters.PhotoVerifier):
    """Stands in for the verifier timing out or the provider breaking."""

    def __init__(self, exc: BaseException):
        self.exc = exc

    def check(self, jpeg: bytes, selected_material: str):
        raise self.exc


@contextmanager
def broken_verifier(exc: BaseException):
    before = adapters.photo_verifier
    adapters.photo_verifier = ExplodingVerifier(exc)
    try:
        yield
    finally:
        adapters.photo_verifier = before


def seen(material: str, confidence: float, *, real_scene: bool | None = True,
         notes: str | None = None, quantity: str | None = None) -> adapters.PhotoCheck:
    return adapters.PhotoCheck(available=True, material=material, confidence=confidence,
                               real_scene=real_scene, notes=notes, approx_quantity=quantity)


@pytest.fixture(scope="module")
def client():
    """A client signed in as the demo dealer and Satin, on a freshly seeded database.

    Module-scoped and reseeded per module, so each test file starts from the same demo data however
    the files happen to be ordered.
    """
    with TestClient(app) as c:
        reset(c)
        login(c, "dealer", RAJU_PHONE)
        login(c, "satin", SATIN_PHONE)
        yield c
