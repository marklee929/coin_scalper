너는 코드 리뷰어다. GitHub repo: marklee929/coin_scalper 를 기준으로,
L2 Rotation Monitor(SRC/l2_rotation_monitor) 개선사항 반영 여부를 점검해라.

목표:
- “무인 1주 운용” 관점에서 observability(heartbeat/skip/backoff/fetch_fail) 및 state 통계가
  설계 의도대로 들어갔는지 확인하고, 누락/버그/스팸 가능성을 지적한다.
- 자동매매 로직이 섞이지 않았는지 확인한다.

=== 0) 점검 대상 경로 ===
- SRC/l2_rotation_monitor/main.py
- SRC/l2_rotation_monitor/exchange/binance.py
- SRC/l2_rotation_monitor/infra/storage.py (또는 로그 저장 모듈)
- SRC/l2_rotation_monitor/infra/rate_limiter.py
- SRC/l2_rotation_monitor/infra/logger.py
- SRC/l2_rotation_monitor/config/* (settings)
- (있다면) SRC/l2_rotation_monitor/infra/daily_state.py 혹은 state 관련 파일
- DOCS/l2_rotation_monitor_dev_doc/architect.md, SRC/l2_rotation_monitor/README.md

=== 1) 필수 기능 체크(반영 여부를 “파일/함수/라인 근거”로 보고) ===
A. skip 로그
- 신호 미발생 시에도 "type=skip" 형태로 사유가 저장되는가?
- 사유 키 후보: btc_gate, volume_dead_zone, not_enough_metrics, leader_fail, lag_fail, rate_limit_blocked 등
- 저장 위치: jsonl (예: storage/signals.jsonl or storage/events.jsonl)
- 너무 잦은 스팸이 되지 않게 최소 간격/상태변화 기반 억제가 있는가?

B. heartbeat 로그 (시간 기준)
- 캔들 갱신 여부와 무관하게 “시간 기준”(예: 1시간)으로 1회 이상 기록되는가?
- heartbeat payload에 다음이 포함되는가?
  - last_success_ts (마지막 성공 fetch 시각)
  - last_success_candle_open_time (가능하면)
  - last_success_symbol (마지막 성공 심볼)
  - success_age_sec = now - last_success_ts
- heartbeat가 “시장 데이터가 끊겨도” 남는 구조인지 확인해라.

C. backoff 로그 (스팸 억제 포함)
- Binance fetch에서 rate limit(429/-1003) 또는 네트워크 에러 발생 시
  backoff를 증가시키고 next_allowed_ts를 계산/적용하는가?
- backoff 이벤트를 아래 형태로 기록하는가?
  {type:"backoff", wait_sec, next_allowed_ts, reason, symbol_pair}
- 기록 정책:
  - 상태 변화(OFF→ON, wait_sec 변화, reason 변화) 때는 즉시 1회
  - 그 외엔 최소 간격(예: 10분)으로만 1회
- backoff 중 fetch_klines()가 빈 리스트 반환만 하고 아무 기록이 없는 “침묵”이 생기지 않는가?

D. fetch_fail 이벤트 (장기 실패 감지)
- 특정 심볼/전체 심볼 fetch 실패가 일정 횟수/시간 누적될 때
  {type:"fetch_fail", symbol_pair, fail_count, fail_duration_sec, last_error} 같은 이벤트가 남는가?
- 실패 누적이 풀리면 (recovered) 이벤트가 남는가? (선택이지만 있으면 좋음)

E. gate_stats / daily_state 통계
- gate_stats.json 또는 daily_state.json이 존재하고 아래 카운터가 유지되는가?
  - btc_gate_hits
  - volume_dead_zone_hits (정책: 사이클당 1회인지, 심볼당 누적인지 명시)
  - leader_fail, lag_fail, rate_limit_blocked 등 (있다면)
- state 파일 쓰기 실패/깨짐(부분 write) 위험을 줄이는 안전장치가 있는가?
  - 원자적 write(임시파일→rename) 또는 예외 처리

=== 2) 안전성 체크(무인 1주 운용 관점) ===
- 프로세스가 죽지 않도록 try/except + backoff가 있는가?
- 네트워크 오류 시 무한 spam/무한 sleep/무한 빈 fetch 루프에 빠질 가능성이 있는가?
- 로그 파일이 과도하게 커질 위험이 있는가? (스팸 억제 정책 평가)
- 환경변수로 “간격” 같은 위험 튜닝 포인트가 열려있지 않은가?
  (간격은 코드 상수 고정이 바람직)

=== 3) 아키텍처 준수 체크 ===
- Watchlist가 ARB/OP/S로 고정되어 있고, 자동 확장/추가 로직이 없는가?
- Timeframe이 15m only로 강제되는가?
- 주문/포지션/레버리지 관련 코드가 SRC/l2_rotation_monitor 내부에 없는가?

=== 4) 출력 형식(반드시 이렇게) ===
1) "✅ 반영됨" / "⚠️ 부분 반영" / "❌ 누락"을 항목별로 표로 요약 (짧은 키워드만)
2) 각 항목에 대해:
   - 근거: 파일 경로 + 함수명 + 핵심 코드 스니펫(짧게)
   - 리스크: 어떤 상황에서 침묵/오동작/스팸이 나는지
   - 수정 제안: 최소 변경으로 고치기(패치 형태로 제시하면 더 좋음)
3) 마지막에 “가장 먼저 고칠 3개”만 우선순위로 뽑아라.

중요:
- 새 기능을 멋대로 추가하지 말고, 위 체크리스트 충족을 목표로만 리뷰해라.
- 자동매매 기능은 절대 제안하지 마라.
