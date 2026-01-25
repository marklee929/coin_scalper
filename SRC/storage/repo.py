import json
import time
import hashlib
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from storage.db import connect

_LOGGER = logging.getLogger("trading")
_LAST_SNAPSHOT_TS: Dict[str, float] = {}
_LAST_SNAPSHOT_HASH: Dict[str, str] = {}


def _now_ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=True)
    except Exception:
        return json.dumps({"_repr": repr(obj)}, ensure_ascii=True)


def append_event(level: str,
                 type: str,
                 symbol: Optional[str] = None,
                 message: Optional[str] = None,
                 data: Optional[Any] = None,
                 ts: Optional[str] = None,
                 db_path: Optional[str] = None) -> None:
    try:
        with connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO event_log (ts, level, type, symbol, message, data_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ts or _now_ts(),
                    level,
                    type,
                    symbol,
                    message,
                    _safe_json(data) if data is not None else None
                ),
            )
            conn.commit()
    except Exception as e:
        _LOGGER.error("event_log insert failed: %s", e)


def append_trade(symbol: str,
                 side: str,
                 qty: float,
                 price: Optional[float] = None,
                 quote_qty: Optional[float] = None,
                 fee: Optional[float] = None,
                 fee_asset: Optional[str] = None,
                 reason: Optional[str] = None,
                 order_id: Optional[str] = None,
                 raw: Optional[Any] = None,
                 ts: Optional[str] = None,
                 db_path: Optional[str] = None) -> None:
    try:
        with connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO trade_log
                (ts, symbol, side, qty, price, quote_qty, fee, fee_asset, reason, order_id, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts or _now_ts(),
                    symbol,
                    side,
                    qty,
                    price,
                    quote_qty,
                    fee,
                    fee_asset,
                    reason,
                    order_id,
                    _safe_json(raw) if raw is not None else None
                ),
            )
            conn.commit()
    except Exception as e:
        append_event(
            level="ERROR",
            type="DB_ERROR",
            symbol=symbol,
            message=f"trade_log insert failed: {e}",
            data={"side": side, "qty": qty},
            db_path=db_path,
        )


def upsert_position(symbol: str,
                    status: str,
                    qty: float,
                    avg_price: Optional[float] = None,
                    entry_ts: Optional[str] = None,
                    exit_ts: Optional[str] = None,
                    pnl_pct: Optional[float] = None,
                    tp_pct: Optional[float] = None,
                    sl_rule: Optional[str] = None,
                    data: Optional[Any] = None,
                    ts: Optional[str] = None,
                    db_path: Optional[str] = None) -> None:
    try:
        with connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO positions
                (symbol, status, qty, avg_price, entry_ts, exit_ts, last_update_ts, pnl_pct, tp_pct, sl_rule, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    status=excluded.status,
                    qty=excluded.qty,
                    avg_price=excluded.avg_price,
                    entry_ts=excluded.entry_ts,
                    exit_ts=excluded.exit_ts,
                    last_update_ts=excluded.last_update_ts,
                    pnl_pct=excluded.pnl_pct,
                    tp_pct=excluded.tp_pct,
                    sl_rule=excluded.sl_rule,
                    data_json=excluded.data_json
                """,
                (
                    symbol,
                    status,
                    qty,
                    avg_price,
                    entry_ts,
                    exit_ts,
                    ts or _now_ts(),
                    pnl_pct,
                    tp_pct,
                    sl_rule,
                    _safe_json(data) if data is not None else None
                ),
            )
            conn.commit()
    except Exception as e:
        append_event(
            level="ERROR",
            type="DB_ERROR",
            symbol=symbol,
            message=f"positions upsert failed: {e}",
            db_path=db_path,
        )


def save_snapshot(kind: str,
                  data: Any,
                  min_interval_sec: int = 60,
                  force: bool = False,
                  ts: Optional[str] = None,
                  db_path: Optional[str] = None) -> bool:
    now = time.time()
    payload = _safe_json(data)
    payload_hash = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    last_ts = _LAST_SNAPSHOT_TS.get(kind, 0.0)
    last_hash = _LAST_SNAPSHOT_HASH.get(kind)

    if not force:
        if last_hash == payload_hash and (now - last_ts) < min_interval_sec:
            return False
        if (now - last_ts) < min_interval_sec and last_hash == payload_hash:
            return False

    try:
        with connect(db_path) as conn:
            conn.execute(
                "INSERT INTO snapshots (ts, kind, data_json) VALUES (?, ?, ?)",
                (ts or _now_ts(), kind, payload),
            )
            conn.commit()
        _LAST_SNAPSHOT_TS[kind] = now
        _LAST_SNAPSHOT_HASH[kind] = payload_hash
        return True
    except Exception as e:
        append_event(
            level="ERROR",
            type="DB_ERROR",
            message=f"snapshots insert failed: {e}",
            db_path=db_path,
        )
        return False


def get_latest_snapshot(kind: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    try:
        with connect(db_path) as conn:
            row = conn.execute(
                "SELECT ts, data_json FROM snapshots WHERE kind = ? ORDER BY id DESC LIMIT 1",
                (kind,),
            ).fetchone()
        if not row:
            return None
        data = json.loads(row["data_json"])
        return {"ts": row["ts"], "data": data}
    except Exception as e:
        append_event(
            level="ERROR",
            type="DB_ERROR",
            message=f"get_latest_snapshot failed: {e}",
            db_path=db_path,
        )
        return None


def fetch_trades_by_date(date_str: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        with connect(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM trade_log WHERE ts LIKE ? ORDER BY id ASC",
                (f"{date_str}%",),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        append_event(
            level="ERROR",
            type="DB_ERROR",
            message=f"fetch_trades_by_date failed: {e}",
            db_path=db_path,
        )
        return []


def fetch_open_positions(db_path: Optional[str] = None) -> List[str]:
    try:
        with connect(db_path) as conn:
            rows = conn.execute(
                "SELECT symbol FROM positions WHERE status = 'OPEN' AND qty > 0"
            ).fetchall()
        return [r["symbol"] for r in rows]
    except Exception as e:
        append_event(
            level="ERROR",
            type="DB_ERROR",
            message=f"fetch_open_positions failed: {e}",
            db_path=db_path,
        )
        return []
