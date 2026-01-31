import os
from typing import Optional

import requests

from infra.logger import logger


def send_telegram_message(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            logger.warning(f"telegram send failed: {res.status_code} {res.text[:120]}")
            return False
        return True
    except Exception as exc:
        logger.warning(f"telegram send error: {exc}")
        return False

