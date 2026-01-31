import time
from typing import Dict, List

import requests

from config.settings import BINANCE_BASE_URL
from infra.logger import logger

_NEXT_ALLOWED_TS = 0.0
_BACKOFF_SEC = 5


def _set_backoff(seconds: int) -> None:
    global _NEXT_ALLOWED_TS, _BACKOFF_SEC
    _BACKOFF_SEC = min(max(seconds, 5), 300)
    _NEXT_ALLOWED_TS = time.time() + _BACKOFF_SEC


def fetch_klines(symbol_pair: str, interval: str, limit: int) -> List[Dict]:
    global _NEXT_ALLOWED_TS
    if time.time() < _NEXT_ALLOWED_TS:
        return []

    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {"symbol": symbol_pair, "interval": interval, "limit": limit}

    try:
        res = requests.get(url, params=params, timeout=10)
        if res.status_code != 200:
            _set_backoff(_BACKOFF_SEC * 2)
            logger.warning(f"klines {symbol_pair} status {res.status_code}: {res.text[:120]}")
            return []

        data = res.json()
        if isinstance(data, dict) and data.get("code") == -1003:
            _set_backoff(_BACKOFF_SEC * 2)
            logger.warning(f"klines rate limit: {data.get('msg', '')}")
            return []

        if not isinstance(data, list):
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
        return candles
    except Exception as exc:
        _set_backoff(_BACKOFF_SEC * 2)
        logger.warning(f"klines fetch error {symbol_pair}: {exc}")
        return []

