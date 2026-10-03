"""Integration adapters. The Round 1 demo uses the mocks; the pilot swaps in real providers
behind the same interfaces (see Tech Spec, 'Integrations')."""
import os
import random
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass


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
PHOTO_TIMEOUT_S = 8.0
PHOTO_MAX_EDGE = 768          # plenty for "is this cardboard?", and keeps the request small
PHOTO_JPEG_QUALITY = 82

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


def reencode_jpeg(data: bytes, max_edge: int = PHOTO_MAX_EDGE) -> bytes:
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
    img.save(buf, "JPEG", quality=PHOTO_JPEG_QUALITY)
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
    a verdict against the collector."""

    ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
    DEFAULT_MODEL = "gemini-3.5-flash"

    def __init__(self, api_key: str, model: str | None = None, timeout_s: float = PHOTO_TIMEOUT_S):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.timeout_s = timeout_s

    def check(self, jpeg: bytes, selected_material: str) -> PhotoCheck:
        import base64
        import json
        import urllib.error
        import urllib.request

        body = json.dumps({
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
        req = urllib.request.Request(self.ENDPOINT, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return PhotoCheck.unavailable(f"Photo check unavailable ({type(e).__name__})")
        except ValueError:
            return PhotoCheck.unavailable("Photo check returned a non-JSON response")
        return self._parse(payload)

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
