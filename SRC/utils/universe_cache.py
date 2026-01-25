import json
import os
from datetime import datetime
from glob import glob
from typing import List, Dict

import requests

from config.exchange import BINANCE_BASE_URL, QUOTE_ASSET
from utils.logger import logger


def _default_base_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "..", "storage")


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _universe_path(base_dir: str, date_str: str) -> str:
    return os.path.join(base_dir, f"universe_{date_str}.json")


def _read_universe(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_or_refresh_universe(quote_asset: str = QUOTE_ASSET, base_dir: str = None) -> List[Dict]:
    """
    Spot 심볼 목록을 하루 1회 갱신해 캐시로 사용한다.
    - 오늘 파일 있으면 그대로 사용
    - 없으면 API로 갱신 후 저장
    - API 실패 시 가장 최근 파일 fallback
    """
    if base_dir is None:
        base_dir = _default_base_dir()
    os.makedirs(base_dir, exist_ok=True)

    today = _today_str()
    today_path = _universe_path(base_dir, today)

    # 1) 오늘 캐시 있으면 사용
    if os.path.exists(today_path):
        payload = _read_universe(today_path)
        return payload.get("symbols", [])

    # 2) 없으면 갱신 시도
    try:
        res = requests.get(f"{BINANCE_BASE_URL}/api/v3/exchangeInfo", timeout=5)
        data = res.json()
        symbols = []
        for s in data.get("symbols", []):
            if s.get("status") != "TRADING":
                continue
            if s.get("quoteAsset") != quote_asset:
                continue
            perms = s.get("permissions", [])
            if perms and "SPOT" not in perms:
                continue
            symbols.append({
                "symbol": s.get("symbol"),
                "baseAsset": s.get("baseAsset"),
                "quoteAsset": s.get("quoteAsset"),
                "status": s.get("status"),
                "permissions": perms
            })

        payload = {
            "date": today,
            "source": "binance_exchange_info",
            "quoteAsset": quote_asset,
            "symbols": symbols,
            "count": len(symbols)
        }
        with open(today_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2)

        logger.info(f"✅ universe 갱신 완료: {today_path} ({len(symbols)} symbols)")
        return symbols

    except Exception as e:
        logger.warning(f"⚠️ universe 갱신 실패: {e}")

    # 3) 실패 시 가장 최신 파일 fallback
    files = sorted(glob(os.path.join(base_dir, "universe_*.json")))
    if not files:
        raise RuntimeError("universe refresh failed and no cache exists")

    latest = files[-1]
    logger.warning(f"↩️ universe fallback 사용: {latest}")
    payload = _read_universe(latest)
    return payload.get("symbols", [])
