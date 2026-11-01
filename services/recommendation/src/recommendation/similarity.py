"""Product similarity from feature vectors.

Each product gets a deterministic feature vector derived from its id and categories; products
sharing categories point in similar directions. Ranking is by cosine similarity.
"""

import hashlib
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

DIMENSIONS = 512

Vector = list[float]


@dataclass(frozen=True)
class Item:
    id: str
    categories: tuple[str, ...]


def _seeded(text: str) -> random.Random:
    return random.Random(int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big"))


def feature_vector(item: Item) -> Vector:
    vector = [0.0] * DIMENSIONS
    for source, weight in [(item.id, 0.4), *((c, 1.0) for c in item.categories)]:
        rng = _seeded(source)
        for i in range(DIMENSIONS):
            vector[i] += weight * rng.gauss(0.0, 1.0)
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def cosine(a: Vector, b: Vector) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def rank(target: str, vectors: dict[str, Vector], limit: int) -> list[str]:
    base = vectors[target]
    scored = sorted(
        ((cosine(base, v), item_id) for item_id, v in vectors.items() if item_id != target),
        reverse=True,
    )
    return [item_id for _, item_id in scored[:limit]]


class VectorCache:
    """Caches feature vectors.

    "v1" keeps one vector per product. "v2" keeps a vector set per (session, product) so that
    per-session re-weighting can be added later.
    """

    def __init__(self, mode: str = "v1") -> None:
        self.mode = mode
        self._entries: dict[tuple[str, ...], dict[str, Vector]] = {}

    def vectors(self, items: Sequence[Item], session_id: str, product_id: str) -> dict[str, Vector]:
        key = (session_id, product_id) if self.mode == "v2" else ("all",)
        cached = self._entries.get(key)
        if cached is None or cached.keys() != {i.id for i in items}:
            cached = {i.id: feature_vector(i) for i in items}
            self._entries[key] = cached
        return cached

    def __len__(self) -> int:
        return len(self._entries)
