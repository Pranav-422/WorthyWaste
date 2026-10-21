# WorthyWaste: segregation check (technical report)

## 1. Problem

Indian cities collect household waste door to door, and the Solid Waste Management Rules, 2016 require households
to keep wet (organic) and dry (recyclable) waste apart. Mixed waste cannot be composted or recycled; it goes to
landfill. WorthyWaste pays door-to-door collectors per verified pickup and gives households points when their waste
is separated. Until now the collector simply tapped "separated" or "mixed". That is easy to game: tapping
"separated" every time earns the household points and keeps the customer happy.

The question this work answers: **from the collector's photo of a home's waste, is it separated or mixed?** And
what should happen when the camera and the collector disagree?

## 2. Users

| User | What they get |
| --- | --- |
| Door-to-door collector | A photo check at the door. A bad photo is caught on the spot ("retake"), not days later. |
| Household | Points that are fair: they are held only when a person has to look, never taken on a camera's word alone. |
| WorthyWaste team (ops) | A review queue with the annotated photo and the agent's reasoning, so a decision takes a few seconds. |
| Satin (lender) | A `vision_mismatch` flag on a collector, but only after a person has confirmed it. It feeds the same fraud review as Phase 1. |
| Judges and visitors | `/vision`: upload or take a photo, see every stage, play the reviewer, delete the data. |

## 3. Architecture

Full diagrams: [`ARCHITECTURE.md`](ARCHITECTURE.md). In short:

```
browser ─▶ Vercel: Next.js ─▶ FastAPI (EXIF strip, pHash, GPS, 1/day) ─▶ Postgres
                                   │ X-WW-Key
                                   ▼
             AWS: Lambda function URL ─▶ OpenCV 5 pipeline ─▶ agent decide() ─▶ S3 (photos) + DynamoDB (run, trace)
                                                                              └▶ CloudWatch (logs, EMF metrics, dashboard)
```

## 4. OpenCV implementation

OpenCV `5.0.0` (`opencv-contrib-python-headless==5.0.0.93`). Code: `vision/ww_vision/pipeline.py`.

| # | Stage | OpenCV | Why |
| --- | --- | --- | --- |
| 1 | Decode, resize to 640 px | `imdecode`, `resize(INTER_AREA)` | Phones send 4,000 px photos. 640 px keeps the pipeline under a second. |
| 2 | Quality gate | `Laplacian` variance (sharpness, min 60), mean gray (45–235) | A blurred or dark photo is not judged. The agent asks for a retake instead of guessing. |
| 3 | Colour correction | gray-world white balance, `createCLAHE` on L of `Lab` | Yellow street light or shade must not look like food waste. |
| 4 | Privacy | `FaceDetectorYN` (YuNet, ONNX) + `GaussianBlur` | Doorstep photos catch people. Faces are blurred before anything is stored or classified. |
| 5 | Waste vs floor | `grabCut` (rect-seeded, run at 320 px) + morphology | Separates heaps or bins from the floor. Running it at 320 px is 4× faster with the same mask (1.2 s → 0.31 s). |
| 6 | Heaps | `distanceTransform` → peaks → `connectedComponents` → `watershed` | Splits the waste into heaps, so "two bins side by side" means two heaps. |
| 7 | Parts | `ximgproc.createSuperpixelSLIC` (SLICO, size 80) | Cuts each heap along colour and texture edges, so each part is mostly one item. |
| 8 | Classify | `dnn.readNetFromONNX` (MobileNetV2, cut at its pooling layer → 1280-d) + `ml.LogisticRegression`, Platt-calibrated | Organic or recyclable per part, with a probability that means what it says. |
| 9 | Verdict | area-weighted vote of parts with p ≥ 0.75; a heap is mixed if the minority holds ≥ 12% | One rule, two tuned numbers. Unsure parts don't vote. |
| 10 | Output | `rectangle`, `drawContours`, `addWeighted`, `putText`, `imencode` | Annotated image: heaps, parts coloured by class, verdict banner. |

Every stage is timed, so each result carries its own latency breakdown.

**Design decisions, each one measured:**

- **SLIC parts instead of a 3×3 grid.** A grid cuts across items, and tiles that straddle two items vote wrong. On
  the tuning scenes the grid reached 70%, SLIC with size 40 reached 53%, size 60 78%, size 80 86% and size 100 85%.
  Size 80 was chosen.
- **Logistic regression instead of `cv2.ml.ANN_MLP`.** Same accuracy (93.4% vs 93.6% on TEST), but the ANN output
  saturates at ±1, so every tile reported 0.89. Without a real probability there is no confidence, and without a
  confidence the agent cannot decide when to ask a person.
- **Training on random crops as well as whole photos.** The pipeline classifies pieces of a heap, not whole photos,
  so the classifier is trained on that kind of input.
- **OpenCV 5 specifics.** `ml` moved to the contrib package. The new DNN engine only returns a graph's final output,
  so MobileNetV2 is cut at its pooling layer once with `onnx` (`make_features_model.py`).

## 5. AWS deployment

`vision/deploy.sh` (idempotent; it creates each resource or updates it):

| Service | Resource | Role |
| --- | --- | --- |
| Lambda | `ww-vision`, Python 3.12, x86_64, 2 GB, 30 s, function URL | Runs pipeline + agent. Every route checks `X-WW-Key` with a constant-time compare. |
| S3 | `worthywaste-vision-<account>` | `runs/<id>/safe.jpg` (face-blurred) and `annotated.jpg`, read through 1-hour presigned URLs. Public access is blocked. A lifecycle rule deletes them after 30 days. |
| DynamoDB | `ww-vision-runs`, on-demand | One item per run (result, decision, trace, status). TTL `expires_at` = 30 days. Reviews use a conditional update, so a second reviewer gets 409. |
| IAM | `ww-vision-lambda` | Basic execution, plus only `runs/*` in the bucket and only that table. |
| CloudWatch | log group (30-day retention), EMF metrics `WorthyWaste/Vision`, dashboard `WorthyWaste-Vision` | Latency p50/p90, actions over time, invocations, errors, throttles, duration, recent runs. |

There is no Docker: the zip is built from Linux wheels (`pip download --platform manylinux2014_x86_64`) and
uploaded through S3. It unpacks to about 240 MB, inside Lambda's 250 MB limit. The app stays on Vercel; only the
API calls AWS.

## 6. The agent

Code: `vision/ww_vision/agent.py`. The loop is perception (the pipeline), then a decision (rules over the result,
the collector's mark and the attempt number), then an action. Every step goes into the trace, which DynamoDB stores
and the UI shows as a timeline.

| Action | Trigger | Effect |
| --- | --- | --- |
| `recapture` | bad input, blurry, dark, or confidence < 0.55, on attempt 1 or 2 | Collector app shows "take it again" and the annotated photo. Nothing is recorded. |
| `accept` | camera agrees; or the collector marked "mixed" (the safer mark); or the camera disagrees but is < 0.70 sure | Normal pickup. |
| `needs_approval` | collector said separated, camera ≥ 0.70 sure it is mixed | Pickup recorded, **points held**, card in `/ops` → Photo reviews. |
| `accept_unverified` | Lambda error or timeout, or attempt 3 still not judgeable | Recorded as marked, points held for a person. |

**Human in the loop.** The risky actions are holding a household's points and flagging a collector to the lender.
The agent never takes them alone. A reviewer clicks "Mixed: flag collector" (no points, `vision_mismatch` flag) or
"Separated: release points". The decision is applied with a guarded SQL update and written to the run's trace in
DynamoDB.

**Failure handling.** See the table in [`ARCHITECTURE.md`](ARCHITECTURE.md#where-failures-go). In short: no failure
of the vision service blocks a pickup or costs anyone money. It falls back to the collector's mark with the points
held.

## 7. Evaluation

Reproduce with `python vision/evaluate.py data/raw/DATASET.zip --scenes 300`. Output: `vision/eval/results.json`.
Measured on a laptop CPU (Windows, OpenCV 5.0.0).

**Data.** "Waste Classification Data" by Sashaank Sekar (CC BY-SA 4.0), labelled O (organic) and R (recyclable).
Training: 3,000 photos per class plus a random crop of each. Calibration: 1,000 held-out train crops. **All numbers
below are on the TEST split (2,513 photos), never seen in training or calibration.**

### 7.1 Classifier, per photo (positive = recyclable)

| Accuracy | Precision | Recall | F1 | n |
| --- | --- | --- | --- | --- |
| **93.4%** | 94.0% | 91.0% | 92.5% | 2,513 |

Confusion: TP 1,012 · FP 65 · FN 100 · TN 1,336.

### 7.2 Whole pipeline: separated vs mixed (positive = mixed)

The dataset has one object per photo and no photos of bins at a doorstep. So scenes are composed from TEST photos
on a floor texture: two heaps (one organic, one recyclable) apart; one pure heap; or one heap whose quarters mix
both classes. The decision rule was tuned on scenes built from TEST photos 400–800. These numbers use photos
0–400 and a different random seed.

| Accuracy | Precision | Recall | F1 | n |
| --- | --- | --- | --- | --- |
| **87.0%** | 86.8% | 87.3% | 87.0% | 300 |

| Scene | Accuracy |
| --- | --- |
| Two separate heaps | 84.0% (75) |
| One pure heap | 89.3% (75) |
| One mixed heap | 87.3% (150) |

**Confidence is informative.** Mean confidence is 0.81 when the pipeline is right and 0.66 when it is wrong. At the
agent's thresholds:

| Photos the agent acts on | Share | Accuracy |
| --- | --- | --- |
| confidence ≥ 0.55 (judged, not sent back for a retake) | 88% | **90.9%** |
| "mixed" with confidence ≥ 0.70 (sent to a person) | 70% | 86.8%; the other 13% is what the human review catches |

**Quality gate**, on 40 scenes each: blurred (σ = 6) refused 100%, darkened to 20% refused 100%, random bytes
refused 100%.

### 7.3 Latency (pipeline, laptop CPU, 300 scenes)

| Stage | p50 ms | p95 ms |
| --- | --- | --- |
| decode | 1.1 | 1.2 |
| quality | 2.9 | 3.4 |
| colour (WB + CLAHE) | 9.2 | 10.4 |
| faces (YuNet) | 10.3 | 15.9 |
| segment (GrabCut + watershed) | 313.6 | 507.6 |
| superpixels (SLIC) | 41.7 | 57.7 |
| classify (MobileNetV2 + LR) | 96.6 | 120.9 |
| annotate | 1.6 | 2.1 |
| **total** | **481.9** | **676.1** |

On Lambda: run `python vision/cost.py` after some traffic. It reads the REPORT lines (billed duration, cold starts)
from CloudWatch Logs Insights.

### 7.4 Cost per run (estimate, ap-south-1 list prices)

| Item | Per run |
| --- | --- |
| Lambda: 2 GB × ~0.7 s billed | $0.0000233 |
| Lambda request | $0.0000002 |
| S3: 2 PUTs | $0.0000100 |
| DynamoDB: ~5 write units | $0.0000063 |
| **Total** | **≈ $0.00004 (₹0.003); $0.04 per 1,000 photos** |

For scale: the platform fee per pickup is ₹0.50, so the check costs under 1% of it. `cost.py` replaces the 0.7 s
estimate with the measured billed duration.

## 8. Failure cases (honest)

Images: `vision/eval/failures/`.

1. **Heaps that touch merge into one.** When two heaps touch, GrabCut's mask joins them through a thin bridge,
   watershed keeps them as one heap, and that heap is 27% "other class", so it is called **mixed**
   (`scene_00_separated_two_said-mixed.jpg`). This is the main source of false "mixed" (precision 86.8%). A real
   household's two bins usually stand side by side, so this matters. The fix to try next is an erosion before the
   distance transform, or detecting bins as objects.
2. **A minority that looks like the majority.** Red and green paper bags inside a vegetable heap were classified
   organic, so a mixed heap passed as **separated** (`scene_01_mixed_said-separated.jpg`). Colour-heavy recyclables
   next to vegetables are the hardest case.
3. **The dataset's labels vs Indian reality.** Food in a plastic packet is labelled "organic" in the dataset, and the
   model says recyclable (`classifier_00_true-organic_pred-recyclable.jpg`). In India, wet waste in a plastic bag is
   common. It is, honestly, mixed.
4. **Distribution shift.** Every number above comes from stock-like single-object photos on a synthetic floor. Real
   doorstep photos have bins, bags, dim stairwells and feet. **We expect lower accuracy on real photos until we
   label a pilot set.** That is why the agent never penalises anyone alone.
5. **Segmentation fallback.** With a cluttered background, GrabCut may mark less than 8% of the frame as waste. The
   whole frame is then judged as one heap (`segmentation_fallback` in the result), which is less precise.

## 9. Responsible use

**Privacy**
- Photos are re-encoded by the API before leaving it (Pillow writes pixels only), so EXIF and phone GPS are dropped.
- Faces are blurred (YuNet) before storage and before classification. **Only the blurred copy is stored** in S3,
  and the app's database stores the same blurred copy (`return_safe`). Exception: when the vision service is off
  or fails, the app keeps its own re-encoded copy (EXIF stripped, faces not blurred), as before Phase 3.
- Retention: S3 lifecycle and DynamoDB TTL delete everything after 30 days. Logs are kept 30 days and contain no
  images and no names (`ref` holds a collector id and the last 4 characters of the door code).
- Deletion: "Delete my data" on `/vision` (`DELETE /runs/{id}`) removes the item and both photos immediately.
- Access: the S3 bucket is private, with presigned links that expire in 1 hour. Pickup runs are visible only to the
  ops role; demo runs only to someone holding their random id.

**Fairness and bias**
- The camera can be wrong in both directions (§7, §8). So it **never takes points or raises a flag on its own**: a
  disagreement holds points and waits for a person. Even when the camera is sure, 13% of its "mixed" calls on our
  test scenes were wrong.
- Training data is stock-like photos, mostly not from India. Packaging, food and bins look different here.
  Performance on real doorstep photos is unmeasured, and that is the first thing to measure in the pilot.
- One person's word can still cost another person: a reviewer's "mixed" flags a collector to the lender. That flag
  is informational (it is not in `HOLDING_RULES`), and Satin reviews flags before acting, as in Phase 1.
- Earlier review fix: a dispute flag now needs three different households, so one household cannot freeze a
  collector's loan.

**Limits**
- Two classes only (wet / dry). There is no hazardous, sanitary or e-waste class.
- The photo is optional for the collector. A collector who never takes one is not checked. That is a product choice
  for the pilot, made visible by the share of pickups that have a photo.
- The public endpoint is rate-limited per server instance (30 photos per 10 minutes per IP), not globally.

## 10. Reproduce

```bash
cd vision && .venv/Scripts/pip install -r requirements.txt && .venv/Scripts/python make_features_model.py
.venv/Scripts/python train.py data/raw/DATASET.zip && .venv/Scripts/python evaluate.py data/raw/DATASET.zip
.venv/Scripts/python -m pytest -q
WW_VISION_KEY=... ./deploy.sh
```
