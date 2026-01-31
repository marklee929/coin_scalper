from __future__ import annotations

from typing import Dict, List, Tuple


def btc_gate(candles: List[Dict], abs_ret_threshold: float) -> Tuple[bool, float | None]:
    if len(candles) < 2:
        return False, None
    prev_close = float(candles[-2]["close"])
    last_close = float(candles[-1]["close"])
    if prev_close == 0:
        return False, None
    ret_15 = last_close / prev_close - 1
    return abs(ret_15) <= abs_ret_threshold, float(ret_15)

