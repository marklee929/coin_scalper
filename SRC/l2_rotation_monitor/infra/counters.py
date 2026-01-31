import json
import time
from pathlib import Path
from typing import Dict

from config.settings import STORAGE_DIR
from infra.logger import logger
from infra.state_store import atomic_write_json

STATE_PATH = Path(STORAGE_DIR) / "gate_stats.json"

_DEFAULT_COUNTS = {
    "btc_gate_hits": 0,
    "volume_dead_zone_hits": 0,
    "leader_fail": 0,
    "lag_fail": 0,
    "rate_limit_blocked": 0,
}


def _today_date(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _load_state(now_ts: float) -> Dict:
    if not STATE_PATH.exists():
        return {"date": _today_date(now_ts), **_DEFAULT_COUNTS}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as exc:
        logger.warning(f"gate_stats.json load failed: {exc}")
        return {"date": _today_date(now_ts), **_DEFAULT_COUNTS}

    if state.get("date") != _today_date(now_ts):
        return {"date": _today_date(now_ts), **_DEFAULT_COUNTS}

    for key, value in _DEFAULT_COUNTS.items():
        state.setdefault(key, value)
    return state


def _save_state(state: Dict) -> None:
    try:
        atomic_write_json(STATE_PATH, state)
    except Exception as exc:
        logger.warning(f"gate_stats.json save failed: {exc}")


def increment_counter(key: str, now_ts: float | None = None, amount: int = 1) -> Dict:
    now_ts = now_ts or time.time()
    state = _load_state(now_ts)
    state[key] = int(state.get(key, 0)) + amount
    _save_state(state)
    return state

