from __future__ import annotations

from statistics import median
from typing import Iterable, List, Sequence


def clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0:
        return default
    return numerator / denominator


def rolling_sum(values: Sequence[float], window: int) -> List[float]:
    if window <= 0 or len(values) < window:
        return []
    sums: List[float] = []
    running = sum(values[:window])
    sums.append(running)
    for i in range(window, len(values)):
        running += values[i] - values[i - window]
        sums.append(running)
    return sums


def median_or_none(values: Iterable[float]) -> float | None:
    items = list(values)
    if not items:
        return None
    return float(median(items))


def compute_returns(closes: Sequence[float], periods: int) -> float | None:
    if len(closes) <= periods:
        return None
    past = closes[-(periods + 1)]
    now = closes[-1]
    if past == 0:
        return None
    return now / past - 1

