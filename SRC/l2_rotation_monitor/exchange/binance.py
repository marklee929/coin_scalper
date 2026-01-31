import time
from typing import Dict, List

import requests

from config.settings import BINANCE_BASE_URL
from infra.logger import logger
from infra.storage import append_event

_NEXT_ALLOWED_TS = 0.0
_BACKOFF_SEC = 5
_LOG_MIN_INTERVAL_SEC = 600
_BACKOFF_STATE = {
    "active": False,
    "reason": None,
    "backoff_sec": None,
    "last_log_ts": 0.0,
}
_FETCH_FAIL_STATE = {
    "reason": None,
    "status": None,
    "last_log_ts": 0.0,
}


def _set_backoff(seconds: int) -> float:
    global _NEXT_ALLOWED_TS, _BACKOFF_SEC
    _BACKOFF_SEC = min(max(seconds, 5), 300)
    _NEXT_ALLOWED_TS = time.time() + _BACKOFF_SEC
    return _NEXT_ALLOWED_TS


def _log_backoff_state(symbol_pair: str, reason: str, backoff_sec: int, next_allowed_ts: float, now: float) -> None:
    state = _BACKOFF_STATE
    should_log = False
    if not state["active"]:
        should_log = True
    elif state["reason"] != reason:
        should_log = True
    elif state["backoff_sec"] != backoff_sec:
        should_log = True
    elif now - state["last_log_ts"] >= _LOG_MIN_INTERVAL_SEC:
        should_log = True

    if not should_log:
        return
    wait_sec = max(0.0, next_allowed_ts - now)
    append_event(
        {
            "ts": int(now),
            "type": "backoff",
            "symbol_pair": symbol_pair,
            "reason": reason,
            "backoff_sec": int(backoff_sec),
            "wait_sec": round(float(wait_sec), 2),
            "next_allowed_ts": int(next_allowed_ts),
        }
    )
    state["active"] = True
    state["reason"] = reason
    state["backoff_sec"] = backoff_sec
    state["last_log_ts"] = now


def _log_fetch_fail(symbol_pair: str, reason: str, detail: str | None = None, status: int | None = None) -> None:
    state = _FETCH_FAIL_STATE
    now = time.time()
    if (
        state["reason"] == reason
        and state["status"] == status
        and now - state["last_log_ts"] < _LOG_MIN_INTERVAL_SEC
    ):
        return
    payload = {
        "ts": int(now),
        "type": "fetch_fail",
        "symbol_pair": symbol_pair,
        "reason": reason,
    }
    if status is not None:
        payload["status"] = int(status)
    if detail:
        payload["detail"] = detail[:200]
    append_event(payload)
    state["reason"] = reason
    state["status"] = status
    state["last_log_ts"] = now


def _clear_fetch_fail_state() -> None:
    _FETCH_FAIL_STATE["reason"] = None
    _FETCH_FAIL_STATE["status"] = None
    _FETCH_FAIL_STATE["last_log_ts"] = 0.0


def fetch_klines(symbol_pair: str, interval: str, limit: int) -> List[Dict]:
    global _NEXT_ALLOWED_TS
    now = time.time()
    if now >= _NEXT_ALLOWED_TS and _BACKOFF_STATE["active"]:
        _BACKOFF_STATE["active"] = False
        _BACKOFF_STATE["reason"] = None
        _BACKOFF_STATE["backoff_sec"] = None

    if now < _NEXT_ALLOWED_TS:
        reason = _BACKOFF_STATE["reason"] or "active_backoff"
        backoff_sec = _BACKOFF_STATE["backoff_sec"] or _BACKOFF_SEC
        _log_backoff_state(symbol_pair, reason, backoff_sec, _NEXT_ALLOWED_TS, now)
        return []

    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {"symbol": symbol_pair, "interval": interval, "limit": limit}

    try:
        res = requests.get(url, params=params, timeout=10)
        if res.status_code != 200:
            next_allowed = _set_backoff(_BACKOFF_SEC * 2)
            _log_fetch_fail(symbol_pair, "http_status", res.text[:200], res.status_code)
            _log_backoff_state(symbol_pair, "http_status", _BACKOFF_SEC, next_allowed, time.time())
            logger.warning(f"klines {symbol_pair} status {res.status_code}: {res.text[:120]}")
            return []

        data = res.json()
        if isinstance(data, dict) and data.get("code") == -1003:
            next_allowed = _set_backoff(_BACKOFF_SEC * 2)
            _log_fetch_fail(symbol_pair, "rate_limit", data.get("msg", ""))
            _log_backoff_state(symbol_pair, "rate_limit", _BACKOFF_SEC, next_allowed, time.time())
            logger.warning(f"klines rate limit: {data.get('msg', '')}")
            return []

        if not isinstance(data, list):
            _log_fetch_fail(symbol_pair, "invalid_response", str(data))
            logger.warning(f"klines invalid response: {data}")
            return []

        candles: List[Dict] = []
        for row in data:
            try:
                candles.append({
                    "open_time": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                })
            except Exception:
                continue
        _clear_fetch_fail_state()
        return candles
    except Exception as exc:
        next_allowed = _set_backoff(_BACKOFF_SEC * 2)
        _log_fetch_fail(symbol_pair, "exception", str(exc))
        _log_backoff_state(symbol_pair, "exception", _BACKOFF_SEC, next_allowed, time.time())
        logger.warning(f"klines fetch error {symbol_pair}: {exc}")
        return []

