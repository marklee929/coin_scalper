import logging
from datetime import datetime, date

from utils.telegram import send_telegram_summary_if_needed, send_telegram_message
from storage.repo import append_trade, upsert_position, fetch_trades_by_date, append_event, save_snapshot

# ——— 로깅 설정 ———
logger = logging.getLogger("trading")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch_formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-5s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    ch.setFormatter(ch_formatter)
    logger.addHandler(ch)


def log_trade(trade):
    """매수·매도 거래를 SQLite에 저장하고 로그에 기록."""
    try:
        append_trade(
            symbol=trade.get("code") or trade.get("symbol") or "UNKNOWN",
            side=trade.get("action") or trade.get("side") or "UNKNOWN",
            qty=float(trade.get("qty") or trade.get("quantity") or 0),
            price=float(trade.get("price") or 0),
            quote_qty=trade.get("quote_qty"),
            reason=trade.get("reason"),
            raw=trade,
        )
    except Exception as e:
        append_event(level="ERROR", type="DB_ERROR", message=f"log_trade failed: {e}")

    logger.info(f"Trade logged: {trade}")


def append_to_current_positions(code, price, qty):
    """현재 포지션을 SQLite에 업데이트."""
    try:
        upsert_position(
            symbol=code,
            status="OPEN",
            qty=qty,
            avg_price=price,
            entry_ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        logger.debug(f"Position upserted: {code} {qty} @ {price}")
    except Exception as e:
        append_event(level="ERROR", type="DB_ERROR", message=f"append_to_current_positions failed: {e}")


def append_sell_log(code, quantity, buy_price, sell_price, profit_rate):
    """매도 거래를 SQLite에 저장하고 로그에 기록."""
    entry = {
        "code": code,
        "quantity": quantity,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "profit_rate": round(profit_rate * 100, 2),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
        append_trade(
            symbol=code,
            side="SELL",
            qty=quantity,
            price=sell_price,
            reason="EXIT",
            raw=entry,
            ts=entry["timestamp"],
        )
    except Exception as e:
        append_event(level="ERROR", type="DB_ERROR", message=f"append_sell_log failed: {e}")

    logger.info(f"Sell logged: {code} {quantity} @ {sell_price} ({round(profit_rate*100,2)}%)")


def summarize_day_trades(trades=None):
    """오늘 매매 내역을 요약해 텔레그램으로 전송."""
    today = datetime.now().strftime("%Y-%m-%d")
    trades = trades or fetch_trades_by_date(today)
    if not trades:
        logger.warning(f"No trades to summarize for {today}")
        return

    total_profit_value = 0
    total_invested = 0
    max_profit = -9999
    min_profit = 9999
    max_code = ""
    min_code = ""

    for trade in trades:
        profit_rate = trade.get("profit_rate", 0)
        buy_price = trade.get("buy_price", 0)
        quantity = trade.get("quantity", 0)

        invested = buy_price * quantity
        total_invested += invested
        total_profit_value += profit_rate * invested

        if profit_rate > max_profit:
            max_profit = profit_rate
            max_code = trade["code"]
        if profit_rate < min_profit:
            min_profit = profit_rate
            min_code = trade["code"]

    summary = {
        "date": today,
        "total_trades": len(trades),
        "average_profit_weighted": round(total_profit_value / total_invested, 2) if total_invested else 0,
        "max_profit": round(max_profit, 2),
        "max_profit_code": max_code,
        "min_profit": round(min_profit, 2),
        "min_profit_code": min_code,
        "total_profit_sum": round(total_profit_value / 100, 0)
    }
    save_snapshot(kind="SUMMARY", data=summary, force=True)
    logger.info("Day summary saved to SQLite")
    send_telegram_summary_if_needed(summary)


def save_daily_summary():
    today = datetime.now().strftime("%Y-%m-%d")
    logs = fetch_trades_by_date(today)
    if not logs:
        logger.error("저장 실패: 거래 로그가 없습니다.")
        return

    send_telegram_message(
        f"📦 자동매매 종료\n📝 {date.today()} 거래 요약 ({len(logs)}건)"
    )

