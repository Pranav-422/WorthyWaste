"""The pickup-photo pipeline: is this household's waste separated (wet and dry apart) or mixed?

    decode -> quality gate -> colour correction -> face blur -> segmentation -> superpixels -> DNN -> verdict

1. Quality gate: sharpness (variance of the Laplacian) and exposure (mean brightness). A blurred or dark
   photo is not judged; the agent asks for a retake.
2. Colour correction: gray-world white balance, then CLAHE on the L channel of Lab, so a yellow street
   light or a shadow does not look like food waste.
3. Privacy: YuNet face detector; any face is blurred before the photo is stored or classified.
4. Segmentation: GrabCut (seeded with the centre of the frame) separates waste from floor; a distance
   transform + watershed splits the waste into heaps or bins.
5. Parts: SLIC superpixels (cv2.ximgproc) cut each heap along colour and texture edges, so a part is
   mostly one item. (A fixed grid cuts across items: 70% vs 86% on the tuning scenes.)
6. Classification: MobileNetV2 (cv2.dnn, ONNX) turns each part into 1280 numbers; a cv2.ml logistic
   regression, calibrated, says organic (wet) or recyclable (dry).
7. Verdict: only parts the classifier is sure of (p >= SURE) vote, weighted by area. A heap whose
   minority class holds >= MIXED_SHARE of that area is mixed. Any mixed heap -> mixed.

Every stage is timed, so the result carries its own latency breakdown.
"""
import time
from pathlib import Path

import cv2
import numpy as np

MODELS = Path(__file__).resolve().parent.parent / "models"
CLASSES = ("organic", "recyclable")   # wet, dry
COLOURS = {"organic": (60, 160, 60), "recyclable": (200, 120, 30)}  # BGR

MAX_SIDE = 640
GRABCUT_SIDE = 320
MIN_SHARPNESS = 60.0         # variance of the Laplacian on the 640-px gray image
MIN_BRIGHTNESS, MAX_BRIGHTNESS = 45, 235
MIN_REGION_SHARE = 0.04      # heaps smaller than 4% of the frame are noise
MIN_WASTE_SHARE = 0.08       # less waste than this in the frame: nothing to judge
SUPERPIXEL = 80              # SLIC region size in px at 640 px (tuned: 40 / 60 / 80 / 100)
MIN_PART = 24                # parts narrower than this are too small to classify
SURE = 0.75                  # a part votes only when the classifier is this sure
MIXED_SHARE = 0.12           # minority share of the sure area that makes a heap mixed (tuned)
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


class Models:
    """Loaded once per process (a warm Lambda keeps them)."""

    def __init__(self, models_dir: Path = MODELS):
        self.embed_net = cv2.dnn.readNetFromONNX(str(models_dir / "mobilenetv2_features.onnx"))
        self.faces = cv2.FaceDetectorYN.create(str(models_dir / "face_detection_yunet_2023mar.onnx"), "",
                                               (320, 320), 0.8)
        head = models_dir / "head.npz"  # trained by train.py (cv2.ml logistic regression)
        if head.exists():
            with np.load(head) as h:
                self.w, self.b = h["w"], float(h["b"])

    def embed(self, crops: list[np.ndarray]) -> np.ndarray:
        """BGR crops -> (n, 1280) MobileNetV2 features."""
        rgb = [cv2.cvtColor(cv2.resize(c, (224, 224), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
               .astype(np.float32) / 255.0 for c in crops]
        blob = cv2.dnn.blobFromImages([(x - MEAN) / STD for x in rgb])
        out = []
        for i in range(blob.shape[0]):  # the new graph engine runs one image per forward
            self.embed_net.setInput(blob[i:i + 1])
            out.append(self.embed_net.forward().reshape(-1))
        return np.stack(out).astype(np.float32)

    def classify(self, crops: list[np.ndarray]) -> np.ndarray:
        """(n, 2) probabilities for CLASSES."""
        p1 = 1 / (1 + np.exp(-(self.embed(crops) @ self.w + self.b)))
        return np.stack([1 - p1, p1], axis=1)

def decode(data: bytes) -> np.ndarray | None:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None or min(img.shape[:2]) < 64:
        return None
    s = MAX_SIDE / max(img.shape[:2])
    return cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img


def quality(img: np.ndarray) -> dict:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    bright = float(gray.mean())
    problems = []
    if sharp < MIN_SHARPNESS:
        problems.append("blurry")
    if bright < MIN_BRIGHTNESS:
        problems.append("too_dark")
    elif bright > MAX_BRIGHTNESS:
        problems.append("too_bright")
    return {"sharpness": round(sharp, 1), "brightness": round(bright, 1), "problems": problems}


def correct_colour(img: np.ndarray) -> np.ndarray:
    f = img.astype(np.float32)
    f *= f.reshape(-1, 3).mean() / np.maximum(f.reshape(-1, 3).mean(axis=0), 1e-3)  # gray world
    lab = cv2.cvtColor(np.clip(f, 0, 255).astype(np.uint8), cv2.COLOR_BGR2Lab)
    lab[..., 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_Lab2BGR)


def blur_faces(models: Models, img: np.ndarray) -> tuple[np.ndarray, int]:
    h, w = img.shape[:2]
    models.faces.setInputSize((w, h))
    _, faces = models.faces.detect(img)
    if faces is None:
        return img, 0
    out = img.copy()
    for f in faces:
        x, y, fw, fh = (int(v) for v in f[:4])
        x0, y0, x1, y1 = max(0, x - fw // 4), max(0, y - fh // 4), min(w, x + fw * 5 // 4), min(h, y + fh * 5 // 4)
        if x1 > x0 and y1 > y0:
            k = max(31, (max(fw, fh) // 2) | 1)
            out[y0:y1, x0:x1] = cv2.GaussianBlur(out[y0:y1, x0:x1], (k, k), 0)
    return out, len(faces)


def segment(img: np.ndarray) -> tuple[np.ndarray, list[dict]]:
    """Waste mask (GrabCut) and the heaps in it (distance transform + watershed)."""
    h, w = img.shape[:2]
    # GrabCut is the slow step (~1 s at 640 px); at 320 px it is 4x faster and the mask is as good.
    s = min(1.0, GRABCUT_SIDE / max(h, w))
    small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    mask = np.zeros((sh, sw), np.uint8)
    rect = (int(sw * 0.04), int(sh * 0.04), int(sw * 0.92), int(sh * 0.92))
    bg, fg = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(small, mask, rect, bg, fg, 4, cv2.GC_INIT_WITH_RECT)
    waste = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    waste = cv2.resize(waste, (w, h), interpolation=cv2.INTER_NEAREST)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    waste = cv2.morphologyEx(cv2.morphologyEx(waste, cv2.MORPH_OPEN, k), cv2.MORPH_CLOSE, k, iterations=2)

    # Heaps: peaks of the distance transform are seeds; watershed grows them back to the mask edge.
    dist = cv2.distanceTransform(waste, cv2.DIST_L2, 5)
    peaks = np.uint8(dist > 0.45 * dist.max()) * 255 if dist.max() > 0 else np.zeros_like(waste)
    n, markers = cv2.connectedComponents(peaks)
    markers = markers + 1
    markers[(waste == 255) & (peaks == 0)] = 0
    markers = cv2.watershed(img, markers)

    regions = []
    for label in range(2, n + 1):
        m = np.uint8(markers == label) * 255
        area = int(cv2.countNonZero(m))
        if area < MIN_REGION_SHARE * h * w:
            continue
        x, y, bw, bh = cv2.boundingRect(m)
        regions.append({"mask": m, "box": [x, y, bw, bh], "area_share": round(area / (h * w), 3)})
    return waste, regions


def parts(img: np.ndarray, region: dict) -> list[tuple[list[int], np.ndarray, int]]:
    """SLIC superpixels of one heap, as (box, crop, area). A heap too small to split is one part."""
    x, y, w, h = region["box"]
    crop, mask = img[y:y + h, x:x + w], region["mask"][y:y + h, x:x + w]
    if min(w, h) < 2 * SUPERPIXEL:
        return [([x, y, w, h], crop, int(cv2.countNonZero(mask)))]
    slic = cv2.ximgproc.createSuperpixelSLIC(cv2.cvtColor(crop, cv2.COLOR_BGR2Lab), cv2.ximgproc.SLICO, SUPERPIXEL)
    slic.iterate(10)
    slic.enforceLabelConnectivity(25)
    labels = slic.getLabels()
    out = []
    for label in range(slic.getNumberOfSuperpixels()):
        m = np.uint8((labels == label) & (mask > 0)) * 255
        area = int(cv2.countNonZero(m))
        if area < SUPERPIXEL * SUPERPIXEL * 0.3:
            continue
        bx, by, bw, bh = cv2.boundingRect(m)
        if bw >= MIN_PART and bh >= MIN_PART:
            out.append(([x + bx, y + by, bw, bh], crop[by:by + bh, bx:bx + bw], area))
    return out or [([x, y, w, h], crop, int(cv2.countNonZero(mask)))]


def judge_heap(votes: list[tuple[float, int]]) -> dict:
    """votes: (p_organic, area) per part. Label, minority share of the sure area, and how clear-cut."""
    sure = [(p, a) for p, a in votes if p >= SURE or p <= 1 - SURE]
    total = sum(a for _, a in sure)
    if not total:
        return {"label": CLASSES[0] if np.mean([p for p, _ in votes]) >= 0.5 else CLASSES[1],
                "minority": 0.0, "mixed": False, "sure_share": 0.0, "clarity": 0.0}
    organic = sum(a for p, a in sure if p >= 0.5) / total
    minority = min(organic, 1 - organic)
    mixed = minority >= MIXED_SHARE
    clarity = min(1.0, (minority - MIXED_SHARE) / MIXED_SHARE) if mixed else (MIXED_SHARE - minority) / MIXED_SHARE
    return {"label": CLASSES[0] if organic >= 0.5 else CLASSES[1], "minority": round(minority, 3), "mixed": mixed,
            "sure_share": round(total / sum(a for _, a in votes), 3), "clarity": round(clarity, 3)}


def annotate(img: np.ndarray, waste: np.ndarray, heaps: list[dict], verdict: str | None) -> np.ndarray:
    out = img.copy()
    overlay = out.copy()
    for heap in heaps:
        for t in heap["parts"]:
            x, y, w, h = t["box"]
            cv2.rectangle(overlay, (x, y), (x + w, y + h), COLOURS[t["label"]], -1)
    out = cv2.addWeighted(overlay, 0.25, out, 0.75, 0)
    contours, _ = cv2.findContours(waste, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, contours, -1, (255, 255, 255), 2)
    for i, heap in enumerate(heaps, 1):
        x, y, w, h = heap["box"]
        colour = (40, 40, 220) if heap["mixed"] else COLOURS[heap["label"]]
        cv2.rectangle(out, (x, y), (x + w, y + h), colour, 3)
        text = f"#{i} MIXED {round(100 * heap['minority'])}%" if heap["mixed"] else f"#{i} {heap['label']}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        ty = y if y - th - 10 < 32 else y - th - 10  # inside the box when the verdict banner would cover it
        cv2.rectangle(out, (x, ty), (x + tw + 8, ty + th + 10), colour, -1)
        cv2.putText(out, text, (x + 4, ty + th + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
    if verdict:
        banner = (40, 150, 40) if verdict == "separated" else (40, 40, 220)
        cv2.rectangle(out, (0, 0), (out.shape[1], 30), banner, -1)
        cv2.putText(out, verdict.upper(), (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return out


def analyze(models: Models, data: bytes) -> dict:
    """The whole pipeline. Returns the result and the annotated + privacy-safe images as JPEG bytes."""
    times: dict[str, float] = {}
    t = time.perf_counter()

    def lap(stage: str):
        nonlocal t
        now = time.perf_counter()
        times[stage] = round((now - t) * 1000, 1)
        t = now

    img = decode(data)
    lap("decode")
    if img is None:
        return {"status": "bad_input", "reason": "Not an image, or smaller than 64 px", "timings_ms": times}
    q = quality(img)
    lap("quality")
    img = correct_colour(img)
    lap("colour")
    img, n_faces = blur_faces(models, img)
    lap("faces")
    safe_jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
    result = {"status": "ok", "quality": q, "faces_blurred": n_faces, "width": img.shape[1], "height": img.shape[0]}
    if q["problems"]:
        result.update(status="low_quality", verdict=None, confidence=0.0, heaps=[])
        times["total"] = round(sum(times.values()), 1)
        return {**result, "timings_ms": times, "images": {"safe": safe_jpeg}}

    waste, regions = segment(img)
    lap("segment")
    waste_share = cv2.countNonZero(waste) / waste.size
    if waste_share < MIN_WASTE_SHARE or not regions:  # GrabCut found nothing: judge the whole frame as one heap
        h, w = img.shape[:2]
        regions = [{"mask": np.full((h, w), 255, np.uint8), "box": [0, 0, w, h], "area_share": 1.0}]
        result["segmentation_fallback"] = True
    found = [(ri, box, crop, area) for ri, r in enumerate(regions) for box, crop, area in parts(img, r)]
    lap("superpixels")
    probs = models.classify([c for _, _, c, _ in found])
    lap("classify")

    heaps = []
    for ri, r in enumerate(regions):
        mine = [(box, area, p) for (rj, box, _, area), p in zip(found, probs) if rj == ri]
        verdict_h = judge_heap([(float(p[0]), area) for _, area, p in mine])
        heaps.append({"box": r["box"], "area_share": r["area_share"], **verdict_h,
                      "parts": [{"box": b, "label": CLASSES[int(np.argmax(p))], "p": round(float(p.max()), 3)}
                                for b, _, p in mine]})
    verdict = "mixed" if any(h["mixed"] for h in heaps) else "separated"
    # Confidence: how much of the waste the classifier is sure about, and how far the deciding heap is
    # from the mixed threshold (the most mixed heap for "mixed", the least clear pure heap for "separated").
    deciding = [h for h in heaps if h["mixed"]] if verdict == "mixed" else heaps
    clarity = max(h["clarity"] for h in deciding) if verdict == "mixed" else min(h["clarity"] for h in deciding)
    sure = float(np.mean([h["sure_share"] for h in heaps]))
    confidence = round(min(1.0, (0.35 + 0.65 * sure) * (0.45 + 0.55 * clarity)), 3)
    result.update(verdict=verdict, confidence=confidence, waste_share=round(waste_share, 3), heaps=heaps,
                  counts={c: sum(1 for h in heaps for t in h["parts"] if t["label"] == c) for c in CLASSES})
    annotated = annotate(img, waste, heaps, verdict)
    lap("annotate")
    times["total"] = round(sum(times.values()), 1)
    return {**result, "timings_ms": times, "images": {
        "safe": safe_jpeg, "annotated": cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()}}
