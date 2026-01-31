import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class FetchFailState:
    first_fail_ts: float = 0.0
    last_fail_ts: float = 0.0
    fail_count: int = 0
    last_error: str = ""
    last_reason: str = ""
    last_event_ts: float = 0.0
    in_fail_mode: bool = False


@dataclass
class FetchTracker:
    # 고정 상수 (env로 빼지 않음)
    FAIL_EMIT_AFTER_SEC: int = 600
    EVENT_MIN_INTERVAL_SEC: int = 600
    states: Dict[str, FetchFailState] = field(default_factory=dict)

    def _get(self, key: str) -> FetchFailState:
        if key not in self.states:
            self.states[key] = FetchFailState()
        return self.states[key]

    def on_success(
        self,
        key: str,
        symbol_pair: str | None = None,
        now_ts: Optional[float] = None,
    ) -> Tuple[bool, Optional[Dict]]:
        now = now_ts or time.time()
        st = self._get(key)
        if st.fail_count == 0 and not st.in_fail_mode:
            return False, None

        if st.in_fail_mode:
            duration = int(now - st.first_fail_ts) if st.first_fail_ts else 0
            payload = {
                "type": "fetch_recovered",
                "ts": int(now),
                "key": key,
                "symbol_pair": symbol_pair,
                "fail_count": st.fail_count,
                "fail_duration_sec": duration,
                "last_error": st.last_error,
                "last_reason": st.last_reason,
            }
            self.states[key] = FetchFailState()
            return True, payload

        self.states[key] = FetchFailState()
        return False, None

    def on_fail(
        self,
        key: str,
        symbol_pair: str | None = None,
        reason: str = "",
        now_ts: Optional[float] = None,
    ) -> Tuple[bool, Optional[Dict]]:
        now = now_ts or time.time()
        st = self._get(key)
        st.fail_count += 1
        st.last_fail_ts = now
        if reason:
            st.last_error = reason[:200]
            st.last_reason = reason[:120]
        if st.first_fail_ts == 0.0:
            st.first_fail_ts = now

        duration = now - st.first_fail_ts
        if duration < self.FAIL_EMIT_AFTER_SEC:
            return False, None

        should_emit = False
        if not st.in_fail_mode:
            should_emit = True
        elif st.last_reason != reason:
            should_emit = True
        elif now - st.last_event_ts >= self.EVENT_MIN_INTERVAL_SEC:
            should_emit = True

        if not should_emit:
            return False, None

        st.in_fail_mode = True
        st.last_event_ts = now
        payload = {
            "type": "fetch_fail",
            "ts": int(now),
            "key": key,
            "symbol_pair": symbol_pair,
            "fail_count": st.fail_count,
            "fail_duration_sec": int(duration),
            "last_error": st.last_error,
            "last_reason": st.last_reason,
        }
        return True, payload
