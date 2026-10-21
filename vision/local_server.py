"""Run the Lambda handler on this machine, with S3 and DynamoDB kept in memory. For development and
for trying the app without AWS:

    WW_VISION_KEY=local python local_server.py          # http://127.0.0.1:8100
    # backend: WW_VISION_URL=http://127.0.0.1:8100 WW_VISION_KEY=local

Photos are served back from /_s3/<key> in place of S3 presigned URLs. Same code path as on AWS otherwise.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

os.environ.setdefault("WW_VISION_KEY", "local")
os.environ.setdefault("WW_TABLE", "local")
os.environ.setdefault("WW_BUCKET", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")

import lambda_function as lf  # noqa: E402

PORT = int(os.environ.get("PORT", "8100"))


class MemoryS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = Body

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"http://127.0.0.1:{PORT}/_s3/{Params['Key']}"


class MemoryTable:
    class _Failed(Exception):
        pass

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.meta = type("M", (), {"client": type("C", (), {"exceptions": type("E", (), {
            "ConditionalCheckFailedException": MemoryTable._Failed})})})

    def put_item(self, Item):
        self.items[Item["run_id"]] = Item

    def get_item(self, Key):
        item = self.items.get(Key["run_id"])
        return {"Item": item} if item else {}

    def update_item(self, Key, ConditionExpression, UpdateExpression, ExpressionAttributeNames,
                    ExpressionAttributeValues):
        item = self.items[Key["run_id"]]
        if item["status"] != "pending_approval":
            raise MemoryTable._Failed()
        item.update(status="closed", trace=ExpressionAttributeValues[":t"], outcome=ExpressionAttributeValues[":o"])

    def delete_item(self, Key):
        self.items.pop(Key["run_id"], None)


lf.s3, lf.table = MemoryS3(), MemoryTable()


class Handler(BaseHTTPRequestHandler):
    def _go(self):
        url = urlsplit(self.path)
        if url.path.startswith("/_s3/"):
            body = lf.s3.objects.get(url.path[5:])
            self.send_response(200 if body else 404)
            self.send_header("content-type", "image/jpeg")
            self.end_headers()
            self.wfile.write(body or b"")
            return
        n = int(self.headers.get("content-length") or 0)
        query = dict(p.split("=", 1) for p in url.query.split("&") if "=" in p)
        r = lf.handler({"headers": dict(self.headers), "rawPath": url.path, "queryStringParameters": query or None,
                        "requestContext": {"http": {"method": self.command}},
                        "body": self.rfile.read(n).decode() if n else None}, None)
        self.send_response(r["statusCode"])
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(r["body"].encode())

    do_GET = do_POST = do_DELETE = _go

    def log_message(self, fmt, *args):
        print(json.dumps({"path": self.path, "status": args[1] if len(args) > 1 else None}))


if __name__ == "__main__":
    print(f"vision on http://127.0.0.1:{PORT} (key {os.environ['WW_VISION_KEY']!r})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
