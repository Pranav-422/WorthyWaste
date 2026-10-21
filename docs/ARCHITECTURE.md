# Architecture

WorthyWaste runs as two parts. The **app** is on Vercel: Next.js web, FastAPI API and Postgres. The **vision
service** is on AWS: Lambda, S3, DynamoDB and CloudWatch. The API is the only thing that calls the vision service,
and every call carries a shared secret.

```mermaid
flowchart LR
  subgraph Phone["Collector / visitor (browser, phone)"]
    CAM["Camera or upload<br/>/collector · /vision"]
    OPS["Reviewer<br/>/ops → Photo reviews"]
  end

  subgraph Vercel["Vercel"]
    WEB["Next.js web"]
    API["FastAPI API<br/>re-encode JPEG (EXIF/GPS stripped)<br/>pHash duplicate check · GPS 50 m · 1/day"]
    PG[("Postgres (Neon)<br/>pickups · fees · points<br/>fraud_flags · review")]
  end

  subgraph AWS["AWS ap-south-1"]
    URL["Lambda function URL<br/>X-WW-Key check"]
    subgraph L["Lambda ww-vision (Python 3.12, 2 GB)"]
      direction TB
      P1["1 decode · resize 640"] --> P2["2 quality gate<br/>Laplacian variance · brightness"]
      P2 --> P3["3 gray-world WB + CLAHE (Lab)"]
      P3 --> P4["4 YuNet face detect → blur"]
      P4 --> P5["5 GrabCut (320 px) → mask<br/>distance transform + watershed → heaps"]
      P5 --> P6["6 SLIC superpixels per heap"]
      P6 --> P7["7 MobileNetV2 (cv2.dnn, ONNX) 1280-d<br/>+ cv2.ml logistic regression (calibrated)"]
      P7 --> P8["8 area-weighted heap verdict<br/>+ confidence + annotated image"]
      P8 --> AG{"Agent decide()"}
    end
    S3[("S3<br/>runs/id/safe.jpg (face-blurred)<br/>runs/id/annotated.jpg<br/>30-day lifecycle")]
    DDB[("DynamoDB ww-vision-runs<br/>result · decision · trace<br/>status · TTL 30 days")]
    CW["CloudWatch<br/>logs + EMF metrics<br/>dashboard WorthyWaste-Vision"]
  end

  CAM --> WEB --> API
  API -- "POST /analyze" --> URL --> P1
  AG -- recapture --> API
  AG -- "accept / needs_approval /<br/>accept_unverified" --> API
  AG --> S3
  AG --> DDB
  L --> CW
  API --> PG
  OPS --> WEB
  API -- "POST /runs/id/review<br/>(human step)" --> URL
```

## The agent loop

```mermaid
stateDiagram-v2
  [*] --> Perceive: photo + collector's mark + attempt
  Perceive --> Decide: pipeline result (or error)
  Decide --> Recapture: bad input / blurry / dark / confidence < 0.55 (attempt < 3)
  Recapture --> Perceive: collector retakes (attempt + 1)
  Decide --> Accept: camera agrees, or marked "mixed"
  Decide --> NeedsApproval: marked separated, camera >= 0.70 sure it is mixed
  Decide --> Unverified: Lambda down, or 3 photos not judgeable
  NeedsApproval --> Human: points held, flag proposed
  Unverified --> Human: points held
  Human --> Mixed: reviewer agrees: no points, vision_mismatch flag
  Human --> Separated: reviewer disagrees: points released
  Accept --> [*]
  Mixed --> [*]
  Separated --> [*]
```

The agent never holds a household's points or flags a collector on its own: it **proposes** that, and a person
decides in `/ops` (or on `/vision`, where the visitor plays the reviewer for their own demo run).

## Where failures go

| Failure | Handling |
| --- | --- |
| Not an image / under 64 px | `bad_input` → recapture |
| Blurry (Laplacian var < 60), too dark (< 45) or too bright (> 235) | `low_quality` → recapture, not judged |
| GrabCut finds < 8% waste | whole frame judged as one heap (`segmentation_fallback`) |
| Classifier unsure | unsure parts (p < 0.75) don't vote; low overall confidence → recapture |
| Exception inside the pipeline | caught in the Lambda → `accept_unverified` |
| Lambda timeout / network / 5xx | caught in the API (`_vision_pickup`) → `accept_unverified`; reason on `/api/health` |
| Two reviewers at once | DynamoDB conditional update and a guarded SQL `UPDATE ... WHERE review = 'pending'` → second gets 409 |
