from typing import List, Dict, Optional
import requests
from datetime import datetime, timezone

from config.exchange import BINANCE_BASE_URL, QUOTE_ASSET, CANDLE_LIMITS
from data.fetch_price import get_all_tickers_24hr, get_candle_data_v2
from utils.logger import logger
from utils.universe_cache import load_or_refresh_universe

EXCLUDED_BASE_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S")


def _is_excluded_symbol(base_asset: str) -> bool:
    base = base_asset.upper()
    return any(base.endswith(suffix) for suffix in EXCLUDED_BASE_SUFFIXES)


def get_spot_symbols(quote_asset: str = QUOTE_ASSET) -> List[Dict]:
    symbols = []
    for s in load_or_refresh_universe(quote_asset=quote_asset):
        base = s.get("baseAsset", "")
        if not base or _is_excluded_symbol(base):
            continue

        symbols.append({
            "symbol": s.get("symbol"),
            "baseAsset": base,
            "quoteAsset": quote_asset
        })
    return symbols


def _get_first_kline_time_ms(symbol_pair: str, interval: str = "1h") -> Optional[int]:
    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {
        "symbol": symbol_pair,
        "interval": interval,
        "limit": 1,
        "startTime": 0
    }
    try:
        res = requests.get(url, params=params)
        data = res.json()
        if isinstance(data, list) and data:
            return int(data[0][0])
    except Exception as e:
        logger.warning(f"최초 캔들 조회 실패({symbol_pair}): {e}")
    return None


def is_recent_listing(symbol_pair: str, max_days: int = 2) -> bool:
    first_ts = _get_first_kline_time_ms(symbol_pair)
    if first_ts is None:
        return False
    first_dt = datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc)
    age_days = (datetime.now(tz=timezone.utc) - first_dt).days
    return age_days <= max_days


def is_deep_drawdown_without_rebound(base_symbol: str,
                                     quote_asset: str = QUOTE_ASSET,
                                     min_drawdown_pct: float = 70.0,
                                     max_drawdown_pct: float = 90.0,
                                     rebound_ratio: float = 1.2,
                                     days: int = None) -> bool:
    if days is None:
        days = CANDLE_LIMITS.get("1d", 120)
    candles = get_candle_data_v2(base_symbol, quote_asset, interval="1d", size=days)
    if len(candles) < 10:
        return False

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]

    peak = max(highs)
    if peak <= 0:
        return False

    current = closes[-1]
    drawdown_pct = (1 - (current / peak)) * 100
    if not (min_drawdown_pct <= drawdown_pct <= max_drawdown_pct):
        return False

    low = min(lows)
    has_rebound = any(c["close"] >= low * rebound_ratio for c in candles)
    return not has_rebound


def stage1_scan(quote_asset: str = QUOTE_ASSET,
                change_low: float = -20.0,
                change_high: float = -5.0,
                min_quote_volume: float = 10000.0,
                min_trade_count: int = 10,
                max_new_listing_days: int = 2,
                exclude_symbols: Optional[set] = None) -> List[Dict]:
    """
    코인 1차 필터 스캔.
    - 24h Change %: -5% ~ -20% 범위
    - 거래량/체결수 최소치
    - 신규 상장 1~2일 제외
    - 1h 캔들 1~2개 수준 제외
    - 장기 폭락(-70~-90%) + 반등 없음 제외
    """
    symbols = get_spot_symbols(quote_asset)
    tickers = get_all_tickers_24hr()
    ticker_map = {t.get("symbol"): t for t in tickers if isinstance(t, dict)}

    results = []
    exclude = {s.upper() for s in (exclude_symbols or set())}
    for info in sorted(symbols, key=lambda x: x["symbol"]):
        symbol_pair = info["symbol"]
        base_symbol = info["baseAsset"]
        if symbol_pair.upper() in exclude or base_symbol.upper() in exclude:
            continue
        ticker = ticker_map.get(symbol_pair)
        if not ticker:
            continue

        change_pct = float(ticker.get("priceChangePercent", 0))
        if not (change_low <= change_pct <= change_high):
            continue
        if change_pct <= -40:
            continue

        quote_volume = float(ticker.get("quoteVolume", 0))
        trade_count = int(ticker.get("count", 0))
        if quote_volume < min_quote_volume or trade_count < min_trade_count:
            continue

        if is_recent_listing(symbol_pair, max_days=max_new_listing_days):
            continue

        candles_1h = get_candle_data_v2(
            base_symbol,
            quote_asset,
            interval="1h",
            size=CANDLE_LIMITS.get("1h", 1000)
        )
        if len(candles_1h) < 3:
            continue

        if is_deep_drawdown_without_rebound(base_symbol, quote_asset):
            continue

        results.append({
            "symbol": base_symbol,
            "symbol_pair": symbol_pair,
            "change_pct": change_pct,
            "quote_volume": quote_volume,
            "trade_count": trade_count
        })

    logger.info(f"✅ 1차 필터 통과 코인 수: {len(results)}")
    return results


if __name__ == "__main__":
    logger.info("🔎 Binance 1차 필터 스캔 시작")
    candidates = stage1_scan()
    for c in candidates:
        logger.info(
            f"{c['symbol_pair']} | change={c['change_pct']:+.2f}% | "
            f"vol={c['quote_volume']:.2f} {QUOTE_ASSET} | trades={c['trade_count']}"
        )
