import datetime
from utils.logger import logger

def get_trend_state(candles: list) -> str:
    if not candles or len(candles) < 3:
        logger.warning("❌ 추세 판별용 캔들 부족: len(candles) < 3")
        return "side"

    score = 0
    for i in range(1, len(candles)):
        prev = candles[i-1]["close"]
        curr = candles[i]["close"]
        if curr > prev:
            score += 1
        elif curr < prev:
            score -= 1
    logger.debug(f"📊 캔들 변화 score = {score} / close 흐름 = {[c['close'] for c in candles]}")

    if score >= 2 and is_trend_rising(candles):
        logger.info("📈 상승 추세 감지됨")
        return "up"
    if score <= -2 and is_trend_falling(candles):
        logger.info("📉 하락 추세 감지됨")
        return "down"
    logger.debug("➖ 추세 애매함 → side 처리")
    return "side"


def is_trend_rising(candles: list, depth: int = 4) -> bool:
    if not candles or len(candles) < depth:
        logger.warning("❌ 상승 추세 판단용 캔들 부족")
        return False

    closes = [c["close"] for c in candles[-depth:]]
    result = all(x < y for x, y in zip(closes, closes[1:]))
    logger.debug(f"⬆️ 상승 판단: {closes} → {result}")
    return result


def is_trend_falling(candles: list, depth: int = 4) -> bool:
    if not candles or len(candles) < depth:
        logger.warning("❌ 하락 추세 판단용 캔들 부족")
        return False

    closes = [c["close"] for c in candles[-depth:]]
    result = all(x > y for x, y in zip(closes, closes[1:]))
    logger.debug(f"⬇️ 하락 판단: {closes} → {result}")
    return result


def get_relative_position(candles, current_price):
    if not candles or len(candles) < 2:
        logger.debug("ℹ️ 상대위치 판단용 캔들 부족 → 0.5 반환")
        return 0.5

    lows = [c["low"] for c in candles]
    highs = [c["high"] for c in candles]
    lowest = min(lows)
    highest = max(highs)

    if highest == lowest:
        logger.debug("⚠️ 고저 동일 → 상대위치 0.5 고정")
        return 0.5

    position = (current_price - lowest) / (highest - lowest)
    logger.debug(f"📍 현재가 위치: {current_price} / range=({lowest}~{highest}) → pos={round(position, 3)}")
    return position
