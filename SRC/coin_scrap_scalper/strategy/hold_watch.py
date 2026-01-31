import datetime, time, threading
from decimal import Decimal
from data.fetch_price import get_current_price
from data.fetch_balance import fetch_active_balances
from config.exchange import QUOTE_ASSET, MIN_ORDER_QUOTE, ALLOC_PCT, MAX_OPEN_POSITIONS, RESERVE_QUOTE
from utils.capital import calc_order_quote
from strategy.watch_trend import get_trend_state, get_relative_position
from trade.order_executor import buy_market, sell_market, get_symbol_filters
from utils.telegram import send_telegram_message
from utils.candle_log import get_hourly_candles
from utils.number import safe_int
from utils.logger import logger
from storage.repo import append_event, upsert_position, save_snapshot, fetch_open_positions, get_latest_snapshot
from utils.ws_price import get_price as get_ws_price

COOLDOWN_AFTER_TRADE = 60
BALANCE_REFRESH_SEC = 120
CANDLE_REFRESH_SEC = 300
REST_PRICE_REFRESH_SEC = 10
ACTIVE_WATCHLIST_REFRESH_SEC = 30
trading_state = {
    "holding": False,
    "buy_price": 0.0,
    "qty": 0.0,
    "high_price": 0.0,
    "low_price": None
}
dynamic_cooldown_until: float = 0.0
last_sent_summary: str = ""
last_summary_time = 0  # ⏱️ 마지막 전송 시간

def send_trend_report(symbol: str, price: float, krw: float, qty: float, trend_30: str, trend_10, pos: float):
    global last_sent_summary, last_summary_time
    now = time.time()
    if now - last_summary_time < 7200:  # 2시간 = 7200초
        return

    summary_key = f"{trend_30}:{trend_10}:{round(pos, 2)}:{round(price, -2)}"
    if summary_key == last_sent_summary:
        return

    last_sent_summary = summary_key
    last_summary_time = now

    try:
        msg = (
            f"\n📡 [코인와치] {symbol}\n"
            f"💸 현재가: {safe_int(price):,} {QUOTE_ASSET}\n"
            f"💰 가용 {QUOTE_ASSET}: {safe_int(krw):,}\n"
            f"📦 보유 {symbol}: {qty:.6f}개\n"
            f"📈 추세: 30={trend_30}, 10={trend_10} / 상대위치: {pos:.1%}"
        )
        send_telegram_message(msg)
    except Exception:
        logger.error("📡 텔레그램 리포트 전송 실패", exc_info=True)

def scalping_loop(symbol: str):
    global dynamic_cooldown_until
    logger.info(f"🚀 {symbol} 스캘핑 시작")

    # 초기화
    balances, krw = fetch_active_balances()
    balances_cache = balances
    krw_cache = krw
    last_balance_ts = time.time()
    last_candle_ts = 0.0
    cached_c1h = []
    last_rest_price_ts = 0.0
    last_rest_price = 0.0
    last_min_order_log_ts = 0.0
    last_active_watch_ts = 0.0
    active_watchlist = None
    last_dust_log_ts = 0.0
    dust_mode = False
    trading_state.update({
        "holding": False,
        "qty": 0.0,
        "buy_price": 0.0,
        "high_price": 0.0,
        "low_price": None
    })
    last_sell_time = 0

    for c in balances:
        if c["symbol"] == symbol:
            total = c["available"] + c["limit"]
            trading_state.update({
                "qty": total,
                "holding": total > 0,
                "buy_price": float(c["average_price"]) if c["average_price"] else 0.0,
                "high_price": float(c["average_price"]) if c["average_price"] else 0.0,
            })
            break

    while True:
        try:
            now = time.time()
            if now < dynamic_cooldown_until:
                time.sleep(10)
                continue

            if now - last_active_watch_ts >= ACTIVE_WATCHLIST_REFRESH_SEC:
                snap = get_latest_snapshot("ACTIVE_WATCHLIST")
                if snap and isinstance(snap.get("data"), list):
                    active_watchlist = set(snap["data"])
                last_active_watch_ts = now

            if active_watchlist is not None and symbol not in active_watchlist and not trading_state["holding"]:
                time.sleep(30)
                continue

            ws_price = get_ws_price(symbol)
            if ws_price is not None:
                price = ws_price
            else:
                if now - last_rest_price_ts >= REST_PRICE_REFRESH_SEC:
                    price_data = get_current_price(QUOTE_ASSET, symbol)
                    last_rest_price = price_data.get("price", 0)
                    last_rest_price_ts = now
                price = last_rest_price
            if price == 0:
                time.sleep(5)
                continue

            if now - last_balance_ts >= BALANCE_REFRESH_SEC:
                balances_cache, krw_cache = fetch_active_balances()
                last_balance_ts = now

            sym = next((x for x in balances_cache if x["symbol"] == symbol), None)
            qty = sym["available"] if sym else 0.0
            holding = qty > 0
            trading_state.update({"holding": holding, "qty": qty})
            if holding and trading_state["buy_price"] == 0.0:
                trading_state.update({"buy_price": price, "high_price": price})

            if holding:
                filters = get_symbol_filters(symbol)
                if filters:
                    min_qty, _, min_notional = filters
                    d_qty = Decimal(str(qty))
                    if d_qty < min_qty:
                        if now - last_dust_log_ts >= 600:
                            logger.warning(f"⚠️ DUST 보유: {symbol} qty={qty} < minQty={min_qty} (매도 불가)")
                            last_dust_log_ts = now
                        upsert_position(
                            symbol=symbol,
                            status="DUST",
                            qty=0.0,
                            avg_price=trading_state.get("buy_price"),
                            exit_ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        )
                        append_event(level="WARNING", type="DUST", symbol=symbol, message="below minQty; ignore position")
                        if active_watchlist is None:
                            snap = get_latest_snapshot("ACTIVE_WATCHLIST")
                            if snap and isinstance(snap.get("data"), list):
                                active_watchlist = set(snap["data"])
                        if active_watchlist and symbol in active_watchlist:
                            active_watchlist.discard(symbol)
                            save_snapshot("ACTIVE_WATCHLIST", sorted(active_watchlist), min_interval_sec=0, force=True)
                        dust_mode = True
                        time.sleep(30)
                        continue
                    if min_notional is not None:
                        d_price = Decimal(str(price))
                        if (d_qty * d_price) < min_notional:
                            if now - last_dust_log_ts >= 600:
                                logger.warning(
                                    f"⚠️ DUST 보유: {symbol} notional={d_qty * d_price:.8f} < minNotional={min_notional} (매도 불가)"
                                )
                                last_dust_log_ts = now
                            upsert_position(
                                symbol=symbol,
                                status="DUST",
                                qty=0.0,
                                avg_price=trading_state.get("buy_price"),
                                exit_ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            )
                            append_event(level="WARNING", type="DUST", symbol=symbol, message="below minNotional; ignore position")
                            if active_watchlist is None:
                                snap = get_latest_snapshot("ACTIVE_WATCHLIST")
                                if snap and isinstance(snap.get("data"), list):
                                    active_watchlist = set(snap["data"])
                            if active_watchlist and symbol in active_watchlist:
                                active_watchlist.discard(symbol)
                                save_snapshot("ACTIVE_WATCHLIST", sorted(active_watchlist), min_interval_sec=0, force=True)
                            dust_mode = True
                            time.sleep(30)
                            continue

            if dust_mode:
                time.sleep(60)
                continue

            open_positions_count = len(fetch_open_positions())
            if not holding and open_positions_count >= MAX_OPEN_POSITIONS:
                logger.info("⚠️ max 포지션 도달: watch-only 모드, 스캔 스킵")
                time.sleep(5)
                continue

            save_snapshot(
                kind=f"STATE:{symbol}",
                data={
                    "symbol": symbol,
                    "holding": trading_state["holding"],
                    "qty": trading_state["qty"],
                    "buy_price": trading_state["buy_price"],
                    "high_price": trading_state["high_price"],
                    "price": price,
                },
                min_interval_sec=60,
            )

            # 🔍 캔들 데이터 (1h만, 주기적 갱신)
            if now - last_candle_ts >= CANDLE_REFRESH_SEC:
                new_c1h = get_hourly_candles(symbol, 12)  # 최근 12시간
                last_candle_ts = now
                if new_c1h:
                    cached_c1h = new_c1h
            c1h = cached_c1h
            if not c1h or len(c1h) < 6:
                time.sleep(5)
                continue

            # 📊 분석
            minute_30_trend = get_trend_state(c1h[-6:])  # 최근 6시간 추세
            minute_10_trend = get_trend_state(c1h[-3:])  # 최근 3시간 추세
            relative_pos = get_relative_position(c1h, price)

            low_candidates = [c['low'] for c in c1h[-6:]]
            high_candidates = [c['high'] for c in c1h[-6:]]
            bottom = min(low_candidates)
            peak = max(high_candidates)

            send_trend_report(symbol, price, krw_cache, qty, minute_30_trend, minute_10_trend, relative_pos)

            if holding:
                buy_price = trading_state["buy_price"]
                profit_ratio = price / buy_price if buy_price else 1.0

                trading_state["high_price"] = max(trading_state["high_price"], price)
                peak_price = trading_state["high_price"]

                # ✅ 익절
                if profit_ratio > 1.05 and price < peak_price * 0.98 and (minute_30_trend == "down" or (minute_30_trend == "side" and minute_10_trend == "down")):
                    res = None
                    for attempt in range(2):
                        res = sell_market(symbol, qty)
                        if res:
                            break
                        if attempt == 0:
                            time.sleep(1)
                    if res:
                        logger.info("✅ 익절: 수익 + 고점 하락 + 추세 하락")
                        trading_state.update({
                            "holding": False,
                            "qty": 0.0,
                            "buy_price": 0.0,
                            "high_price": 0.0,
                            "low_price": None
                        })
                        upsert_position(
                            symbol=symbol,
                            status="CLOSED",
                            qty=0.0,
                            avg_price=buy_price,
                            exit_ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            pnl_pct=(profit_ratio - 1.0) * 100.0,
                        )
                        append_event(level="INFO", type="EXIT_TP", symbol=symbol, message="take profit")
                        dynamic_cooldown_until = now + COOLDOWN_AFTER_TRADE
                        last_sell_time = now
                        last_balance_ts = 0
                        continue
                    logger.warning("❌ 익절 매도 실패: 즉시 재시도 후에도 실패")
                    append_event(level="WARNING", type="EXIT_FAIL", symbol=symbol, message="take profit sell failed")

                # 🛑 손절
                # 수정 코드
                if profit_ratio < 0.97 and (minute_30_trend == "down" or (minute_30_trend == "side" and minute_10_trend == "down")):
                    res = None
                    for attempt in range(2):
                        res = sell_market(symbol, qty)
                        if res:
                            break
                        if attempt == 0:
                            time.sleep(1)
                    if res:
                        logger.info("🛑 손절: 손실 + 추세 하락")
                        trading_state.update({
                            "holding": False,
                            "qty": 0.0,
                            "buy_price": 0.0,
                            "high_price": 0.0,
                            "low_price": None
                        })
                        upsert_position(
                            symbol=symbol,
                            status="CLOSED",
                            qty=0.0,
                            avg_price=buy_price,
                            exit_ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            pnl_pct=(profit_ratio - 1.0) * 100.0,
                        )
                        append_event(level="INFO", type="EXIT_SL", symbol=symbol, message="stop loss")
                        dynamic_cooldown_until = now + COOLDOWN_AFTER_TRADE
                        last_sell_time = now
                        last_balance_ts = 0
                        continue
                    logger.warning("❌ 손절 매도 실패: 즉시 재시도 후에도 실패")
                    append_event(level="WARNING", type="EXIT_FAIL", symbol=symbol, message="stop loss sell failed")

            else:
                #logger.info(f"🔍보유없음 {symbol} 현재가: {price}, 추세: 30={minute_30_trend}, 10={minute_10_trend}, 상대위치: {relative_pos:.1%}")
                #logger.info(f"📉 최근 저점(1h): {bottom}, 고점(1h): {peak}, 현재가: {price}")
                #logger.info(f"price change {price > bottom * 1.005} , {price} , {bottom}, {bottom * 1.005}")
                #logger.info(f"trend : {(minute_30_trend == "up" or (minute_30_trend == "side" and minute_10_trend == "up"))} , {minute_30_trend}, {minute_10_trend}")
                #logger.info(f"보유자금 { krw }, { krw >= MIN_ORDER_KRW }")
                #logger.info(f"최근 매도 { now - last_sell_time > 600 }")
                # 📈 재매수 조건
                if open_positions_count >= MAX_OPEN_POSITIONS:
                    logger.info(f"🚫 신규 진입 제한: open_positions={open_positions_count}, max={MAX_OPEN_POSITIONS}")
                    time.sleep(5)
                    continue

                entry_signal = (
                    price > bottom * 1.005
                    and (minute_30_trend == "up" or (minute_30_trend == "side" and minute_10_trend == "up"))
                    and now - last_sell_time > 600
                )
                if not entry_signal:
                    time.sleep(5)
                    continue

                order_amount = calc_order_quote(krw_cache, ALLOC_PCT, MAX_OPEN_POSITIONS, RESERVE_QUOTE)
                if order_amount < MIN_ORDER_QUOTE:
                    if now - last_min_order_log_ts >= 300:
                        logger.info(
                            f"🚫 주문 금액 부족: order={order_amount:.2f} {QUOTE_ASSET}, "
                            f"min={MIN_ORDER_QUOTE} {QUOTE_ASSET}"
                        )
                        last_min_order_log_ts = now
                    time.sleep(5)
                    continue

                if entry_signal:
                    res = buy_market(symbol, order_amount)
                    if res:
                        logger.info("📥 재매수: 1시간봉 저점 대비 +2% 상승 & 실시간 추세 상승")
                        trading_state.update({
                            "holding": True,
                            "buy_price": price,
                            "high_price": price,
                            "low_price": None
                        })
                        upsert_position(
                            symbol=symbol,
                            status="OPEN",
                            qty=order_amount / price if price else 0.0,
                            avg_price=price,
                            entry_ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        )
                        append_event(level="INFO", type="ENTRY", symbol=symbol, message="buy signal")
                        dynamic_cooldown_until = now + COOLDOWN_AFTER_TRADE
                        last_balance_ts = 0
                        continue
                    logger.warning("❌ 매수 실패: 주문 미체결")
                    append_event(level="WARNING", type="ENTRY_FAIL", symbol=symbol, message="buy failed")

            time.sleep(5)

        except Exception:
            logger.error("⚠️ 스캘핑 루프 오류", exc_info=True)
            time.sleep(5)

def start_scalping_thread(symbol: str):
    t = threading.Thread(target=scalping_loop, args=(symbol,), daemon=True)
    t.start()
