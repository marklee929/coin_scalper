import json
import os
import logging
from datetime import datetime, date
from pathlib import Path

import pandas as pd

from utils.telegram import send_telegram_summary_if_needed, send_telegram_message

# ——— 로깅 설정 ———
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("trading")
logger.setLevel(logging.DEBUG)

# 콘솔 핸들러 (INFO 이상)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch_formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)-5s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
ch.setFormatter(ch_formatter)
logger.addHandler(ch)

# 파일 핸들러 (DEBUG 이상)
fh = logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8")
fh.setLevel(logging.DEBUG)
fh.setFormatter(ch_formatter)
logger.addHandler(fh)


def log_trade(trade):
    """매수·매도 거래를 JSON 파일에 저장하고 로그에 기록."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"trades_{date_str}.json"
    if log_file.exists():
        with open(log_file, "r", encoding="utf-8") as f:
            logs = json.load(f)
    else:
        logs = []

    logs.append(trade)
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)

    logger.info(f"Trade logged: {trade['code']} {trade['action']} {trade['qty']} @ {trade['price']}")


def append_to_current_positions(code, price, qty):
    """현재 포지션 파일에 보유 종목을 업데이트."""
    path = LOG_DIR / "current_positions.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = []

    exists = next((x for x in data if x["code"] == code), None)
    if exists:
        exists["quantity"] += qty
        logger.debug(f"Position updated: {code} += {qty} (total {exists['quantity']})")
    else:
        data.append({"code": code, "buy_price": price, "quantity": qty})
        logger.debug(f"Position added: {code} {qty} @ {price}")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_sell_log(code, quantity, buy_price, sell_price, profit_rate):
    """매도 거래를 JSON 파일에 저장하고 로그에 기록."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"trades_{date_str}.json"
    if log_file.exists():
        with open(log_file, "r", encoding="utf-8") as f:
            logs = json.load(f)
    else:
        logs = []

    entry = {
        "code": code,
        "quantity": quantity,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "profit_rate": round(profit_rate * 100, 2),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    logs.append(entry)
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)

    logger.info(f"Sell logged: {code} {quantity} @ {sell_price} ({round(profit_rate*100,2)}%)")


def summarize_day_trades(trades=None):
    """오늘 매매 내역을 요약해 파일에 저장하고 텔레그램으로 전송."""
    today = datetime.now().strftime("%Y-%m-%d")
    trade_log_path = LOG_DIR / f"trades_{today}.json"
    summary_path = LOG_DIR / f"summary_{today}.json"

    if not trade_log_path.exists():
        logger.warning(f"No trades to summarize for {today}")
        return

    with open(trade_log_path, encoding="utf-8") as f:
        trades = json.load(f)

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

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info(f"Day summary saved → {summary_path}")
    send_telegram_summary_if_needed(summary)


def save_daily_summary():
    today = datetime.now().strftime("%Y-%m-%d")
    log_path = Path(f"logs/trades_{today}.json")
    output_path = Path(f"data/summary_{today}.xlsx")
    Path("data").mkdir(exist_ok=True)

    if not log_path.exists():
        logger.error("저장 실패: 거래 로그 파일이 없습니다.")
        return

    with open(log_path, encoding="utf-8") as f:
        logs = json.load(f)

    df = pd.DataFrame(logs)
    try:
        df.to_excel(output_path, index=False)
        logger.info(f"✅ 엑셀 저장 완료: {output_path}")
    except Exception as e:
        logger.error(f"엑셀 저장 실패: {e}")

    # 🔐 텔레그램으로 거래 기록 전송
    text_blocks = []
    current_block = ""
    for entry in logs:
        line = json.dumps(entry, ensure_ascii=False)
        if len(current_block) + len(line) + 1 > 4000:
            text_blocks.append(current_block)
            current_block = ""
        current_block += line + "\n"
    if current_block:
        text_blocks.append(current_block)

    send_telegram_message(
        f"📦 자동매매 종료\n📝 {date.today()} 거래 요약 ({len(logs)}건)"
    )

    for idx, block in enumerate(text_blocks, start=1):
        send_telegram_message(f"[{idx}/{len(text_blocks)}]\n{block.strip()}")

