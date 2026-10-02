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

    # Seconds after which the mock provider calls our webhook. Real providers call it themselves.
    mock_webhook_delay: float | None = None


class MockUpi(PaymentAdapter):
    mock_webhook_delay = 1.0

    def initiate(self, payer_vpa: str, payee_vpa: str, amount: float) -> PaymentInit:
        return PaymentInit(provider_ref=new_upi_ref(), status="pending")


def new_upi_ref() -> str:
    return "UPI" + "".join(secrets.choice("0123456789") for _ in range(12))


# ---------- Messages (voice / WhatsApp / IVR) ----------

class MessageAdapter(ABC):
    @abstractmethod
    def send(self, conn, collector_id: int, channel: str, language: str, text: str) -> None: ...


class OnScreenMessages(MessageAdapter):
    """Demo: messages are stored and shown on the collector screen (and spoken by the browser)."""

    def send(self, conn, collector_id: int, channel: str, language: str, text: str) -> None:
        from .clock import ts
        conn.execute(
            "INSERT INTO messages (collector_id, channel, language, text, created_at) VALUES (?,?,?,?,?)",
            (collector_id, channel, language, text, ts()),
        )


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
