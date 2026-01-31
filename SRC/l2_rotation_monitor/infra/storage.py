import json
from pathlib import Path
from typing import Dict

from config.settings import STORAGE_DIR
from infra.logger import logger

SIGNALS_PATH = Path(STORAGE_DIR) / "signals.jsonl"


def append_signal(payload: Dict) -> None:
    try:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        with open(SIGNALS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error(f"signals.jsonl append failed: {exc}")

