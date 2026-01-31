# L2 Rotation Monitor

Minimal implementation based on `DOCS/l2_rotation_monitor_dev_doc/architect.md`.

## Run

```bash
cd SRC/l2_rotation_monitor
python main.py
```

## Environment overrides

- `L2_WATCHLIST` (default: `ARB,OP,S`)
- `L2_WATCHLIST_PAIRS` (default: `ARBUSDT,OPUSDT,SUSDT`)
- `L2_BTC_PAIR` (default: `BTCUSDT`)
- `L2_TIMEFRAME` (default: `15m`)
- `L2_CANDLE_LIMIT` (default: `200`)
- `L2_POLL_INTERVAL_SEC` (default: `20`)
- `L2_HEARTBEAT_INTERVAL_SEC` (default: `3600`)
- `BTC_GATE_ABS_RET_15` (default: `0.02`)
- `VOL_DROP_RATIO` (default: `0.5`)
- `LEADER_GAP`, `LEADER_MIN_RET_60`, `LAG_GAP`, `LAG_FLOOR_RET_60`, `LAG_VOL_FLOOR`
- `MAX_ALERTS_PER_DAY`, `COOLDOWN_MINUTES`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

## Notes
- Data source: Binance public REST `api/v3/klines`.
- Signals are appended to `storage/signals.jsonl`.
- Skip/heartbeat events are appended to `storage/events.jsonl`.
- Gate counters are stored in `storage/gate_stats.json`.
- Rate limit state is stored in `storage/rate_state.json`.

