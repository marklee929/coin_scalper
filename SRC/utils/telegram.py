import requests
import json
import os
from datetime import datetime, timedelta
from utils.safe_request import safe_request
from config.exchange import QUOTE_ASSET

with open(os.path.join(os.path.dirname(__file__), '..', 'config', 'secrets.json'), encoding="utf-8") as f:
    secrets = json.load(f)

BOT_TOKEN = secrets.get("TELEGRAM_TOKEN")
CHAT_ID   = secrets.get("TELEGRAM_CHAT_ID")

LAST_SUMMARY_FILE = os.path.join(os.path.dirname(__file__), '..', 'logs', 'last_summary_timestamp.txt')


def send_telegram_message(msg: str):
    """
    Telegram 메시지 전송 (단일 메시지)
    """
    from utils.logger import logger

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    }
    try:
        res = safe_request(requests.post, url, json=payload)

        if isinstance(res, dict):
            if not res.get("ok", False):
                logger.error("⛔ Telegram 전송 실패: ok=False")
        else:
            if hasattr(res, 'status_code') and (res.status_code != 200 or not getattr(res, 'ok', False)):
                logger.error(f"⛔ Telegram 전송 실패: {res.text}")
    except Exception as e:
        logger.error(f"⛔ Telegram 예외 발생: {e}")


def send_telegram_summary_if_needed(summary: dict):
    from utils.logger import logger

    now = datetime.now()

    # 마지막 전송 시간 읽기
    last_ts = None
    try:
        with open(LAST_SUMMARY_FILE, 'r') as f:
            last_str = f.read().strip()
            last_ts = datetime.fromisoformat(last_str)
    except Exception:
        pass

    # 마지막 전송으로부터 1시간 이내면 건너뜀
    if last_ts and (now - last_ts) < timedelta(hours=1):
        logger.info("⏱️ 마지막 전송으로부터 1시간 미만, 건너뜀")
        return

    message = format_summary_for_telegram(summary)
    send_telegram_message(message)
    logger.info("📬 텔레그램 요약 전송 완료")

    os.makedirs(os.path.dirname(LAST_SUMMARY_FILE), exist_ok=True)
    with open(LAST_SUMMARY_FILE, 'w') as f:
        f.write(now.isoformat())


def format_summary_for_telegram(summary: dict) -> str:
    return (
        f"📊 *{summary['date']} 일일 요약 리포트*\n"
        f"총 거래: {summary['total_trades']}건\n"
        f"평균 수익률(가중): {summary.get('average_profit_weighted', 0)}%\n"
        f"총 수익률 합: {summary['total_profit_sum']}%\n\n"
        f"🏆 최고 수익: {summary['max_profit']}% ({summary['max_profit_code']})\n"
        f"💣 최저 수익: {summary['min_profit']}% ({summary['min_profit_code']})"
    )


def notify_trade_action(action: str, symbol: str, price: float, reason: str = ""):
    """
    매수/매도 시점에 요약 메시지를 전송합니다.
    action: "BUY" or "SELL"
    reason: 조건 요약
    """
    emoji = "📥" if action.upper() == "BUY" else "📤"
    msg = (
        f"{emoji} *[{symbol}]* {action.upper()} 실행됨\n"
        f"💰 가격: {int(price):,} {QUOTE_ASSET}\n"
        f"📌 사유: {reason}"
    )
    send_telegram_message(msg)
