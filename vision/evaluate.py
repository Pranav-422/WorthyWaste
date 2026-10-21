"""Evaluate the vision pipeline; writes eval/results.json and eval/failures/*.jpg.

    python evaluate.py data/raw/DATASET.zip [--scenes 300]

1. Classifier: every photo of the held-out TEST split (never seen in training), organic vs recyclable.
2. Whole pipeline on composed scenes. The dataset has one object per photo and no "bin at a doorstep"
   photos, so scenes are built from TEST photos on a floor texture:
     separated  = two heaps, one organic and one recyclable, apart on the floor; or one pure heap
     mixed      = one heap whose quarters mix organic and recyclable photos
   "Mixed" is the positive class: it is what the check exists to catch.
3. Quality gate: the same scenes blurred, darkened and as random bytes must be refused, not judged.
4. Latency per stage (p50 / p95) on this machine.
"""
import argparse
import json
import random
import time
import zipfile
from pathlib import Path

import cv2
import numpy as np

from train import DATA, features, listing
from ww_vision import agent
from ww_vision.pipeline import CLASSES, MODELS, Models, analyze

OUT = Path(__file__).resolve().parent / "eval"


def prf(tp, fp, fn, tn) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"accuracy": round((tp + tn) / max(1, tp + fp + fn + tn), 4), "precision": round(p, 4),
            "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
            "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn}, "n": tp + fp + fn + tn}


def floor(rng: random.Random, h=480, w=640) -> np.ndarray:
    base = np.array([rng.randint(110, 170), rng.randint(110, 160), rng.randint(100, 150)], np.float32)
    noise = cv2.GaussianBlur(np.random.default_rng(rng.randint(0, 9999)).normal(0, 18, (h, w, 1)).astype(np.float32),
                             (0, 0), 3)[..., None]
    return np.clip(base + noise, 0, 255).astype(np.uint8)


def heap(imgs: list[np.ndarray], size: int) -> tuple[np.ndarray, np.ndarray]:
    """One heap: 1 photo, or a 2 x 2 collage, inside a rough ellipse."""
    if len(imgs) == 1:
        tile = cv2.resize(imgs[0], (size, size))
    else:
        q = [cv2.resize(i, (size // 2, size // 2)) for i in imgs]
        tile = np.vstack([np.hstack(q[:2]), np.hstack(q[2:])])
        tile = cv2.resize(tile, (size, size))
    mask = np.zeros((size, size), np.uint8)
    cv2.ellipse(mask, (size // 2, size // 2), (size // 2 - 4, size // 2 - 4), 0, 0, 360, 255, -1)
    return tile, cv2.GaussianBlur(mask, (9, 9), 0)


def paste(bg: np.ndarray, tile: np.ndarray, mask: np.ndarray, x: int, y: int) -> None:
    h, w = mask.shape
    a = (mask.astype(np.float32) / 255)[..., None]
    bg[y:y + h, x:x + w] = (a * tile + (1 - a) * bg[y:y + h, x:x + w]).astype(np.uint8)


def scene(rng: random.Random, pool: dict[int, list[np.ndarray]], kind: str) -> np.ndarray:
    bg = floor(rng)
    pick = lambda c, n: [rng.choice(pool[c]) for _ in range(n)]  # noqa: E731
    if kind == "separated_two":
        for (c, x) in ((0, 30), (1, 340)):
            tile, mask = heap(pick(c, 4), 270)
            paste(bg, tile, mask, x + rng.randint(-10, 10), 100 + rng.randint(-40, 40))
    elif kind == "separated_one":
        tile, mask = heap(pick(rng.randint(0, 1), 4), 360)
        paste(bg, tile, mask, 140 + rng.randint(-40, 40), 60 + rng.randint(-30, 30))
    else:
        n_org = rng.choice([2, 2, 1, 3])
        imgs = pick(0, n_org) + pick(1, 4 - n_org)
        rng.shuffle(imgs)
        tile, mask = heap(imgs, 360)
        paste(bg, tile, mask, 140 + rng.randint(-40, 40), 60 + rng.randint(-30, 30))
    return bg


def selective(scored, threshold) -> dict:
    kept = [(said, truth) for conf, said, truth, status in scored if status == "ok" and conf >= threshold]
    return {"share_of_photos": round(len(kept) / max(1, len(scored)), 3),
            "accuracy": round(sum(s == t for s, t in kept) / len(kept), 4) if kept else None, "n": len(kept)}


def pct(xs, q):
    return round(float(np.percentile(xs, q)), 1) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("zip", type=Path)
    ap.add_argument("--scenes", type=int, default=300)
    args = ap.parse_args()
    (OUT / "failures").mkdir(parents=True, exist_ok=True)
    models = Models()
    results: dict = {"opencv": cv2.__version__}

    # 1. classifier on the full TEST split
    with zipfile.ZipFile(args.zip) as z:
        test = listing(z, "TEST")
        x, y, names = features(models, z, test, DATA / "features_test.npz")
        p1 = 1 / (1 + np.exp(-(x @ models.w + models.b)))
        pred = (p1 > 0.5).astype(int)
        # positive = recyclable (dry)
        tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
        fn = int(((pred == 0) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
        results["classifier"] = {**prf(tp, fp, fn, tn), "positive": "recyclable", "split": "TEST (held out)"}
        wrong = [i for i in np.argsort(-np.abs(p1 - 0.5)) if pred[i] != y[i]][:12]
        for k, i in enumerate(wrong):
            img = cv2.imdecode(np.frombuffer(z.read(names[i]), np.uint8), cv2.IMREAD_COLOR)
            cv2.imwrite(str(OUT / "failures" / f"classifier_{k:02d}_true-{CLASSES[y[i]]}_pred-{CLASSES[pred[i]]}.jpg"),
                        img)
        rng = random.Random(11)
        idx = list(range(len(test)))
        rng.shuffle(idx)
        pool = {0: [], 1: []}
        for i in idx[:400]:
            n, c = test[i]
            img = cv2.imdecode(np.frombuffer(z.read(n), np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                pool[c].append(img)

    # 2. whole pipeline on composed scenes
    kinds = ["separated_two", "separated_one", "mixed", "mixed"]
    stage: dict[str, list[float]] = {}
    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    actions: dict[str, int] = {}
    by_kind: dict[str, dict] = {}
    conf_right, conf_wrong, saved, scored = [], [], 0, []
    for i in range(args.scenes):
        kind = kinds[i % len(kinds)]
        img = scene(rng, pool, kind)
        r = analyze(models, cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes())
        for k, v in r["timings_ms"].items():
            stage.setdefault(k, []).append(v)
        d = agent.decide({k: v for k, v in r.items() if k != "images"}, marked="separated", attempt=1)
        actions[d["action"]] = actions.get(d["action"], 0) + 1
        truth_mixed, said_mixed = kind == "mixed", r.get("verdict") == "mixed"
        key = ("tp" if said_mixed else "fn") if truth_mixed else ("fp" if said_mixed else "tn")
        counts[key] += 1
        bk = by_kind.setdefault(kind, {"n": 0, "correct": 0})
        bk["n"] += 1
        bk["correct"] += int(said_mixed == truth_mixed)
        (conf_right if said_mixed == truth_mixed else conf_wrong).append(r.get("confidence") or 0)
        scored.append((r.get("confidence") or 0, said_mixed, truth_mixed, r["status"]))
        if said_mixed != truth_mixed and saved < 12 and "annotated" in r["images"]:
            (OUT / "failures" / f"scene_{saved:02d}_{kind}_said-{r['verdict']}.jpg").write_bytes(r["images"]["annotated"])
            saved += 1
        if i < 4:
            (OUT / f"example_{kind}_{i}.jpg").write_bytes(r["images"].get("annotated", r["images"]["safe"]))
    results["pipeline"] = {
        **prf(counts["tp"], counts["fp"], counts["fn"], counts["tn"]), "positive": "mixed",
        "by_kind": {k: {**v, "accuracy": round(v["correct"] / v["n"], 4)} for k, v in by_kind.items()},
        "mean_confidence_correct": round(float(np.mean(conf_right)), 3) if conf_right else None,
        "mean_confidence_wrong": round(float(np.mean(conf_wrong)), 3) if conf_wrong else None,
        "agent_actions_when_collector_says_separated": actions,
        # The agent's thresholds, checked: how right the camera is on the photos it acts on.
        "at_agent_thresholds": {
            f"confidence>={agent.MIN_CONFIDENCE} (judged, not retaken)": selective(scored, agent.MIN_CONFIDENCE),
            f"mixed with confidence>={agent.DISAGREE_CONFIDENCE} (sent to a person)": selective(
                [x for x in scored if x[1]], agent.DISAGREE_CONFIDENCE),
        },
        "latency_ms": {k: {"p50": pct(v, 50), "p95": pct(v, 95)} for k, v in stage.items()},
    }

    # 3. quality gate
    gate = {"blurred": 0, "dark": 0, "garbage": 0, "n": 40}
    for i in range(gate["n"]):
        img = scene(rng, pool, kinds[i % len(kinds)])
        enc = lambda m: cv2.imencode(".jpg", m)[1].tobytes()  # noqa: E731
        gate["blurred"] += analyze(models, enc(cv2.GaussianBlur(img, (0, 0), 6)))["status"] == "low_quality"
        gate["dark"] += analyze(models, enc((img * 0.2).astype(np.uint8)))["status"] == "low_quality"
        gate["garbage"] += analyze(models, bytes(random.Random(i).randbytes(5000)))["status"] == "bad_input"
    results["quality_gate"] = {k: (round(v / gate["n"], 3) if k != "n" else v) for k, v in gate.items()}

    results["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (OUT / "results.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
