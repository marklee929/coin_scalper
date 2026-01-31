import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Tuple

from config.settings import STORAGE_DIR
from infra.logger import logger

STATE_PATH = Path(STORAGE_DIR) / "rate_state.json"


def _today_date(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


@dataclass
class RateLimiter:
    max_per_day: int
    cooldown_minutes: int
    state_path: Path = STATE_PATH
    state: Dict = field(default_factory=dict)

    def load(self) -> None:
        if self.state:
            return
        if not self.state_path.exists():
            self.state = {
                "date": _today_date(time.time()),
                "count": 0,
                "cooldowns": {},
            }
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                self.state = json.load(f)
        except Exception as exc:
            logger.warning(f"rate_state.json load failed: {exc}")
            self.state = {
                "date": _today_date(time.time()),
                "count": 0,
                "cooldowns": {},
            }

    def save(self) -> None:
        try:
            STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False)
        except Exception as exc:
            logger.warning(f"rate_state.json save failed: {exc}")

    def _rollover(self, now_ts: float) -> None:
        today = _today_date(now_ts)
        if self.state.get("date") != today:
            self.state = {"date": today, "count": 0, "cooldowns": {}}

    def allow(self, key: str, now_ts: float | None = None) -> Tuple[bool, str]:
        self.load()
        now_ts = now_ts or time.time()
        self._rollover(now_ts)

        if self.state.get("count", 0) >= self.max_per_day:
            return False, "daily_cap_reached"

        cooldowns = self.state.setdefault("cooldowns", {})
        last_ts = cooldowns.get(key)
        if last_ts and now_ts - last_ts < self.cooldown_minutes * 60:
            return False, "cooldown_active"

        cooldowns[key] = now_ts
        self.state["count"] = int(self.state.get("count", 0)) + 1
        self.save()
        return True, "rate_limit_ok"

