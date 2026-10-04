"""The photo check against a fake HTTP layer. Nothing here touches the network.

Measured on the Vercel preview, a call was taking ~7.5 s against an 8 s timeout, so one real
mismatch timed out and silently became "unchecked", and a burst hit a rate limit. These tests pin
the three things that fixes: a bigger timeout with one retry, a smaller image, and failures that
are visible instead of silent.
"""
import base64
import io
import json
import urllib.error
import urllib.request

import pytest
from PIL import Image

from app import adapters


def answer(material="cardboard", confidence=0.95, real_scene=True):
    """A well-formed interactions response."""
    return json.dumps({"steps": [{"content": [{"type": "text", "text": json.dumps(
        {"material": material, "confidence": confidence, "real_scene": real_scene,
         "approx_quantity": "one sack", "notes": "fake"})}]}]}).encode()


class FakeClock:
    """A monotonic clock the test moves by hand, so "this attempt used its whole timeout" is
    something we can state rather than wait for."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeHttp:
    """Stands in for urllib.request.urlopen. Each scripted step is a response or an exception.

    When a step is a timeout and a clock is attached, it advances that clock by the timeout the
    verifier asked for — which is what a real attempt that times out costs.
    """

    def __init__(self, *steps, clock=None):
        self.steps = list(steps)
        self.requests = []
        self.timeouts = []
        self.clock = clock

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        self.timeouts.append(timeout)
        step = self.steps.pop(0) if self.steps else self.steps
        if isinstance(step, BaseException):
            if self.clock and isinstance(step, TimeoutError):
                self.clock.advance(timeout)
            raise step
        return _Resp(step)

    # What the verifier actually sent.
    def body(self, i=0):
        return json.loads(self.requests[i].data)

    def image(self, i=0):
        parts = [p for p in self.body(i)["input"] if p.get("type") == "image"]
        return Image.open(io.BytesIO(base64.b64decode(parts[0]["data"])))


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, status=None, message=None):
    body = json.dumps({"error": {"status": status, "message": message}}).encode()
    return urllib.error.HTTPError("https://example.invalid", code, "err", {},
                                  io.BytesIO(body))


def big_photo(px=1600):
    img = Image.new("RGB", (px, int(px * 0.6)), (90, 120, 70))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def clean_status():
    """Each test starts with no recorded latency or failure, and leaves none behind."""
    before = dict(adapters._photo_status)
    adapters._photo_status.update({"last_ms": None, "last_error": None})
    yield
    adapters._photo_status.update(before)


@pytest.fixture
def fake(monkeypatch):
    def _install(*steps, clock=None):
        http = FakeHttp(*steps, clock=clock)
        monkeypatch.setattr(urllib.request, "urlopen", http)
        return http
    return _install


@pytest.fixture
def clock(monkeypatch):
    """Freeze the verifier's clock and never really sleep, so budget tests run instantly."""
    c = FakeClock()
    monkeypatch.setattr(adapters.time, "monotonic", c.monotonic)
    monkeypatch.setattr(adapters.time, "sleep", lambda s: c.advance(s))
    return c


def verifier(**kw):
    return adapters.GeminiPhotoVerifier("test-key-not-a-real-one", **kw)


# ---------- Retry ----------

def test_a_rate_limit_is_retried_once_and_the_verdict_comes_through(fake, clock):
    http = fake(http_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded"), answer("cardboard", 0.91))
    got = verifier().check(big_photo(), "plastic")
    assert got.available
    assert got.material == "cardboard" and got.confidence == 0.91
    assert len(http.requests) == 2, "the 429 should have been retried exactly once"
    # A recovered call is not an error, so health stays clean and records the latency.
    assert adapters.photo_check_status()["photo_check_last_error"] is None
    assert adapters.photo_check_status()["photo_check_last_ms"] is not None


def test_a_server_error_is_retried_too(fake, clock):
    http = fake(http_error(503, "UNAVAILABLE", "Overloaded"), answer("plastic", 0.88))
    assert verifier().check(big_photo(), "plastic").material == "plastic"
    assert len(http.requests) == 2


def test_a_bad_request_is_not_retried(fake):
    http = fake(http_error(400, "INVALID_ARGUMENT", "Unsupported model"), answer())
    got = verifier().check(big_photo(), "plastic")
    assert not got.available
    assert len(http.requests) == 1, "a 400 will fail again; retrying only wastes the budget"
    reason = adapters.photo_check_status()["photo_check_last_error"]["reason"]
    assert "HTTP 400" in reason and "INVALID_ARGUMENT" in reason
    assert "Unsupported model" in reason


def test_two_timeouts_leave_the_sale_unchecked_and_say_so_on_health(fake, clock):
    http = fake(TimeoutError("read timed out"), TimeoutError("read timed out"), clock=clock)
    got = verifier().check(big_photo(), "plastic")
    assert not got.available
    assert len(http.requests) == 2
    # The first attempt gets the full timeout; the retry only gets what is left of the budget.
    assert http.timeouts[0] == 15.0
    assert http.timeouts[1] == pytest.approx(20.0 - 15.0 - 1.0)
    # And the whole check stayed inside its budget, well under the 60 s function limit.
    assert clock.now - 1000.0 <= adapters.PHOTO_TOTAL_BUDGET_S
    err = adapters.photo_check_status()["photo_check_last_error"]
    assert "TimeoutError" in err["reason"] and err["at"]


def test_the_budget_stops_a_second_attempt_when_there_is_no_time_left(fake, clock):
    # A budget barely longer than one attempt leaves no room for a retry to mean anything.
    http = fake(TimeoutError("slow"), answer(), clock=clock)
    got = verifier(timeout_s=15.0, budget_s=16.0).check(big_photo(), "plastic")
    assert not got.available
    assert len(http.requests) == 1, "a 1 s retry window is not worth spending"
    assert clock.now - 1000.0 <= 16.0


def test_a_whole_check_never_outlasts_its_budget(fake, clock):
    """Whatever goes wrong, the request comes back long before the 60 s function limit."""
    for steps in ([TimeoutError("a"), TimeoutError("b")],
                  [http_error(429, "RESOURCE_EXHAUSTED", "slow down"), TimeoutError("b")],
                  [http_error(503), http_error(503)]):
        clock.now = 1000.0
        fake(*steps, clock=clock)
        verifier().check(big_photo(), "plastic")
        assert clock.now - 1000.0 <= adapters.PHOTO_TOTAL_BUDGET_S, steps


# ---------- What we actually send ----------

def test_the_image_sent_to_the_model_is_at_most_512_px(fake):
    http = fake(answer())
    verifier().check(big_photo(2400), "plastic")
    sent = http.image()
    assert max(sent.size) == adapters.PHOTO_MODEL_MAX_EDGE == 512
    # The stored copy stays bigger, for the dealer to look at.
    stored = Image.open(io.BytesIO(adapters.reencode_jpeg(big_photo(2400))))
    assert max(stored.size) == adapters.PHOTO_MAX_EDGE == 768
    assert len(base64.b64decode([p for p in http.body()["input"]
                                 if p.get("type") == "image"][0]["data"])) < 120_000


def test_the_configured_model_is_the_one_sent(fake):
    http = fake(answer(), answer())
    verifier().check(big_photo(), "plastic")
    assert http.body()["model"] == "gemini-3.5-flash-lite" == adapters.GeminiPhotoVerifier.DEFAULT_MODEL
    adapters.GeminiPhotoVerifier("test-key-not-a-real-one", "gemini-9-custom").check(big_photo(), "plastic")
    assert http.body(1)["model"] == "gemini-9-custom"


def test_the_timeout_asked_for_is_fifteen_seconds(fake):
    http = fake(answer())
    verifier().check(big_photo(), "plastic")
    assert adapters.PHOTO_TIMEOUT_S == 15.0
    assert http.timeouts[0] == pytest.approx(15.0, abs=0.5)


def test_the_key_is_sent_as_a_header_and_never_in_the_body(fake):
    http = fake(answer())
    verifier().check(big_photo(), "plastic")
    req = http.requests[0]
    assert req.get_header("X-goog-api-key") == "test-key-not-a-real-one"
    assert "test-key-not-a-real-one" not in req.data.decode()


def test_env_chooses_the_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-a-real-one")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert adapters.build_photo_verifier().model == "gemini-3.5-flash-lite"
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")
    assert adapters.build_photo_verifier().model == "gemini-3.5-flash"
    monkeypatch.delenv("GEMINI_API_KEY")
    assert isinstance(adapters.build_photo_verifier(), adapters.MockPhotoVerifier)


# ---------- Health ----------

def test_health_reports_the_last_latency_and_the_last_failure(client, fake, clock):
    assert client.get("/api/health").json()["photo_check_last_error"] is None

    fake(TimeoutError("read timed out"), TimeoutError("read timed out"), clock=clock)
    before = adapters.photo_verifier
    adapters.photo_verifier = verifier()
    try:
        from tests.conftest import ids, new_request, photo
        collectors, _ = ids(client)
        r = new_request(client, collectors["Sunita"]["id"], photo(501), kg=9)
    finally:
        adapters.photo_verifier = before

    # The sale went through — an unreachable model never costs the collector a sale…
    assert r.status_code == 201, r.text
    assert r.json()["ai_verdict"] == "unchecked"
    # …but the failure is on the health page rather than nowhere.
    h = client.get("/api/health").json()
    assert h["photo_check_last_error"] and "TimeoutError" in h["photo_check_last_error"]["reason"]
    assert h["photo_check_last_error"]["at"]
    assert h["photo_check_last_ms"] is not None
    assert h["photo_check_model"] is None            # the mock verifier is back in place


def test_health_never_leaks_the_key_or_the_photo(client, fake):
    fake(http_error(403, "PERMISSION_DENIED", "API key not valid"))
    before = adapters.photo_verifier
    adapters.photo_verifier = verifier()
    try:
        adapters.photo_verifier.check(big_photo(), "plastic")
    finally:
        adapters.photo_verifier = before
    body = client.get("/api/health").text
    assert "PERMISSION_DENIED" in body
    assert "test-key-not-a-real-one" not in body
    assert "x-goog-api-key" not in body.lower()


def test_a_crashing_adapter_is_recorded_too(client):
    from tests.conftest import broken_verifier, ids, new_request, photo
    collectors, _ = ids(client)
    with broken_verifier(RuntimeError("adapter exploded")):
        r = new_request(client, collectors["Sunita"]["id"], photo(502), kg=9)
    assert r.status_code == 201 and r.json()["ai_verdict"] == "unchecked"
    err = client.get("/api/health").json()["photo_check_last_error"]
    assert err and "adapter exploded" in err["reason"]
