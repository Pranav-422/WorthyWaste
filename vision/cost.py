"""Cost per run, from the Lambda's own REPORT lines in CloudWatch (after some runs on AWS).

    python cost.py [--hours 24]

Prices: ap-south-1 list prices, checked when this was written. They are inputs here, so update them if AWS
changes them.
"""
import argparse
import time

import boto3

REGION = "ap-south-1"
LAMBDA_GB_S = 0.0000166667      # x86, per GB-second
LAMBDA_REQUEST = 0.20 / 1e6
S3_PUT = 0.005 / 1000           # 2 PUTs per run (face-blurred + annotated photo)
DDB_WRITE = 1.25 / 1e6          # on-demand write request unit; a run item is ~3-5 KB -> ~5 WRU
WRU_PER_RUN = 5

ap = argparse.ArgumentParser()
ap.add_argument("--hours", type=float, default=24)
args = ap.parse_args()
logs = boto3.client("logs", region_name=REGION)
q = logs.start_query(
    logGroupName="/aws/lambda/ww-vision", startTime=int(time.time() - args.hours * 3600), endTime=int(time.time()),
    queryString="filter @type = 'REPORT' | stats count() as runs, avg(@billedDuration) as billed_ms, "
                "pct(@billedDuration, 95) as p95_ms, max(@memorySize) as mem_bytes, "
                "sum(ispresent(@initDuration)) as cold, avg(@initDuration) as init_ms")
while (r := logs.get_query_results(queryId=q["queryId"]))["status"] in ("Running", "Scheduled"):
    time.sleep(1)
row = {f["field"]: float(f["value"]) for f in r["results"][0]} if r["results"] else None
if not row:
    raise SystemExit("No runs in that window")
gb = row["mem_bytes"] / 1024 ** 3
compute = gb * row["billed_ms"] / 1000 * LAMBDA_GB_S
total = compute + LAMBDA_REQUEST + 2 * S3_PUT + WRU_PER_RUN * DDB_WRITE
print(f"runs {row['runs']:.0f} | billed avg {row['billed_ms']:.0f} ms, p95 {row['p95_ms']:.0f} ms | "
      f"cold starts {row.get('cold', 0):.0f} (init avg {row.get('init_ms', 0):.0f} ms)")
print(f"cost per run ${total:.7f}  (Lambda ${compute:.7f}, S3 ${2 * S3_PUT:.7f}, DynamoDB ${WRU_PER_RUN * DDB_WRITE:.7f})"
      f"  -> ${total * 1000:.4f} per 1,000 runs")
