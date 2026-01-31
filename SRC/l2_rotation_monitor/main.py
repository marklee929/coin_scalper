import time
from typing import Dict

from config.settings import (
    BTC_GATE_ABS_RET_15,
    BTC_PAIR,
    CANDLE_LIMIT,
    COOLDOWN_MINUTES,
    LAG_FLOOR_RET_60,
    LAG_GAP,
    LAG_VOL_FLOOR,
    LEADER_GAP,
    LEADER_MIN_RET_60,
    MAX_ALERTS_PER_DAY,
    POLL_INTERVAL_SEC,
    QUOTE_ASSET,
    TIMEFRAME,
    VOL_DROP_RATIO,
    WATCHLIST,
    WATCHLIST_PAIRS,
)
from core.gates import btc_gate
from core.scoring import compute_metrics
from core.signal_engine import make_signal_key, select_lags, select_leader
from exchange.binance import fetch_klines
from infra.logger import logger, setup_logging
from infra.notifier import send_telegram_message
from infra.rate_limiter import RateLimiter
from infra.storage import append_signal


def build_symbol_pairs() -> Dict[str, str]:
    if len(WATCHLIST_PAIRS) == len(WATCHLIST):
        return {symbol: pair for symbol, pair in zip(WATCHLIST, WATCHLIST_PAIRS)}

    mapping: Dict[str, str] = {}
    for pair in WATCHLIST_PAIRS:
        if pair.endswith(QUOTE_ASSET):
            symbol = pair[: -len(QUOTE_ASSET)]
        else:
            symbol = pair
        mapping[symbol] = pair
    return mapping


def should_skip_by_volume(metrics: Dict) -> bool:
    median_value = metrics.get("vol_60_median")
    if median_value is None:
        return False
    return metrics.get("vol_60", 0.0) < median_value * VOL_DROP_RATIO


def format_signal_text(leader: str, lags: list, btc_ret_15: float | None, metrics: Dict) -> str:
    leader_score = metrics.get(leader, {}).get("score")
    btc_part = f"{btc_ret_15:+.2%}" if btc_ret_15 is not None else "n/a"
    score_part = f"{leader_score:.4f}" if leader_score is not None else "n/a"
    return (
        f"[L2 Rotation] leader={leader} lags={','.join(lags)} "
        f"btc_ret_15={btc_part} score={score_part}"
    )


def run_cycle(btc_candles: list, symbol_pairs: Dict[str, str], limiter: RateLimiter) -> None:
    gate_ok, btc_ret_15 = btc_gate(btc_candles, BTC_GATE_ABS_RET_15)
    if not gate_ok:
        logger.info(f"BTC gate active: btc_ret_15={btc_ret_15}")
        return

    metrics_by_symbol: Dict[str, Dict] = {}
    for symbol, pair in symbol_pairs.items():
        candles = fetch_klines(pair, TIMEFRAME, CANDLE_LIMIT)
        if not candles:
            logger.warning(f"{symbol} candles empty")
            continue
        metrics = compute_metrics(candles)
        if not metrics:
            logger.warning(f"{symbol} metrics unavailable")
            continue
        if should_skip_by_volume(metrics):
            logger.info(f"{symbol} skipped by volume dead zone")
            continue
        metrics_by_symbol[symbol] = metrics

    if len(metrics_by_symbol) < 2:
        logger.info("not enough metrics to rank leader")
        return

    leader, leader_reason = select_leader(metrics_by_symbol, LEADER_GAP, LEADER_MIN_RET_60)
    if not leader:
        logger.info(f"leader selection skipped: {leader_reason}")
        return

    lags, lag_reason = select_lags(
        metrics_by_symbol,
        leader,
        lag_gap=LAG_GAP,
        lag_floor_ret_60=LAG_FLOOR_RET_60,
        lag_vol_floor=LAG_VOL_FLOOR,
    )
    if not lags:
        logger.info(f"lag selection skipped: {lag_reason}")
        return

    key = make_signal_key(leader, lags)
    allowed, rate_reason = limiter.allow(key)
    if not allowed:
        logger.info(f"rate limit blocked: {rate_reason}")
        return

    payload = {
        "ts": int(time.time()),
        "leader": leader,
        "lags": lags,
        "metrics": metrics_by_symbol,
        "btc_ret_15": btc_ret_15,
        "reason": {
            "leader": leader_reason,
            "lags": lag_reason,
            "rate": rate_reason,
        },
    }
    append_signal(payload)

    text = format_signal_text(leader, lags, btc_ret_15, metrics_by_symbol)
    if send_telegram_message(text):
        logger.info("telegram sent")
    logger.info(f"signal saved: {text}")


def main() -> None:
    setup_logging()
    symbol_pairs = build_symbol_pairs()
    limiter = RateLimiter(MAX_ALERTS_PER_DAY, COOLDOWN_MINUTES)

    last_candle_ts = None
    while True:
        btc_candles = fetch_klines(BTC_PAIR, TIMEFRAME, CANDLE_LIMIT)
        if not btc_candles:
            time.sleep(POLL_INTERVAL_SEC)
            continue

        candle_ts = btc_candles[-1]["open_time"]
        if candle_ts == last_candle_ts:
            time.sleep(POLL_INTERVAL_SEC)
            continue

        last_candle_ts = candle_ts
        run_cycle(btc_candles, symbol_pairs, limiter)
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()

