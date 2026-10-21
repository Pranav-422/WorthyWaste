"""AWS Lambda (function URL): runs the OpenCV pipeline and the agent, keeps the evidence.

    POST   /analyze              {"image_b64", "marked"?, "attempt"?, "source", "ref"?, "return_safe"?} -> run
    GET    /runs/{id}                                                                    -> run
    POST   /runs/{id}/review     {"approve", "reviewer", "note"?}                        -> run
    DELETE /runs/{id}            (data deletion: the item and both photos)

S3 keeps only the face-blurred photo and the annotated one, never the original. DynamoDB keeps one item
per run (result, decision, agent trace) with a 30-day TTL, so data deletes itself. CloudWatch gets
structured logs and metrics (Embedded Metric Format: a log line that CloudWatch turns into metrics).
Every call needs the X-WW-Key header shared with the WorthyWaste backend.
"""
import base64
import hmac
import json
import os
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr

from ww_vision import agent, pipeline

BUCKET = os.environ.get("WW_BUCKET", "")
TABLE = os.environ.get("WW_TABLE", "")
KEY = os.environ.get("WW_VISION_KEY", "")
RETENTION_DAYS = 30
URL_SECONDS = 3600

s3 = boto3.client("s3")
table = boto3.resource("dynamodb").Table(TABLE) if TABLE else None
MODELS = pipeline.Models()  # loaded once per warm container


def _json(status: int, body) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": json.dumps(body, default=lambda o: float(o) if isinstance(o, Decimal) else str(o))}


def _metric(name_values: dict, dims: dict) -> None:
    print(json.dumps({"_aws": {"Timestamp": int(time.time() * 1000), "CloudWatchMetrics": [{
        "Namespace": "WorthyWaste/Vision", "Dimensions": [list(dims)],
        "Metrics": [{"Name": k, "Unit": "Milliseconds" if k.endswith("Ms") else "None"} for k in name_values]}]},
        **dims, **name_values}))


def _urls(run: dict) -> dict:
    return {k: s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": key}, ExpiresIn=URL_SECONDS)
            for k, key in (run.get("images") or {}).items()}


def _public(run: dict) -> dict:
    return {**run, "image_urls": _urls(run)}


def analyze(body: dict) -> dict:
    run_id = uuid.uuid4().hex
    started = time.time()
    attempt = int(body.get("attempt") or 1)
    marked = body.get("marked") if body.get("marked") in ("separated", "mixed") else None
    result, error = None, None
    try:
        data = base64.b64decode(body.get("image_b64") or "", validate=True)
        result = pipeline.analyze(MODELS, data)
    except Exception as e:  # any failure of perception becomes the agent's fallback, never a 500
        error = f"{type(e).__name__}: {e}"[:300]
    images = (result or {}).pop("images", {})
    decision = agent.decide(result, marked=marked, attempt=attempt, error=error)

    keys = {}
    for name, jpeg in images.items():
        keys[name] = f"runs/{run_id}/{name}.jpg"
        s3.put_object(Bucket=BUCKET, Key=keys[name], Body=jpeg, ContentType="image/jpeg")
    run = {
        "run_id": run_id, "created_at": int(started), "source": body.get("source") or "demo",
        "ref": body.get("ref") or {}, "marked": marked, "attempt": attempt, "result": result, "error": error,
        "action": decision["action"], "message": decision["message"], "segregation": decision.get("segregation"),
        "trace": decision["trace"], "images": keys,
        "status": "pending_approval" if decision["action"] == "needs_approval" else "closed",
        "expires_at": int(started) + RETENTION_DAYS * 86400,
    }
    table.put_item(Item=json.loads(json.dumps(run), parse_float=Decimal))
    total_ms = round((time.time() - started) * 1000, 1)
    _metric({"RunLatencyMs": total_ms, "PipelineMs": (result or {}).get("timings_ms", {}).get("total", 0),
             "Confidence": (result or {}).get("confidence") or 0, "Runs": 1},
            {"Action": decision["action"]})
    out = {**_public(run), "latency_ms": total_ms}
    if body.get("return_safe") and "safe" in images:  # the backend keeps the face-blurred copy, not the original
        out["safe_b64"] = base64.b64encode(images["safe"]).decode()
    return out


def handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if not KEY or not hmac.compare_digest(headers.get("x-ww-key", ""), KEY):
        return _json(401, {"error": "bad key"})
    method = event["requestContext"]["http"]["method"]
    parts = [p for p in event.get("rawPath", "/").split("/") if p]
    raw = event.get("body") or ""
    body = json.loads(base64.b64decode(raw) if event.get("isBase64Encoded") else raw or "{}") if raw else {}
    try:
        if method == "POST" and parts == ["analyze"]:
            return _json(200, analyze(body))
        if len(parts) == 2 and parts[0] == "runs":
            run = table.get_item(Key={"run_id": parts[1]}).get("Item")
            if not run:
                return _json(404, {"error": "run not found"})
            if method == "GET":
                return _json(200, _public(run))
            if method == "DELETE":
                for key in (run.get("images") or {}).values():
                    s3.delete_object(Bucket=BUCKET, Key=key)
                table.delete_item(Key={"run_id": parts[1]})
                return _json(200, {"deleted": parts[1]})
        if len(parts) == 3 and parts[0] == "runs" and parts[2] == "review" and method == "POST":
            run = table.get_item(Key={"run_id": parts[1]}).get("Item")
            if not run:
                return _json(404, {"error": "run not found"})
            if run["status"] != "pending_approval":
                return _json(409, {"error": "already reviewed"})
            r = agent.review(json.loads(json.dumps(run["trace"], default=float)), approve=bool(body.get("approve")),
                             reviewer=str(body.get("reviewer") or "reviewer")[:60], note=(body.get("note") or None))
            try:
                table.update_item(
                    Key={"run_id": parts[1]}, ConditionExpression=Attr("status").eq("pending_approval"),
                    UpdateExpression="SET #s = :closed, trace = :t, outcome = :o",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":closed": "closed", ":o": r["outcome"],
                                               ":t": json.loads(json.dumps(r["trace"]), parse_float=Decimal)})
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                return _json(409, {"error": "already reviewed"})
            _metric({"Reviews": 1}, {"Outcome": r["outcome"]})
            return _json(200, _public({**run, "status": "closed", "outcome": r["outcome"], "trace": r["trace"]}))
        return _json(404, {"error": "no such route"})
    except (ValueError, KeyError) as e:
        return _json(400, {"error": str(e)[:200]})
