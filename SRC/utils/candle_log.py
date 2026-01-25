import time
from data.fetch_price import get_candle_data_v2

# in-memory cache to avoid JSON file explosion
_CANDLE_CACHE = {}
_CACHE_TTL_SEC = {
    "1m": 30,
    "5m": 60,
    "15m": 120,
    "30m": 180,
    "1h": 600,
    "4h": 1200,
    "1d": 3600,
}


def _cache_key(symbol: str, tf: str, size: int) -> str:
    return f"{symbol.upper()}:{tf}:{size}"


def get_candles(symbol: str, tf: str, size: int):
    """
    지정된 tf(timeframe) 캐시가 있으면 로드, 없으면 API 호출 후 메모리 캐시에 저장하여 반환
    tf: '1d', '1h', '15m', '30m', '5m', '1m'
    size: 조회할 캔들 수
    """
    key = _cache_key(symbol, tf, size)
    ttl = _CACHE_TTL_SEC.get(tf, 60)
    now = time.time()
    cached = _CANDLE_CACHE.get(key)
    if cached and (now - cached["ts"]) < ttl:
        return cached["data"]

    candles = get_candle_data_v2(symbol, interval=tf, size=size)
    if candles:
        _CANDLE_CACHE[key] = {"ts": now, "data": candles}
    return candles

# 편의 함수

def get_daily_candles(symbol: str, size: int = 5):
    return get_candles(symbol, "1d", size)

def get_hourly_candles(symbol: str, size: int = 5):
    return get_candles(symbol, "1h", size)

def get_1m_candles(symbol: str, size: int = 20):
    return get_candles(symbol, "1m", size)

def get_5m_candles(symbol: str, size: int = 6):
    return get_candles(symbol, "5m", size)

def get_15m_candles(symbol: str, size: int = 5):
    return get_candles(symbol, "15m", size)

def get_30m_candles(symbol: str, size: int = 5):
    return get_candles(symbol, "30m", size)
