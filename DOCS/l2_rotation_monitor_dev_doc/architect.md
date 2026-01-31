# L2 Rotation Monitor — architect.md

## 0. One-liner
돈 벌려고 자동매매하는 봇이 아니라, 사람이 없어도 “망하지 않게” 로테이션 신호만 모으는 15분봉 모니터링 시스템.

---

## 1. Goals (목표)
- ARB / OP / S(구 FTM) 3종목의 **섹터 내 로테이션**을 15분봉 기반으로 감지한다.
- 리더(강한 코인)와 지연(다음 차례 후보) 코인을 판별하고, 조건 충족 시 **로그 + 알림**을 남긴다.
- 여행(무인 운영) 상황에서도 **사고 없이 지속 실행**되도록 안전장치를 최우선으로 설계한다.
- 수익/매매는 목표가 아니다. **데이터 축적과 사후 검증**이 목표다.

---

## 2. Non-Goals (하지 않는 것)
- 주문 실행, 포지션 진입(롱/숏), 레버리지 사용
- 손절/익절/리스크 관리 자동화(거래 자체가 없으므로)
- 코인 추가/자동 확장(종목 고정)
- 1분/5분/1시간 이상 타임프레임 지원(15m only)

---

## 3. Hard Constraints (의도적 제약)
- Watchlist: **ARB, OP, S** (추가 금지)
- Timeframe: **15m only**
- Automation: **Signal + Logging + Notification only**
- “옵션적 접근”: 예측/복구 설계 대신, **관측과 차단(gate)** 중심

---

## 4. Key Concepts (핵심 개념)
### 4.1 Leader
- 최근 30~60분 수익률 + 거래량 변화율에서 상대적으로 가장 강한 코인.
- “로테이션의 중심” 역할을 하는 것으로 가정.

### 4.2 Lag (Follower / Next candidate)
- 리더 대비 수익률이 낮지만 거래량이 유지되고, 가격 붕괴가 없는 코인.
- “다음 차례 후보”로 로그에 남김.

### 4.3 Market Gate
- BTC 15분 변동성이 과도하면 전체 신호 OFF.
- 시장이 “뉴스/폭탄/급변” 상태이면 로테이션 판별 자체가 의미 없다고 가정.

---

## 5. Data Model & Metrics (지표 정의)
(기본값이며, 로그 축적 후 보수적으로 조정 가능)

### 5.1 Returns
- `ret_60 = close_now / close_60m_ago - 1`
- `ret_30 = close_now / close_30m_ago - 1` (참고)

### 5.2 Volume change
- `vol_60 = sum(volume last 4 candles)`
- `vol_prev_60 = sum(volume previous 4 candles)`
- `vol_chg = vol_60 / vol_prev_60 - 1`

### 5.3 Score (simple & safe)
- `score = ret_60 + 0.3 * clip(vol_chg, -1, +3)`

---

## 6. Signal Rules (신호 규칙)
### 6.1 BTC Gate (시장 전체 차단)
- `btc_ret_15 = close_now / close_prev - 1`
- `abs(btc_ret_15) > BTC_GATE_ABS_RET_15` → **signals OFF**

### 6.2 Volume Dead Zone Filter (횡보/의미 없는 구간 배제)
- 각 코인별 `vol_60` 이 24h 기준 중앙값 대비 너무 낮으면 신호 생성 금지
- 예: `vol_60 < median(vol_60 over last 24h) * VOL_DROP_RATIO` → no signal

### 6.3 Leader Detection
- score 1등이 리더 후보
- 최소 조건:
  - `score_1 - score_2 >= LEADER_GAP`
  - `ret_60 >= LEADER_MIN_RET_60`

### 6.4 Lag Detection (Next candidate)
리더가 잡힌 후, 나머지 코인 중:
- `ret_60_lag <= ret_60_leader - LAG_GAP`
- `ret_60_lag >= LAG_FLOOR_RET_60`
- `vol_chg_lag >= LAG_VOL_FLOOR`

### 6.5 Rate limiting (스팸 방지)
- 하루 최대 `MAX_ALERTS_PER_DAY` 회
- 동일 조합(leader -> lagset) **cooldown** 적용

---

## 7. Architecture Overview (구성)
### 7.1 Modules
- `exchange/`: 15m 캔들 수집 (public data only)
- `core/`:
  - `gates.py` : BTC gate
  - `indicators.py` : return/volume/median/clip
  - `scoring.py` : metrics & score
  - `signal_engine.py` : leader/lag 결정
- `infra/`:
  - `storage.py` : jsonl 저장
  - `notifier.py` : Telegram (optional)
  - `rate_limiter.py` : daily cap + cooldown
  - `logger.py` : 콘솔/파일 로깅(옵션)

### 7.2 Data Flow
1) Fetch candles (ARB/OP/S/BTC)  
2) BTC gate check  
3) Compute metrics for ARB/OP/S  
4) Leader ranking  
5) Lag candidates selection  
6) Rate-limit / cooldown check  
7) Persist signal (jsonl)  
8) Send notification (telegram)

---

## 8. Storage (저장)
### 8.1 signals.jsonl (append-only)
- 한 줄에 한 신호(record)
- 필드 예:
  - `ts` (unix seconds)
  - `leader`
  - `lags` (list)
  - `metrics` (symbol → metrics dict)
  - `btc_ret_15`
  - `reason`

### 8.2 rate_state.json (stateful)
- 일자별 알림 카운트 + cooldown key map

---

## 9. Reliability & Safety (여행/무인 운영 기준)
- 프로세스가 절대 죽지 않게 `try/except` + backoff
- 네트워크/거래소 API 오류 시:
  - 재시도(짧은 sleep)
  - 실패 로그만 남기고 다음 루프 진행
- “보수성 우선”:
  - gate가 조금이라도 위험하면 신호 OFF
  - 과신호 방지를 위한 hard limit

---

## 10. Configuration (설정)
환경변수(.env) + 코드 상수로 고정
- 종목/타임프레임은 고정값으로 둠(변경 금지)
- 민감값:
  - `BTC_GATE_ABS_RET_15`
  - `MAX_ALERTS_PER_DAY`
  - `COOLDOWN_MINUTES`
  - `VOL_DROP_RATIO`
  - leader/lag threshold 값들

---

## 11. Deployment (운영)
- 단일 프로세스 실행
- 추천: VPS/서버에서 `systemd` 또는 `pm2` 스타일로 자동 재시작
- 로그는 파일로도 남기되, 핵심 데이터는 jsonl이 “진짜 기록”

---

## 12. Testing Plan (테스트)
### 12.1 Unit tests
- indicator 계산(수익률/거래량/중앙값)
- scoring & leader selection
- lag selection
- rate limiter (daily cap + cooldown)

### 12.2 Simulation (백테스트 아님)
- 과거 캔들 데이터를 재생하면서 “신호가 얼마나 발생했는지”만 확인
- 목적은 수익 검증이 아니라 “쓰레기/쓸만함” 판단을 위한 로그 품질 평가

---

## 13. Exit Criteria (프로젝트 종료 조건)
다음 중 하나면 성공:
- 여행 기간 동안 사고 없이 실행
- 의미 있는 로테이션 로그가 충분히 쌓임(임계 횟수 이상)
- “이건 쓰레기/이건 쓸만함” 결론 도출 가능

---

## 14. Future Extensions (확장하더라도 원칙 고정)
- 반자동(현물) 확장 가능: 하지만 주문 실행 모듈은 별도 프로젝트/레포로 분리
- 종목 추가는 철학 위반이므로 원칙상 금지(실험 레포를 따로 파는 방식만 허용)
- 지표 고도화는 가능(예: 변동성/상대강도/상관/지연 등) 단, “gate 우선” 유지

---
