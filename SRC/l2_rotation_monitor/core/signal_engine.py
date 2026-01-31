from __future__ import annotations

from typing import Dict, List, Tuple


def select_leader(metrics: Dict[str, Dict], leader_gap: float, min_ret_60: float) -> Tuple[str | None, str]:
    if len(metrics) < 2:
        return None, "not_enough_symbols"

    ranked = sorted(metrics.items(), key=lambda item: item[1].get("score", 0.0), reverse=True)
    leader_symbol, leader_metrics = ranked[0]
    runner_symbol, runner_metrics = ranked[1]

    score_gap = leader_metrics.get("score", 0.0) - runner_metrics.get("score", 0.0)
    if score_gap < leader_gap:
        return None, "leader_gap_not_met"
    if leader_metrics.get("ret_60", 0.0) < min_ret_60:
        return None, "leader_min_return_not_met"

    return leader_symbol, "leader_selected"


def select_lags(
    metrics: Dict[str, Dict],
    leader_symbol: str,
    lag_gap: float,
    lag_floor_ret_60: float,
    lag_vol_floor: float,
) -> Tuple[List[str], str]:
    if leader_symbol not in metrics:
        return [], "leader_missing"

    leader_ret = metrics[leader_symbol].get("ret_60", 0.0)
    lags: List[str] = []
    for symbol, data in metrics.items():
        if symbol == leader_symbol:
            continue
        ret_60 = data.get("ret_60", 0.0)
        vol_chg = data.get("vol_chg", 0.0)
        if ret_60 <= leader_ret - lag_gap and ret_60 >= lag_floor_ret_60 and vol_chg >= lag_vol_floor:
            lags.append(symbol)

    if not lags:
        return [], "no_lag_candidates"
    return sorted(lags), "lags_selected"


def make_signal_key(leader: str, lags: List[str]) -> str:
    return f"{leader}|{','.join(sorted(lags))}"

