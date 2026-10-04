"""Integration adapters. The Round 1 demo uses the mocks; the pilot swaps in real providers
behind the same interfaces (see Tech Spec, 'Integrations')."""
import logging
import os
import random
import secrets
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

log = logging.getLogger("worthywaste.adapters")


# ---------- Scale ----------

@dataclass
class ScaleReading:
    kg: float
    source: str  # e.g. "sim:SCALE-01" or "ble:<device id>"


class ScaleAdapter(ABC):
    @abstractmethod
    def read(self, scale_id: str, est_kg: float, mode: str = "normal") -> ScaleReading: ...


class SimulatedScale(ScaleAdapter):
    """Random reading near the estimate. With WW_SCRIPTED=1 the reading is fixed (est × 0.978,
    so 28 kg → 27.4 kg) so every take of the demo recording is identical."""

    def read(self, scale_id: str, est_kg: float, mode: str = "normal") -> ScaleReading:
        if mode == "overstated":
            # Collector overstated the estimate: the scale reads well under it.
            kg = est_kg * 0.8
        elif os.environ.get("WW_SCRIPTED") == "1":
            kg = est_kg * 0.978
        else:
            kg = est_kg * random.uniform(0.94, 1.04)
        return ScaleReading(kg=round(kg, 1), source=f"sim:{scale_id or 'SCALE'}")


# ---------- Payments ----------

@dataclass
class PaymentInit:
    provider_ref: str
    status: str  # "pending"


class PaymentAdapter(ABC):
    @abstractmethod
    def initiate(self, payer_vpa: str, payee_vpa: str, amount: float) -> PaymentInit: ...

    # Mock only: a pending payment older than this many seconds is settled as successful the next
    # time anyone checks on it. No background timer, so it works on serverless too. Real providers
    # call POST /api/payments/webhook themselves and leave this as None.
    settles_after_s: float | None = None


class MockUpi(PaymentAdapter):
    settles_after_s = 1.0

    def initiate(self, payer_vpa: str, payee_vpa: str, amount: float) -> PaymentInit:
        return PaymentInit(provider_ref=new_upi_ref(), status="pending")


def new_upi_ref() -> str:
    return "UPI" + "".join(secrets.choice("0123456789") for _ in range(12))


# ---------- Messages (voice / WhatsApp / IVR) ----------

class MessageAdapter(ABC):
    @abstractmethod
    def send(self, conn, collector_id: int, channel: str, language: str, text: str,
             meta: dict | None = None) -> None: ...


class OnScreenMessages(MessageAdapter):
    """Demo: messages are stored and shown on the collector screen (and spoken by the browser)."""

    def send(self, conn, collector_id: int, channel: str, language: str, text: str,
             meta: dict | None = None) -> None:
        import json
        from .clock import ts
        conn.execute(
            "INSERT INTO messages (collector_id, channel, language, text, meta_json, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (collector_id, channel, language, text, json.dumps(meta) if meta else None, ts()),
        )


# ---------- Photo check (does the photo show the material the collector picked?) ----------

MATERIAL_CHOICES = ("plastic", "cardboard", "metal", "paper", "wire", "glass", "mixed", "not_scrap")
PHOTO_MAX_EDGE = 768          # what we keep and show the dealer
PHOTO_JPEG_QUALITY = 82
# What the model gets. Measured on the preview: 512 px gives the same verdicts as 768 px and shaves
# seconds off a call that was running at ~7.5 s against an 8 s timeout.
PHOTO_MODEL_MAX_EDGE = 512
PHOTO_MODEL_QUALITY = 80
PHOTO_TIMEOUT_S = 15.0        # per attempt
PHOTO_TOTAL_BUDGET_S = 20.0   # for the whole check, retry included (the function limit is 60 s)
PHOTO_RETRY_DELAY_S = 1.0
PHOTO_RETRY_CODES = (429, 503)

PHOTO_PROMPT = (
    "You are checking a photo a waste picker took of scrap they want to sell, against the material "
    "they selected in the app.\n"
    "Answer only with JSON, no prose, with exactly these keys:\n"
    '  "material": one of plastic, cardboard, metal, paper, wire, glass, mixed, not_scrap\n'
    '  "confidence": a number from 0 to 1\n'
    '  "real_scene": true if this is a photo of real scrap in front of the camera; '
    "false if it is a photo of a screen, a printout, a catalogue or stock imagery\n"
    '  "approx_quantity": a short free-text estimate, e.g. "about one full sack"\n'
    '  "notes": one short sentence a human reviewer would find useful\n'
    "Use \"mixed\" only when no single material dominates. Use \"not_scrap\" when the photo does not "
    "show recyclable scrap at all.\n"
    "The collector selected: "
)

PHOTO_SCHEMA = {
    "type": "object",
    "properties": {
        "material": {"type": "string", "enum": list(MATERIAL_CHOICES)},
        "confidence": {"type": "number"},
        "real_scene": {"type": "boolean"},
        "approx_quantity": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["material", "confidence", "real_scene"],
}


# What the last photo check did, so a silent failure cannot hide. Exposed on /api/health; holds no
# key, no image and no collector data. Per instance, like the login rate limiter.
_photo_status: dict = {"last_ms": None, "last_error": None}


def record_photo_check(ms: float | None = None, *, error: str | None = None) -> None:
    if ms is not None:
        _photo_status["last_ms"] = round(ms)
    if error:
        from .clock import ts
        _photo_status["last_error"] = {"at": ts(), "reason": error[:200]}


def photo_check_status() -> dict:
    return {"photo_check_last_ms": _photo_status["last_ms"],
            "photo_check_last_error": _photo_status["last_error"]}


@dataclass
class PhotoCheck:
    """What the verifier saw. `available` is False when the AI could not be reached at all, which the
    caller turns into the 'unchecked' verdict — a photo check must never block a sale on its own."""

    available: bool
    material: str | None = None
    confidence: float | None = None
    real_scene: bool | None = None
    approx_quantity: str | None = None
    notes: str | None = None

    @classmethod
    def unavailable(cls, why: str) -> "PhotoCheck":
        return cls(available=False, notes=why)


class PhotoVerifier(ABC):
    @abstractmethod
    def check(self, jpeg: bytes, selected_material: str) -> PhotoCheck: ...


def reencode_jpeg(data: bytes, max_edge: int = PHOTO_MAX_EDGE, quality: int = PHOTO_JPEG_QUALITY) -> bytes:
    """Re-save the photo as a plain JPEG before it leaves our servers. Pillow writes only the pixels,
    so EXIF — including the GPS tags many phones embed — is dropped, and the downscale keeps the
    request small. Raises if the bytes are not a readable image."""
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")
    if max(img.size) > max_edge:
        scale = max_edge / max(img.size)
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                         Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


class MockPhotoVerifier(PhotoVerifier):
    """Used in tests and whenever GEMINI_API_KEY is unset. Returns whatever `self.result` holds, so a
    test can script each verdict; by default the AI is simply unavailable, i.e. 'unchecked'."""

    def __init__(self, result: PhotoCheck | None = None):
        self.result = result

    def check(self, jpeg: bytes, selected_material: str) -> PhotoCheck:
        if self.result is None:
            return PhotoCheck.unavailable("No photo verifier configured")
        return self.result


class GeminiPhotoVerifier(PhotoVerifier):
    """Google's Gemini API over plain REST (no SDK: the serverless bundle stays small).

    Uses the interactions endpoint with a response_format schema so the model must answer with the
    JSON we asked for. Any error, timeout or unparseable answer comes back as unavailable, never as
    a verdict against the collector — but it is logged and shown on /api/health, because a photo
    check that has quietly stopped working looks exactly like one that finds nothing wrong.
    """

    ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
    # Lite answers in 4–5.5 s where flash takes 6–8 s, with the same verdicts on the photos we
    # tested on the preview. Override with GEMINI_MODEL.
    DEFAULT_MODEL = "gemini-3.5-flash-lite"

    def __init__(self, api_key: str, model: str | None = None, timeout_s: float = PHOTO_TIMEOUT_S,
                 budget_s: float = PHOTO_TOTAL_BUDGET_S):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.timeout_s = timeout_s
        self.budget_s = budget_s

    def _body(self, jpeg: bytes, selected_material: str) -> bytes:
        import base64
        import json

        return json.dumps({
            "model": self.model,
            "input": [
                {"type": "text", "text": PHOTO_PROMPT + selected_material},
                {"type": "image", "mime_type": "image/jpeg",
                 "data": base64.b64encode(jpeg).decode()},
            ],
            "response_format": {"type": "text", "mime_type": "application/json",
                                "schema": PHOTO_SCHEMA},
            "generation_config": {"thinking_level": "minimal", "max_output_tokens": 400},
        }).encode()

    @staticmethod
    def _google_error(err) -> tuple[str | None, str | None]:
        """Google puts a machine-readable status and a human message in the error body. Reading them
        is the difference between "the photo check is broken" and "the key is out of quota"."""
        import json

        try:
            body = json.loads(err.read().decode(errors="replace")).get("error") or {}
        except Exception:
            return None, None
        status = body.get("status")
        message = body.get("message")
        return (str(status)[:60] if status else None, str(message)[:160] if message else None)

    def check(self, jpeg: bytes, selected_material: str) -> PhotoCheck:
        import urllib.error
        import urllib.request

        # The model only needs enough pixels to tell cardboard from plastic; the dealer gets the
        # bigger copy. Smaller upload, faster answer.
        try:
            small = reencode_jpeg(jpeg, max_edge=PHOTO_MODEL_MAX_EDGE, quality=PHOTO_MODEL_QUALITY)
        except Exception:
            small = jpeg
        body = self._body(small, selected_material)
        deadline = time.monotonic() + self.budget_s
        attempt = 0

        while True:
            attempt += 1
            left = deadline - time.monotonic()
            if left <= 0:
                return self._unavailable("Photo check ran out of time", ms=None)
            timeout = min(self.timeout_s, left)
            req = urllib.request.Request(self.ENDPOINT, data=body, method="POST", headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            })
            started = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = resp.read()
            except urllib.error.HTTPError as e:
                ms = (time.monotonic() - started) * 1000
                status, message = self._google_error(e)
                retry = e.code in PHOTO_RETRY_CODES and self._can_retry(attempt, deadline)
                log.warning("photo check failed: model=%s http=%s status=%s ms=%.0f retry=%s msg=%s",
                            self.model, e.code, status, ms, retry, message)
                if retry:
                    time.sleep(PHOTO_RETRY_DELAY_S)
                    continue
                reason = f"HTTP {e.code}" + (f" {status}" if status else "")
                return self._unavailable(reason + (f": {message}" if message else ""), ms)
            except (TimeoutError, urllib.error.URLError, OSError) as e:
                # A timeout or a dropped connection is often transient, so it gets the same one
                # retry — inside the same total budget, so a slow model cannot stretch the request.
                ms = (time.monotonic() - started) * 1000
                retry = self._can_retry(attempt, deadline)
                log.warning("photo check failed: model=%s error=%s ms=%.0f retry=%s",
                            self.model, type(e).__name__, ms, retry)
                if retry:
                    time.sleep(PHOTO_RETRY_DELAY_S)
                    continue
                return self._unavailable(f"{type(e).__name__} after {ms / 1000:.1f}s", ms)

            ms = (time.monotonic() - started) * 1000
            import json
            try:
                data = json.loads(payload)
            except ValueError:
                return self._unavailable("Response was not JSON", ms)
            result = self._parse(data)
            if not result.available:
                log.warning("photo check unusable: model=%s ms=%.0f reason=%s",
                            self.model, ms, result.notes)
                return self._unavailable(result.notes or "Unusable answer", ms)
            record_photo_check(ms)
            log.info("photo check ok: model=%s ms=%.0f material=%s confidence=%.2f",
                     self.model, ms, result.material, result.confidence or 0.0)
            return result

    @staticmethod
    def _can_retry(attempt: int, deadline: float) -> bool:
        """One retry only, and only if there is time left for it to mean anything."""
        return attempt == 1 and (deadline - time.monotonic()) > PHOTO_RETRY_DELAY_S + 2.0

    @staticmethod
    def _unavailable(reason: str, ms: float | None) -> PhotoCheck:
        record_photo_check(ms, error=reason)
        return PhotoCheck.unavailable(f"Photo check unavailable ({reason})")

    @staticmethod
    def _output_text(payload: dict) -> str | None:
        """The answer text, across the shapes the API documents (output_text, steps[].content[].text)
        and the older generateContent shape, so a response format change degrades to 'unchecked'."""
        for key in ("output_text", "outputText"):
            if isinstance(payload.get(key), str):
                return payload[key]
        inner = payload.get("interaction")
        if isinstance(inner, dict):
            return GeminiPhotoVerifier._output_text(inner)
        parts: list[str] = []
        for step in payload.get("steps") or []:
            for part in (step or {}).get("content") or []:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
        for cand in payload.get("candidates") or []:
            for part in ((cand or {}).get("content") or {}).get("parts") or []:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
        return "".join(parts) or None

    @classmethod
    def _parse(cls, payload: dict) -> PhotoCheck:
        import json

        text = cls._output_text(payload)
        if not text:
            return PhotoCheck.unavailable("Photo check returned no answer")
        try:
            data = json.loads(text)
        except ValueError:
            return PhotoCheck.unavailable("Photo check answer was not valid JSON")
        if not isinstance(data, dict):
            return PhotoCheck.unavailable("Photo check answer was not an object")
        material = data.get("material")
        if material not in MATERIAL_CHOICES:
            return PhotoCheck.unavailable(f"Photo check named an unknown material ({material!r})")
        try:
            confidence = min(1.0, max(0.0, float(data.get("confidence"))))
        except (TypeError, ValueError):
            return PhotoCheck.unavailable("Photo check gave no usable confidence")
        real_scene = data.get("real_scene")
        return PhotoCheck(
            available=True,
            material=material,
            confidence=confidence,
            real_scene=bool(real_scene) if isinstance(real_scene, bool) else None,
            approx_quantity=_short(data.get("approx_quantity")),
            notes=_short(data.get("notes")),
        )


def _short(v, limit: int = 240) -> str | None:
    return str(v)[:limit] if isinstance(v, (str, int, float)) else None


def build_photo_verifier() -> PhotoVerifier:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return MockPhotoVerifier()
    return GeminiPhotoVerifier(key, os.environ.get("GEMINI_MODEL"))


# ---------- KYC ----------

class KycAdapter(ABC):
    @abstractmethod
    def verify(self, id_type: str, id_number: str) -> bool: ...


class SkippedKyc(KycAdapter):
    """Demo: KYC is skipped. In the pilot Satin, as the regulated lender, runs KYC."""

    def verify(self, id_type: str, id_number: str) -> bool:
        return True


scale: ScaleAdapter = SimulatedScale()
payments: PaymentAdapter = MockUpi()
messages: MessageAdapter = OnScreenMessages()
kyc: KycAdapter = SkippedKyc()
photo_verifier: PhotoVerifier = build_photo_verifier()
