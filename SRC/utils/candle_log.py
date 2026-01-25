import datetime
import os
import json
from data.fetch_price import get_candle_data_v2

# 캐시 파일 생성/로드 범용 함수

def _get_timestamp_label(tf: str) -> str:
    now = datetime.datetime.now()
    if tf == "1d":
        return now.strftime("%Y_%m_%d")
    if tf == "1h":
        return now.strftime("%Y_%m_%d_%H")
    if tf in ("15m", "30m", "5m", "1m"):
        # 분을 tf 간격으로 내림
        interval = int(tf[:-1])
        minute = (now.minute // interval) * interval
        label_time = now.replace(minute=minute, second=0, microsecond=0)
        return label_time.strftime("%Y_%m_%d_%H%M")
    raise ValueError(f"Unsupported timeframe: {tf}")


def load_candle_cache(symbol: str, tf: str):
    label = _get_timestamp_label(tf)
    path = f"logs/{tf}_candle_{symbol}_{label}.json"
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None


def save_candle_cache(symbol: str, tf: str, candles: list):
    label = _get_timestamp_label(tf)
    path = f"logs/{tf}_candle_{symbol}_{label}.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(candles, f, indent=2, ensure_ascii=False)


def get_candles(symbol: str, tf: str, size: int):
    """
    지정된 tf(timeframe) 캐시가 있으면 로드, 없으면 API 호출 후 저장하여 반환
    tf: '1d', '1h', '15m', '30m'
    size: 조회할 캔들 수
    """
    cached = load_candle_cache(symbol, tf)
    if cached is not None:
        return cached
    # API interval 파라미터
    interval = tf
    candles = get_candle_data_v2(symbol, interval=interval, size=size)
    
    if candles:
        save_candle_cache(symbol, tf, candles)
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