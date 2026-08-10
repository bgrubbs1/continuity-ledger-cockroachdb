"""A small deterministic demo encoder, explicitly not a trained model."""

from __future__ import annotations

import hashlib
import math
import re

DIMENSIONS = 32
_TOKEN = re.compile(r"[a-z0-9]+")


def feature_hash(text: str, dimensions: int = DIMENSIONS) -> tuple[float, ...]:
    if dimensions < 8:
        raise ValueError("dimensions must be at least 8")
    values = [0.0] * dimensions
    for token in _TOKEN.findall(text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        values[index] += sign
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        raise ValueError("text must contain an alphanumeric token")
    return tuple(value / norm for value in values)


def cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise ValueError("vector dimensions must match")
    return sum(a * b for a, b in zip(left, right, strict=True))


def vector_literal(values: tuple[float, ...]) -> str:
    return "[" + ",".join(f"{value:.9f}" for value in values) + "]"

