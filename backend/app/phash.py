"""Perceptual hash (pHash), same method as the `imagehash` library: 32×32 greyscale, 2-D DCT, keep the
8×8 lowest frequencies, set each bit by whether it is above their median. Pure Python + Pillow, so the
serverless bundle needs no numpy/scipy. Near-identical photos land within a few bits of each other."""
import io
import math
import statistics

from PIL import Image

_N = 32
_K = 8
# DCT-II basis for the K lowest frequencies (unnormalised; scaling doesn't change a median test).
_BASIS = [[math.cos(math.pi / _N * (x + 0.5) * u) for x in range(_N)] for u in range(_K)]


def phash(data: bytes) -> str:
    img = Image.open(io.BytesIO(data)).convert("L").resize((_N, _N), Image.Resampling.LANCZOS)
    px = list(img.tobytes())  # mode "L": one byte per pixel
    grid = [px[r * _N:(r + 1) * _N] for r in range(_N)]
    # DCT along rows, then along columns, keeping only the low-frequency block.
    rows = [[sum(b * v for b, v in zip(_BASIS[u], row)) for u in range(_K)] for row in grid]
    low = [[sum(_BASIS[v][y] * rows[y][u] for y in range(_N)) for u in range(_K)] for v in range(_K)]
    flat = [c for row in low for c in row]
    med = statistics.median(flat)
    bits = "".join("1" if c > med else "0" for c in flat)
    return f"{int(bits, 2):016x}"


def distance(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()
