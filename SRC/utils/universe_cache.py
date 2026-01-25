from datetime import datetime
from typing import List, Dict

import requests

from config.exchange import BINANCE_BASE_URL, QUOTE_ASSET
from utils.logger import logger
from storage.repo import get_latest_snapshot, save_snapshot, append_event


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_or_refresh_universe(quote_asset: str = QUOTE_ASSET) -> List[Dict]:
    """
    Spot 심볼 목록을 하루 1회 갱신해 캐시로 사용한다.
    - 오늘 스냅샷 있으면 그대로 사용
    - 없으면 API로 갱신 후 저장
    - API 실패 시 가장 최근 스냅샷 fallback
    """
    today = _today_str()

    # 1) 오늘 스냅샷 있으면 사용
    latest = get_latest_snapshot("UNIVERSE")
    if latest:
        data = latest.get("data", {})
        if data.get("date") == today and data.get("quoteAsset") == quote_asset:
            return data.get("symbols", [])

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
        save_snapshot("UNIVERSE", payload, force=True)

        logger.info(f"✅ universe 갱신 완료 ({len(symbols)} symbols)")
        return symbols

    except Exception as e:
        logger.warning(f"⚠️ universe 갱신 실패: {e}")
        append_event(level="WARN", type="API_ERROR", message=f"universe refresh failed: {e}")

    # 3) 실패 시 가장 최신 스냅샷 fallback
    if latest:
        logger.warning("↩️ universe fallback 사용: latest snapshot")
        return latest.get("data", {}).get("symbols", [])

    raise RuntimeError("universe refresh failed and no snapshot exists")
