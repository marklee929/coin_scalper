from __future__ import annotations

from typing import Dict, List

from core.indicators import clip, compute_returns, median_or_none, rolling_sum, safe_div


def compute_metrics(candles: List[Dict]) -> Dict | None:
    if len(candles) < 8:
        return None

    closes = [float(c["close"]) for c in candles]
    volumes = [float(c["volume"]) for c in candles]

    ret_60 = compute_returns(closes, periods=4)
    ret_30 = compute_returns(closes, periods=2)
    if ret_60 is None:
        return None

    vol_60 = sum(volumes[-4:])
    vol_prev_60 = sum(volumes[-8:-4])
    vol_chg = safe_div(vol_60, vol_prev_60, default=0.0) - 1 if vol_prev_60 else 0.0

    window_sums = rolling_sum(volumes[-96:], 4) if len(volumes) >= 96 else rolling_sum(volumes, 4)
    vol_60_median = median_or_none(window_sums)

    score = ret_60 + 0.3 * clip(vol_chg, -1.0, 3.0)

    return {
        "ret_60": float(ret_60),
        "ret_30": float(ret_30) if ret_30 is not None else None,
        "vol_60": float(vol_60),
        "vol_prev_60": float(vol_prev_60),
        "vol_chg": float(vol_chg),
        "vol_60_median": float(vol_60_median) if vol_60_median is not None else None,
        "score": float(score),
        "last_close": float(closes[-1]),
    }

