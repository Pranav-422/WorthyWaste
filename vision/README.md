# Vision service: segregation check + pickup agent

OpenCV 5 pipeline and agent, run as an AWS Lambda. Pipeline steps: [`ww_vision/pipeline.py`](ww_vision/pipeline.py).
Agent: [`ww_vision/agent.py`](ww_vision/agent.py). HTTP routes, S3, DynamoDB and metrics:
[`lambda_function.py`](lambda_function.py). Diagram: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md). Numbers and
limits: [`../docs/TECHNICAL_REPORT.md`](../docs/TECHNICAL_REPORT.md).

## Setup

```bash
cd vision
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # macOS/Linux: .venv/bin/pip
.venv/Scripts/python make_features_model.py        # downloads MobileNetV2 + YuNet (OpenCV Zoo), cuts MobileNetV2 at its pool layer
```

`models/head.npz` (the trained classifier, 5 KB) is in the repo. To retrain it you need the dataset.

## Train and evaluate

```bash
mkdir -p data/raw && curl -L -o data/raw/DATASET.zip \
  https://huggingface.co/datasets/bryandts/waste_organic_anorganic_classification/resolve/main/DATASET.zip
.venv/Scripts/python train.py data/raw/DATASET.zip          # ~4 min on a laptop CPU, features cached in data/
.venv/Scripts/python evaluate.py data/raw/DATASET.zip       # writes eval/results.json, eval/failures/*.jpg
```

Data: "Waste Classification Data" by Sashaank Sekar (CC BY-SA 4.0), 22,564 train and 2,513 test photos, labelled
O (organic) and R (recyclable). Training uses 3,000 photos per class plus a random crop of each. Platt scaling uses
1,000 held-out train crops. Evaluation runs on the TEST split only. The tuning scenes and the evaluation scenes are
built from different TEST photos.

## Test

```bash
.venv/Scripts/python -m pytest -q     # pipeline, agent, Lambda handler with fake S3/DynamoDB; no AWS or dataset needed
```

## Run locally (no AWS)

```bash
WW_VISION_KEY=local .venv/Scripts/python local_server.py     # same handler; S3 and DynamoDB in memory
```

## Deploy

```bash
WW_VISION_KEY=<32+ random chars> ./deploy.sh
```

The script is idempotent. It builds a zip from Linux wheels (`pip download --platform manylinux2014_x86_64`, no
Docker needed), uploads it through S3, and creates or updates the bucket, table, role, Lambda, function URL and
dashboard. At the end it prints `WW_VISION_URL`. The zip unpacks to about 240 MB; the Lambda limit is 250 MB, and
the script checks this.

API (all calls need the `X-WW-Key` header):

| Route | What |
| --- | --- |
| `POST /analyze` | `{image_b64, marked?, attempt?, source, ref?, return_safe?}` → run (result, action, trace, image URLs) |
| `GET /runs/{id}` | one run, with fresh presigned image URLs (1 h) |
| `POST /runs/{id}/review` | `{approve, reviewer, note?}`; conditional, a second review gets 409 |
| `DELETE /runs/{id}` | deletes the item and both photos |

CloudWatch metrics, namespace `WorthyWaste/Vision`, by `Action`: `RunLatencyMs`, `PipelineMs`, `Confidence`,
`Runs`; plus `Reviews` by `Outcome`. The dashboard is `WorthyWaste-Vision`.
