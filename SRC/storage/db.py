import os
import sqlite3
from threading import Lock
from typing import Optional

_INIT_LOCK = Lock()
_INITIALIZED = set()


def get_db_path(db_path: Optional[str] = None) -> str:
    if db_path:
        return db_path
    base_dir = os.path.dirname(__file__)
    return os.path.join(base_dir, "bot.db")


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = get_db_path(db_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn, path)
    return conn


def init_db(conn: sqlite3.Connection, db_path: str) -> None:
    with _INIT_LOCK:
        if db_path in _INITIALIZED:
            return

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trade_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                price REAL,
                quote_qty REAL,
                fee REAL,
                fee_asset TEXT,
                reason TEXT,
                order_id TEXT,
                raw_json TEXT
            );

            CREATE TABLE IF NOT EXISTS event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                level TEXT NOT NULL,
                type TEXT NOT NULL,
                symbol TEXT,
                message TEXT,
                data_json TEXT
            );

            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                qty REAL NOT NULL,
                avg_price REAL,
                entry_ts TEXT,
                exit_ts TEXT,
                last_update_ts TEXT,
                pnl_pct REAL,
                tp_pct REAL,
                sl_rule TEXT,
                data_json TEXT
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                kind TEXT NOT NULL,
                data_json TEXT NOT NULL
            );
            """
        )

        conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_ts ON trade_log(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_symbol_ts ON trade_log(symbol, ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_event_ts ON event_log(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_event_type_ts ON event_log(type, ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_event_symbol_ts ON event_log(symbol, ts)")
        conn.commit()
        _INITIALIZED.add(db_path)
