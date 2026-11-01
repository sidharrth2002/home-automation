"""Light-friendly colour palettes from album art.

k-means on a downsampled cover, then: drop near-black / grey / white clusters (bulbs can't show them as
colour), merge clusters with near-identical hues, and rank by coverage x vividness. A cover with no real
colour (e.g. black-and-white) yields an empty palette, so callers can fall back to harmony-based hue.
"""
import colorsys
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

MIN_VALUE = 0.18
MIN_SAT = 0.18
MUTED_SAT, MUTED_SHARE = 0.07, 0.25  # a muted colour still counts if it dominates the cover
MIN_SHARE = 0.02
SAME_HUE = 0.045


@dataclass
class Swatch:
    h: float
    s: float
    v: float
    share: float  # fraction of the cover

    @property
    def hex(self):
        r, g, b = colorsys.hsv_to_rgb(self.h, self.s, self.v)
        return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"

    @property
    def light_sat(self):
        """Album colours are often muted; bulbs wash them out further, so push saturation up."""
        return min(1.0, 0.55 + 0.6 * self.s)


def _kmeans(px, k, iters=12, seed=0):
    rng = np.random.default_rng(seed)
    centers = [px[rng.integers(len(px))]]
    for _ in range(1, k):  # k-means++ seeding
        d = np.min([((px - c) ** 2).sum(1) for c in centers], axis=0)
        centers.append(px[rng.choice(len(px), p=d / d.sum())] if d.sum() > 0 else px[rng.integers(len(px))])
    centers = np.array(centers)
    for _ in range(iters):
        labels = np.argmin(((px[:, None, :] - centers[None]) ** 2).sum(-1), axis=1)
        for j in range(k):
            if np.any(labels == j):
                centers[j] = px[labels == j].mean(0)
    return centers, np.bincount(labels, minlength=k) / len(px)


def extract(image_bytes: bytes, k: int = 8, max_colours: int = 4) -> list[Swatch]:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((64, 64), Image.BILINEAR)
    px = np.asarray(img, dtype=np.float32).reshape(-1, 3) / 255
    centers, shares = _kmeans(px, k)

    swatches = []
    for (r, g, b), share in zip(centers, shares):
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        if v >= MIN_VALUE and s >= MUTED_SAT:
            swatches.append(Swatch(h, s, v, float(share)))

    def score(sw):
        return sw.share * (0.3 + sw.s) * (0.3 + sw.v)

    def same_colour(a, b):
        # Hue is unreliable for greyish colours, so they merge more loosely.
        tol = SAME_HUE if min(a.s, b.s) >= 0.3 else 0.12
        return min(abs(a.h - b.h), 1 - abs(a.h - b.h)) < tol

    # Merge before filtering: k-means often splits one big background colour into several small clusters.
    merged: list[Swatch] = []
    for sw in sorted(swatches, key=lambda x: x.share, reverse=True):
        twin = next((m for m in merged if same_colour(m, sw)), None)
        if twin:
            w = sw.share / (twin.share + sw.share)
            twin.s += w * (sw.s - twin.s)
            twin.v += w * (sw.v - twin.v)
            twin.share += sw.share
        else:
            merged.append(sw)

    kept = [m for m in merged if (m.s >= MIN_SAT and m.share >= MIN_SHARE) or m.share >= MUTED_SHARE]
    return sorted(kept, key=score, reverse=True)[:max_colours]
