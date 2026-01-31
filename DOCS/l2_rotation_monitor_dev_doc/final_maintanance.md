오케이. 그 우선순위(1~3) 그대로 **“수정 패치 형태(unified diff)”**로 뽑아줄게.
지금 레포 구조 기준으로 **최소 침습**(기존 함수 시그니처 거의 안 건드림)으로 가는 안이야.

아래 패치는 3덩어리로 나뉨:

1. **fetch_fail 누적/복구 이벤트(D)**
2. **gate_stats atomic write + rate_limit_blocked 카운터(E)**
3. **main 루프 try/except(무인 안전성)**

---

## PATCH 1) fetch_fail 누적/복구 이벤트 추가 (D)

### ✅ 핵심

* `fetch_klines()`가 `[]` 반환하는 경우(백오프 포함) → **실패 누적**
* 실패가 **10분 이상 지속**되면 `type=fetch_fail` 1회 기록(스팸 방지)
* 이후 정상 fetch 되면 `type=fetch_recovered` 1회 기록
* heartbeat가 이미 있다면, 거기에 `last_success_*` 업데이트도 같이 가능

> 파일 추가: `SRC/l2_rotation_monitor/infra/fetch_tracker.py`
> 저장: `events.jsonl` (없으면 PATCH 2에서 추가)

```diff
diff --git a/SRC/l2_rotation_monitor/infra/fetch_tracker.py b/SRC/l2_rotation_monitor/infra/fetch_tracker.py
new file mode 100644
index 0000000..b3a6d2f
--- /dev/null
+++ b/SRC/l2_rotation_monitor/infra/fetch_tracker.py
@@ -0,0 +1,131 @@
+import time
+from dataclasses import dataclass, field
+from typing import Dict, Optional, Tuple
+
+
+@dataclass
+class FetchFailState:
+    first_fail_ts: float = 0.0
+    last_fail_ts: float = 0.0
+    fail_count: int = 0
+    last_error: str = ""
+    last_event_ts: float = 0.0   # spam 방지용
+    in_fail_mode: bool = False   # fetch_fail 이벤트가 이미 발행됐는지
+
+
+@dataclass
+class FetchTracker:
+    # 고정 상수 (env로 빼지 않음)
+    FAIL_EMIT_AFTER_SEC: int = 600       # 10분 이상 지속되면 fail 이벤트
+    EVENT_MIN_INTERVAL_SEC: int = 600    # fail 이벤트 재발행 최소 간격
+
+    states: Dict[str, FetchFailState] = field(default_factory=dict)
+
+    def _get(self, key: str) -> FetchFailState:
+        if key not in self.states:
+            self.states[key] = FetchFailState()
+        return self.states[key]
+
+    def on_success(self, key: str, now_ts: Optional[float] = None) -> Tuple[bool, Optional[Dict]]:
+        """
+        성공 시: 실패 모드였다면 recovered 이벤트 1회.
+        return: (should_emit, event_payload)
+        """
+        now = now_ts or time.time()
+        st = self._get(key)
+        if st.fail_count == 0 and not st.in_fail_mode:
+            return False, None
+
+        # 복구 이벤트: fail 모드였을 때만 1회
+        if st.in_fail_mode:
+            duration = int(now - st.first_fail_ts) if st.first_fail_ts else 0
+            payload = {
+                "type": "fetch_recovered",
+                "ts": int(now),
+                "key": key,
+                "fail_count": st.fail_count,
+                "fail_duration_sec": duration,
+                "last_error": st.last_error,
+            }
+            # reset
+            self.states[key] = FetchFailState()
+            return True, payload
+
+        # fail 모드 아니었으면 그냥 reset
+        self.states[key] = FetchFailState()
+        return False, None
+
+    def on_fail(self, key: str, reason: str = "", now_ts: Optional[float] = None) -> Tuple[bool, Optional[Dict]]:
+        """
+        실패 시: 누적하다가 10분 이상 지속되면 fetch_fail 이벤트 1회.
+        return: (should_emit, event_payload)
+        """
+        now = now_ts or time.time()
+        st = self._get(key)
+        st.fail_count += 1
+        st.last_fail_ts = now
+        st.last_error = reason[:200] if reason else st.last_error
+        if st.first_fail_ts == 0.0:
+            st.first_fail_ts = now
+
+        duration = now - st.first_fail_ts
+        if duration < self.FAIL_EMIT_AFTER_SEC:
+            return False, None
+
+        # 이미 fail 이벤트를 발행했으면, 최소 간격 지나기 전엔 스팸 방지
+        if st.in_fail_mode:
+            if now - st.last_event_ts < self.EVENT_MIN_INTERVAL_SEC:
+                return False, None
+
+        st.in_fail_mode = True
+        st.last_event_ts = now
+        payload = {
+            "type": "fetch_fail",
+            "ts": int(now),
+            "key": key,
+            "fail_count": st.fail_count,
+            "fail_duration_sec": int(duration),
+            "last_error": st.last_error,
+        }
+        return True, payload
```

이제 `main.py`에서 각 심볼 fetch 결과가 비면 `on_fail`, 성공하면 `on_success` 호출해서 `events.jsonl`에 저장하면 끝.

---

## PATCH 2) gate_stats atomic write + rate_limit_blocked 카운터 추가 (E)

### ✅ 핵심

* `gate_stats.json` (또는 daily_state류) 저장을 **atomic write**로 바꿈

  * `tmp 파일 → os.replace()` 방식
* `rate_limit_blocked` 카운터 추가
* `events.jsonl` 저장 함수가 없다면 같이 추가

> 파일 추가: `SRC/l2_rotation_monitor/infra/state_store.py`
> (네가 이미 `gate_stats.json` 구현해뒀다면 그 저장부만 이걸로 교체)

```diff
diff --git a/SRC/l2_rotation_monitor/infra/state_store.py b/SRC/l2_rotation_monitor/infra/state_store.py
new file mode 100644
index 0000000..2d3f6ad
--- /dev/null
+++ b/SRC/l2_rotation_monitor/infra/state_store.py
@@ -0,0 +1,70 @@
+import json
+import os
+from pathlib import Path
+from typing import Any, Dict
+
+
+def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
+    path.parent.mkdir(parents=True, exist_ok=True)
+    tmp_path = path.with_suffix(path.suffix + ".tmp")
+    with open(tmp_path, "w", encoding="utf-8") as f:
+        json.dump(data, f, ensure_ascii=False)
+    os.replace(tmp_path, path)
```

그리고 `infra/storage.py`에 `events.jsonl` append 추가(없으면):

```diff
diff --git a/SRC/l2_rotation_monitor/infra/storage.py b/SRC/l2_rotation_monitor/infra/storage.py
index 175288723809225..9b1b77a 100644
--- a/SRC/l2_rotation_monitor/infra/storage.py
+++ b/SRC/l2_rotation_monitor/infra/storage.py
@@ -1,17 +1,31 @@
 ﻿import json
 from pathlib import Path
 from typing import Dict
 
 from config.settings import STORAGE_DIR
 from infra.logger import logger
 
 SIGNALS_PATH = Path(STORAGE_DIR) / "signals.jsonl"
+EVENTS_PATH = Path(STORAGE_DIR) / "events.jsonl"
 
 
 def append_signal(payload: Dict) -> None:
     try:
         STORAGE_DIR.mkdir(parents=True, exist_ok=True)
         with open(SIGNALS_PATH, "a", encoding="utf-8") as f:
             f.write(json.dumps(payload, ensure_ascii=False) + "\n")
     except Exception as exc:
         logger.error(f"signals.jsonl append failed: {exc}")
+
+
+def append_event(payload: Dict) -> None:
+    try:
+        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
+        with open(EVENTS_PATH, "a", encoding="utf-8") as f:
+            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
+    except Exception as exc:
+        logger.error(f"events.jsonl append failed: {exc}")
```

`gate_stats`가 어디 파일인지 지금 원격에서 확인이 안 돼서(네 로컬 반영 가능성), **패턴만** 제시할게.
기존 `json.dump(open(path,"w"))` 부분을 `atomic_write_json()`로 교체하면 됨.
그리고 `rate_limit_blocked`는 `limiter.allow()`가 막았을 때 카운터 1 증가.

---

## PATCH 3) main 루프 try/except + fetch_tracker 연결 (무인 운용 안전성 + D 연결)

### ✅ 핵심

* `while True`에서 어떤 예외가 나도 프로세스가 안 죽게
* `fetch_klines()` 빈 리스트(실패)면 fetch_tracker 누적
* 성공하면 recovered 이벤트 가능

```diff
diff --git a/SRC/l2_rotation_monitor/main.py b/SRC/l2_rotation_monitor/main.py
index 450308082492082..b2c0c84 100644
--- a/SRC/l2_rotation_monitor/main.py
+++ b/SRC/l2_rotation_monitor/main.py
@@ -1,4 +1,5 @@
 ﻿import time
+import traceback
 from typing import Dict
 
 from config.settings import (
@@ -25,10 +26,12 @@ from exchange.binance import fetch_klines
 from infra.logger import logger, setup_logging
 from infra.notifier import send_telegram_message
 from infra.rate_limiter import RateLimiter
-from infra.storage import append_signal
+from infra.storage import append_signal, append_event
+from infra.fetch_tracker import FetchTracker
 
 
 def build_symbol_pairs() -> Dict[str, str]:
@@ -60,7 +63,7 @@ def format_signal_text(leader: str, lags: list, btc_ret_15: float | None, metrics
     )
 
 
-def run_cycle(btc_candles: list, symbol_pairs: Dict[str, str], limiter: RateLimiter) -> None:
+def run_cycle(btc_candles: list, symbol_pairs: Dict[str, str], limiter: RateLimiter, fetch_tracker: FetchTracker) -> None:
     gate_ok, btc_ret_15 = btc_gate(btc_candles, BTC_GATE_ABS_RET_15)
     if not gate_ok:
         logger.info(f"BTC gate active: btc_ret_15={btc_ret_15}")
@@ -67,6 +70,9 @@ def run_cycle(btc_candles: list, symbol_pairs: Dict[str, str], limiter: RateLimit
 
     metrics_by_symbol: Dict[str, Dict] = {}
     for symbol, pair in symbol_pairs.items():
+        key = f"klines:{pair}:{TIMEFRAME}"
         candles = fetch_klines(pair, TIMEFRAME, CANDLE_LIMIT)
         if not candles:
+            should_emit, ev = fetch_tracker.on_fail(key, reason="empty_candles")
+            if should_emit and ev:
+                append_event(ev)
             logger.warning(f"{symbol} candles empty")
             continue
+
+        # 성공 처리(복구 이벤트)
+        should_emit, ev = fetch_tracker.on_success(key)
+        if should_emit and ev:
+            append_event(ev)
+
         metrics = compute_metrics(candles)
         if not metrics:
             logger.warning(f"{symbol} metrics unavailable")
             continue
@@ -101,11 +114,16 @@ def run_cycle(btc_candles: list, symbol_pairs: Dict[str, str], limiter: RateLimit
 
     key = make_signal_key(leader, lags)
     allowed, rate_reason = limiter.allow(key)
     if not allowed:
+        # rate_limit_blocked 카운터는 gate_stats 쪽 구현이 이미 있다면 거기서 +1
+        # (여기선 이벤트만 남김)
+        append_event({"type": "rate_limit_blocked", "ts": int(time.time()), "key": key, "reason": rate_reason})
         logger.info(f"rate limit blocked: {rate_reason}")
         return
 
@@ -129,6 +147,7 @@ def main() -> None:
     setup_logging()
     symbol_pairs = build_symbol_pairs()
     limiter = RateLimiter(MAX_ALERTS_PER_DAY, COOLDOWN_MINUTES)
+    fetch_tracker = FetchTracker()
 
     last_candle_ts = None
     while True:
-        btc_candles = fetch_klines(BTC_PAIR, TIMEFRAME, CANDLE_LIMIT)
-        if not btc_candles:
-            time.sleep(POLL_INTERVAL_SEC)
-            continue
-
-        candle_ts = btc_candles[-1]["open_time"]
-        if candle_ts == last_candle_ts:
-            time.sleep(POLL_INTERVAL_SEC)
-            continue
-
-        last_candle_ts = candle_ts
-        run_cycle(btc_candles, symbol_pairs, limiter)
-        time.sleep(POLL_INTERVAL_SEC)
+        try:
+            btc_key = f"klines:{BTC_PAIR}:{TIMEFRAME}"
+            btc_candles = fetch_klines(BTC_PAIR, TIMEFRAME, CANDLE_LIMIT)
+            if not btc_candles:
+                should_emit, ev = fetch_tracker.on_fail(btc_key, reason="empty_btc_candles")
+                if should_emit and ev:
+                    append_event(ev)
+                time.sleep(POLL_INTERVAL_SEC)
+                continue
+
+            should_emit, ev = fetch_tracker.on_success(btc_key)
+            if should_emit and ev:
+                append_event(ev)
+
+            candle_ts = btc_candles[-1]["open_time"]
+            if candle_ts == last_candle_ts:
+                time.sleep(POLL_INTERVAL_SEC)
+                continue
+
+            last_candle_ts = candle_ts
+            run_cycle(btc_candles, symbol_pairs, limiter, fetch_tracker)
+            time.sleep(POLL_INTERVAL_SEC)
+        except Exception as exc:
+            # 무인 운용: 절대 죽지 않게
+            logger.error(f"main loop error: {exc}")
+            logger.error(traceback.format_exc()[:2000])
+            append_event({"type": "runtime_error", "ts": int(time.time()), "error": str(exc)[:300]})
+            time.sleep(5)
```

---

# 적용 후 기대 결과(검토 포인트)

* `events.jsonl`에 최소한 아래 타입들이 **드문드문** 남아야 정상:

  * `fetch_fail` (10분 이상 장애 지속 시)
  * `fetch_recovered` (장애 복구 시)
  * `rate_limit_blocked` (알림 제한 막힘)
  * `runtime_error` (예외로 죽을 뻔한 순간)
* 장애가 길어져도 **스팸 로그가 아니라**, “상태 변화 + 10분 간격” 정도로만 남게 됨

---

원격에서 “개선 적용 완료” 상태를 내가 지금 당장 확실히 확인하려면, 방금 커밋 SHA나 HEAD가 바뀐 게 보여야 하는데(현재 대화에선 원격 탐색 결과가 이전 SHA로만 잡혔었음), 너가 확인할 때는 `events.jsonl`에 위 이벤트가 찍히는지로 바로 검증하면 돼.

repo: marklee929/coin_scalper
target: SRC/l2_rotation_monitor

현재 상태:
- heartbeat/skip/backoff 기본 구조는 이미 있음
- binance.py에 _log_fetch_fail(type=fetch_fail) 단발 로그가 존재
- counters.py가 STATE_PATH에 json.dump로 저장(atomic 아님)
- main.py while 루프에 try/except 없음

목표:
final_maintanance.md의 PATCH 1~3을 "현재 코드 구조에 맞게" 적용하되,
기존 구현(이벤트 로깅, counters.py, binance.py의 backoff 로직)을 최대한 유지하고
중복/충돌 없이 최소 변경으로 반영해라.

=== PATCH 3 (최우선) main loop try/except ===
- SRC/l2_rotation_monitor/main.py의 메인 while 루프를 try/except로 감싸라.
- 예외 발생 시 프로세스가 죽지 않게 하고, 다음을 수행:
  1) logger.error로 예외 및 traceback 일부 기록
  2) 이벤트 로그에 type="runtime_error" 1줄 기록(있다면 events.jsonl / 아니면 기존 이벤트 저장 경로)
  3) 짧은 sleep 후 루프 지속

=== PATCH 2 gate_stats atomic write + rate_limit_blocked 카운터 ===
- SRC/l2_rotation_monitor/infra/state_store.py 추가:
  - atomic_write_json(path, data): tmp write 후 os.replace
- counters.py에서 STATE_PATH 저장하는 모든 json.dump를 atomic_write_json으로 교체
- rate limit이 막혔을 때:
  - "이벤트 로그"만 남기지 말고 counters에 rate_limit_blocked += 1 누적
  - 기존 counters 구조에 맞게 (date rollover 포함) 넣어라

=== PATCH 1 fetch_fail 누적/복구 이벤트 ===
- 현재 binance.py에 있는 단발 _log_fetch_fail은 유지 가능하나,
  "누적/지속/복구"를 구분하기 위해 fetch_tracker(또는 fetch_fail_tracker) 모듈을 새로 추가해라.
- 요구 동작:
  - fetch 실패(빈 캔들, 예외, backoff로 fetch skip 포함) 시 fail_count 누적
  - fail_duration_sec >= 600초(10분)일 때 type="fetch_fail" 이벤트를 1회 기록
  - 이후 성공하면 type="fetch_recovered" 이벤트를 1회 기록
  - 스팸 방지: fail 이벤트는 최소 10분 간격 또는 상태 변화 시만 기록
- key는 최소한 "BTC_PAIR", 그리고 각 watch symbol pair 별로 구분 가능하게 구성해라.
- 이벤트 저장 경로는 기존 프로젝트가 쓰는 이벤트 로그와 동일하게 맞춰라.

=== 산출물 ===
1) 수정된 파일 목록 + 핵심 diff
2) 동작 설명은 최소로, “실패 지속/복구를 어떻게 구분하는지”만 짧게
3) 테스트 방법:
   - 일부러 BINANCE_BASE_URL을 틀려서 10분 지속 시 fetch_fail 뜨는지
   - 다시 정상으로 바꾸면 fetch_recovered 뜨는지
   - runtime_error 발생해도 프로세스가 유지되는지

좋아. “마지막 패치”는 딱 이것만 하면 돼:

* `fetch_fail` / `fetch_recovered` 이벤트에 **key 유지**
* 거기에 **symbol_pair 필드 병행 추가**

아래는 **unified diff**(PATCH 1에 들어가는 fetch_tracker 기준)야.

---

## PATCH: fetch_fail / fetch_recovered에 symbol_pair 병행 추가

### 1) `infra/fetch_tracker.py`

```diff
diff --git a/SRC/l2_rotation_monitor/infra/fetch_tracker.py b/SRC/l2_rotation_monitor/infra/fetch_tracker.py
index b3a6d2f..d9a1f02 100644
--- a/SRC/l2_rotation_monitor/infra/fetch_tracker.py
+++ b/SRC/l2_rotation_monitor/infra/fetch_tracker.py
@@ -1,6 +1,6 @@
 import time
 from dataclasses import dataclass, field
-from typing import Dict, Optional, Tuple
+from typing import Dict, Optional, Tuple
 
 
 @dataclass
@@ -33,7 +33,7 @@ class FetchTracker:
 
     states: Dict[str, FetchFailState] = field(default_factory=dict)
 
-    def on_success(self, key: str, now_ts: Optional[float] = None) -> Tuple[bool, Optional[Dict]]:
+    def on_success(self, key: str, symbol_pair: str | None = None, now_ts: Optional[float] = None) -> Tuple[bool, Optional[Dict]]:
         """
         성공 시: 실패 모드였다면 recovered 이벤트 1회.
         return: (should_emit, event_payload)
@@ -50,6 +50,7 @@ class FetchTracker:
             payload = {
                 "type": "fetch_recovered",
                 "ts": int(now),
                 "key": key,
+                "symbol_pair": symbol_pair,
                 "fail_count": st.fail_count,
                 "fail_duration_sec": duration,
                 "last_error": st.last_error,
             }
@@ -64,7 +65,7 @@ class FetchTracker:
         self.states[key] = FetchFailState()
         return False, None
 
-    def on_fail(self, key: str, reason: str = "", now_ts: Optional[float] = None) -> Tuple[bool, Optional[Dict]]:
+    def on_fail(self, key: str, symbol_pair: str | None = None, reason: str = "", now_ts: Optional[float] = None) -> Tuple[bool, Optional[Dict]]:
         """
         실패 시: 누적하다가 10분 이상 지속되면 fetch_fail 이벤트 1회.
         return: (should_emit, event_payload)
@@ -95,6 +96,7 @@ class FetchTracker:
         payload = {
             "type": "fetch_fail",
             "ts": int(now),
             "key": key,
+            "symbol_pair": symbol_pair,
             "fail_count": st.fail_count,
             "fail_duration_sec": int(duration),
             "last_error": st.last_error,
         }
         return True, payload
```

---

### 2) `main.py`에서 호출부에 symbol_pair 넘기기

(실제 파일 라인은 네 프로젝트에 맞춰서 넣으면 됨. 핵심만 diff로)

```diff
diff --git a/SRC/l2_rotation_monitor/main.py b/SRC/l2_rotation_monitor/main.py
index b2c0c84..c0c4e0a 100644
--- a/SRC/l2_rotation_monitor/main.py
+++ b/SRC/l2_rotation_monitor/main.py
@@ -70,12 +70,12 @@ def run_cycle(...):
     for symbol, pair in symbol_pairs.items():
         key = f"klines:{pair}:{TIMEFRAME}"
         candles = fetch_klines(pair, TIMEFRAME, CANDLE_LIMIT)
         if not candles:
-            should_emit, ev = fetch_tracker.on_fail(key, reason="empty_candles")
+            should_emit, ev = fetch_tracker.on_fail(key, symbol_pair=pair, reason="empty_candles")
             if should_emit and ev:
                 append_event(ev)
             continue
 
-        should_emit, ev = fetch_tracker.on_success(key)
+        should_emit, ev = fetch_tracker.on_success(key, symbol_pair=pair)
         if should_emit and ev:
             append_event(ev)
@@ -150,10 +150,10 @@ def main():
         try:
             btc_key = f"klines:{BTC_PAIR}:{TIMEFRAME}"
             btc_candles = fetch_klines(BTC_PAIR, TIMEFRAME, CANDLE_LIMIT)
             if not btc_candles:
-                should_emit, ev = fetch_tracker.on_fail(btc_key, reason="empty_btc_candles")
+                should_emit, ev = fetch_tracker.on_fail(btc_key, symbol_pair=BTC_PAIR, reason="empty_btc_candles")
                 if should_emit and ev:
                     append_event(ev)
                 time.sleep(POLL_INTERVAL_SEC)
                 continue
 
-            should_emit, ev = fetch_tracker.on_success(btc_key)
+            should_emit, ev = fetch_tracker.on_success(btc_key, symbol_pair=BTC_PAIR)
             if should_emit and ev:
                 append_event(ev)
```

---

### 결과 이벤트 예시

```json
{"type":"fetch_fail","ts":1706xxxx,"key":"klines:ARBUSDT:15m","symbol_pair":"ARBUSDT","fail_count":23,"fail_duration_sec":742,"last_error":"empty_candles"}
{"type":"fetch_recovered","ts":1706xxxx,"key":"klines:ARBUSDT:15m","symbol_pair":"ARBUSDT","fail_count":23,"fail_duration_sec":905,"last_error":"empty_candles"}
```

이거까지 들어가면 “장애 분석 로그”는 사람 눈으로도 바로 읽히는 수준까지 마감돼.

