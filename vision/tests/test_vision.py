"""Pipeline, agent and Lambda handler. No dataset or AWS needed: images are drawn, S3/DynamoDB are fakes."""
import base64
import json
import os

import cv2
import numpy as np
import pytest

os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
os.environ["WW_VISION_KEY"] = "test-key"
os.environ["WW_TABLE"] = "t"
os.environ["WW_BUCKET"] = "b"

from ww_vision import agent, pipeline  # noqa: E402

MODELS = pipeline.Models()


def jpeg(img) -> bytes:
    return cv2.imencode(".jpg", img)[1].tobytes()


def scene() -> np.ndarray:
    """Two textured heaps on a plain floor: sharp, lit, and clearly apart."""
    rng = np.random.default_rng(1)
    img = np.full((480, 640, 3), (150, 150, 145), np.uint8)
    for cx, colour in ((170, (40, 120, 60)), (470, (200, 160, 40))):
        heap = np.clip(rng.normal(colour, 45, (240, 240, 3)), 0, 255).astype(np.uint8)
        mask = np.zeros((240, 240), np.uint8)
        cv2.circle(mask, (120, 120), 115, 255, -1)
        roi = img[120:360, cx - 120:cx + 120]
        roi[mask > 0] = heap[mask > 0]
    return img


def without_images(r: dict) -> dict:
    return {k: v for k, v in r.items() if k != "images"}


# ---------- pipeline ----------

def test_a_clear_photo_is_judged_with_evidence():
    r = pipeline.analyze(MODELS, jpeg(scene()))
    assert r["status"] == "ok" and r["verdict"] in ("separated", "mixed")
    assert 0 <= r["confidence"] <= 1 and len(r["heaps"]) == 2  # the watershed found both heaps
    assert all(h["parts"] for h in r["heaps"])
    assert set(r["timings_ms"]) >= {"decode", "quality", "segment", "superpixels", "classify", "total"}
    assert cv2.imdecode(np.frombuffer(r["images"]["annotated"], np.uint8), cv2.IMREAD_COLOR) is not None


def test_bad_input_and_bad_photos_are_not_judged():
    assert pipeline.analyze(MODELS, b"not a photo")["status"] == "bad_input"
    assert pipeline.analyze(MODELS, jpeg(np.zeros((40, 40, 3), np.uint8)))["status"] == "bad_input"
    blurred = pipeline.analyze(MODELS, jpeg(cv2.GaussianBlur(scene(), (0, 0), 8)))
    assert blurred["status"] == "low_quality" and "blurry" in blurred["quality"]["problems"]
    dark = pipeline.analyze(MODELS, jpeg((scene() * 0.15).astype(np.uint8)))
    assert dark["status"] == "low_quality" and "too_dark" in dark["quality"]["problems"]


def test_heap_rule():
    sure_org, sure_rec, unsure = 0.95, 0.05, 0.55
    assert not pipeline.judge_heap([(sure_org, 100)] * 9)["mixed"]
    assert pipeline.judge_heap([(sure_org, 100)] * 7 + [(sure_rec, 100)] * 3)["mixed"]
    # parts the classifier is unsure about do not vote
    assert not pipeline.judge_heap([(sure_org, 100)] * 5 + [(unsure, 100)] * 5)["mixed"]


# ---------- agent ----------

def ok(verdict, confidence):
    return {"status": "ok", "verdict": verdict, "confidence": confidence, "quality": {"problems": []},
            "heaps": [{}], "timings_ms": {"total": 1}}


def test_agent_actions():
    assert agent.decide(None, marked="separated", attempt=1, error="timeout")["action"] == "accept_unverified"
    low = {"status": "low_quality", "quality": {"problems": ["blurry"]}, "confidence": 0.0}
    assert agent.decide(low, marked="separated", attempt=1)["action"] == "recapture"
    assert agent.decide(low, marked="separated", attempt=agent.MAX_ATTEMPTS)["action"] == "accept_unverified"
    assert agent.decide(ok("separated", 0.3), marked="separated", attempt=1)["action"] == "recapture"
    assert agent.decide(ok("separated", 0.9), marked="separated", attempt=1)["action"] == "accept"
    d = agent.decide(ok("mixed", 0.9), marked="separated", attempt=1)
    assert d["action"] == "needs_approval" and any(s["kind"] == "action" for s in d["trace"])
    assert agent.decide(ok("mixed", 0.6), marked="separated", attempt=1)["action"] == "accept"
    d = agent.decide(ok("separated", 0.9), marked="mixed", attempt=1)
    assert d["action"] == "accept" and d["segregation"] == "mixed"


def test_review_is_logged():
    d = agent.decide(ok("mixed", 0.9), marked="separated", attempt=1)
    r = agent.review(d["trace"], approve=True, reviewer="ops")
    assert r["outcome"] == "mixed" and r["trace"][-2]["kind"] == "human"


# ---------- Lambda handler ----------

class FakeTable:
    def __init__(self):
        self.items = {}
        self.meta = type("M", (), {"client": type("C", (), {"exceptions": type("E", (), {
            "ConditionalCheckFailedException": KeyError})})})

    def put_item(self, Item):
        self.items[Item["run_id"]] = Item

    def get_item(self, Key):
        return {"Item": self.items.get(Key["run_id"])} if Key["run_id"] in self.items else {}

    def update_item(self, Key, ConditionExpression, UpdateExpression, ExpressionAttributeNames,
                    ExpressionAttributeValues):
        item = self.items[Key["run_id"]]
        if item["status"] != "pending_approval":
            raise KeyError("condition")
        item.update(status="closed", trace=ExpressionAttributeValues[":t"], outcome=ExpressionAttributeValues[":o"])

    def delete_item(self, Key):
        self.items.pop(Key["run_id"])


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = Body

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return "https://s3/" + Params["Key"]


@pytest.fixture
def lam(monkeypatch):
    import lambda_function as lf
    monkeypatch.setattr(lf, "table", FakeTable())
    monkeypatch.setattr(lf, "s3", FakeS3())
    monkeypatch.setattr(lf, "MODELS", MODELS)
    monkeypatch.setattr(lf, "KEY", "test-key")
    return lf


def call(lf, method, path, body=None, key="test-key"):
    r = lf.handler({"headers": {"X-WW-Key": key}, "requestContext": {"http": {"method": method}}, "rawPath": path,
                    "body": json.dumps(body) if body is not None else None}, None)
    return r["statusCode"], json.loads(r["body"])


def test_lambda_needs_the_key(lam):
    assert call(lam, "POST", "/analyze", {}, key="wrong")[0] == 401


def test_lambda_run_review_and_delete(lam, monkeypatch):
    status, run = call(lam, "POST", "/analyze", {"image_b64": base64.b64encode(jpeg(scene())).decode(),
                                                 "marked": "separated", "source": "demo"})
    assert status == 200 and run["result"]["status"] == "ok" and run["trace"]
    assert set(lam.s3.objects) == {f"runs/{run['run_id']}/safe.jpg", f"runs/{run['run_id']}/annotated.jpg"}
    item = lam.table.items[run["run_id"]]
    assert item["expires_at"] > item["created_at"]  # deletes itself (TTL)

    # a run waiting for a person: approve once, the second approval is refused
    item["status"] = "pending_approval"
    assert call(lam, "POST", f"/runs/{run['run_id']}/review", {"approve": True, "reviewer": "ops"})[0] == 200
    assert call(lam, "POST", f"/runs/{run['run_id']}/review", {"approve": False})[0] == 409

    assert call(lam, "DELETE", f"/runs/{run['run_id']}")[0] == 200
    assert not lam.s3.objects and run["run_id"] not in lam.table.items


def test_lambda_survives_garbage(lam):
    status, run = call(lam, "POST", "/analyze", {"image_b64": "!!!", "marked": "separated"})
    assert status == 200 and run["action"] == "accept_unverified" and run["error"]
