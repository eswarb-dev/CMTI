from __future__ import annotations

import random


def bounded_noise(rng: random.Random, base: float, spread: float, low: float, high: float, digits: int = 3) -> float:
    return round(max(low, min(high, base + rng.uniform(-spread, spread))), digits)


def clamp(value: float, low: float, high: float, digits: int = 3) -> float:
    return round(max(low, min(high, value)), digits)


def reject_counts(actual: int, rate: float) -> tuple[int, int]:
    rejected = max(0, min(actual, round(actual * rate)))
    return actual - rejected, rejected

