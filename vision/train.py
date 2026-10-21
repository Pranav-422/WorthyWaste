"""Train the organic / recyclable head on MobileNetV2 features.

    python train.py data/raw/DATASET.zip [--per-class 3000]

Data: "Waste Classification Data" (Sashaank Sekar, CC BY-SA 4.0), 22,564 train and 2,513 test photos,
O (organic) and R (recyclable). The zip is read in place; features are cached in data/features_*.npz.
"""
import argparse
import json
import random
import sys
import zipfile
from pathlib import Path

import cv2
import numpy as np

from ww_vision.pipeline import CLASSES, MODELS, Models

DATA = Path(__file__).resolve().parent / "data"
LABELS = {"O": 0, "R": 1}


def listing(z: zipfile.ZipFile, split: str) -> list[tuple[str, int]]:
    return [(n, LABELS[n.split("/")[2]]) for n in z.namelist()
            if n.startswith(f"DATASET/{split}/") and n.lower().endswith((".jpg", ".jpeg", ".png"))]


def crop(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """A random 35-60% piece of the photo: what a tile of a heap looks like to the classifier."""
    h, w = img.shape[:2]
    f = rng.uniform(0.35, 0.6)
    ch, cw = max(24, int(h * f)), max(24, int(w * f))
    y, x = rng.randint(0, h - ch), rng.randint(0, w - cw)
    return img[y:y + ch, x:x + cw]


def features(models: Models, z: zipfile.ZipFile, items, cache: Path, crops: random.Random | None = None):
    if cache.exists():
        d = np.load(cache, allow_pickle=False)
        return d["x"], d["y"], list(d["names"])
    xs, ys, names = [], [], []
    for i in range(0, len(items), 64):
        batch = items[i:i + 64]
        imgs = [cv2.imdecode(np.frombuffer(z.read(n), np.uint8), cv2.IMREAD_COLOR) for n, _ in batch]
        ok = [(crop(img, crops) if crops else img, (n, y)) for img, (n, y) in zip(imgs, batch) if img is not None]
        xs.append(models.embed([img for img, _ in ok]))
        ys += [y for _, (_, y) in ok]
        names += [n for _, (n, _) in ok]
        print(f"\r{cache.stem}: {i + len(batch)}/{len(items)}", end="", file=sys.stderr)
    print(file=sys.stderr)
    x, y = np.concatenate(xs), np.array(ys, np.int32)
    np.savez(cache, x=x, y=y, names=np.array(names))
    return x, y, names


def train_head(x: np.ndarray, y: np.ndarray, x_cal: np.ndarray, y_cal: np.ndarray) -> tuple[np.ndarray, float]:
    """cv2.ml logistic regression on standardised features, then Platt scaling on held-out crops so the
    probabilities mean what they say. Standardisation and scale are folded into one weight vector:
    p(recyclable) = sigmoid(x . w + b)."""
    mu, sd = x.mean(axis=0), x.std(axis=0) + 1e-6
    lr = cv2.ml.LogisticRegression.create()
    lr.setLearningRate(0.01)
    lr.setIterations(300)
    lr.setRegularization(cv2.ml.LogisticRegression_REG_L2)
    lr.setTrainMethod(cv2.ml.LogisticRegression_MINI_BATCH)
    lr.setMiniBatchSize(256)
    lr.train(cv2.ml.TrainData_create(((x - mu) / sd).astype(np.float32), cv2.ml.ROW_SAMPLE,
                                     y.astype(np.float32).reshape(-1, 1)))
    th = lr.get_learnt_thetas().reshape(-1).astype(np.float64)
    w = th[1:] / sd
    b = th[0] - float((th[1:] * mu / sd).sum())
    z = x_cal @ w + b
    best = None
    for k in np.arange(0.5, 20.01, 0.25):
        pr = np.clip(1 / (1 + np.exp(-k * z)), 1e-6, 1 - 1e-6)
        loss = -np.mean(y_cal * np.log(pr) + (1 - y_cal) * np.log(1 - pr))
        if best is None or loss < best[0]:
            best = (loss, float(k))
    return (w * best[1]).astype(np.float32), b * best[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("zip", type=Path)
    ap.add_argument("--per-class", type=int, default=3000)
    args = ap.parse_args()
    random.seed(7)
    models = Models()
    with zipfile.ZipFile(args.zip) as z:
        train = listing(z, "TRAIN")
        picked = [it for c in LABELS.values() for it in random.sample([t for t in train if t[1] == c], args.per_class)]
        x1, y1, _ = features(models, z, picked, DATA / f"features_train_{args.per_class}.npz")
        x2, y2, _ = features(models, z, picked, DATA / f"features_train_{args.per_class}_crops.npz", random.Random(8))
        held = [t for t in train if t not in set(picked)]
        cal = random.Random(9).sample(held, 1000)
        x3, y3, _ = features(models, z, cal, DATA / "features_calib_crops.npz", random.Random(10))
    x, y = np.concatenate([x1, x2]), np.concatenate([y1, y2])
    w, b = train_head(x, y, x3, y3)
    np.savez(MODELS / "head.npz", w=w, b=np.float32(b))
    p = 1 / (1 + np.exp(-(x3 @ w + b)))
    print(f"train accuracy {np.mean(((x @ w + b) > 0) == (y == 1)):.3f} on {len(y)} photos and crops; "
          f"held-out crops {np.mean((p > 0.5) == (y3 == 1)):.3f}")

if __name__ == "__main__":
    main()
