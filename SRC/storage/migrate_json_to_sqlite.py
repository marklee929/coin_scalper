import argparse
import json
import os
import re
import shutil
from glob import glob
from typing import Any, Dict, Optional

from storage.repo import append_event, append_trade, upsert_position, save_snapshot


DATE_PATTERNS = [
    re.compile(r"(20\d{2}-\d{2}-\d{2})"),
    re.compile(r"(20\d{2}_\d{2}_\d{2})"),
    re.compile(r"(20\d{2}\d{2}\d{2})"),
]


def _extract_date(path: str) -> Optional[str]:
    name = os.path.basename(path)
    for pat in DATE_PATTERNS:
        m = pat.search(name)
        if not m:
            continue
        val = m.group(1)
        if "_" in val:
            return val.replace("_", "-")
        if "-" in val:
            return val
        if len(val) == 8:
            return f"{val[0:4]}-{val[4:6]}-{val[6:8]}"
    return None


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _migrate_trade_list(payload: Any, ts: Optional[str], db_path: Optional[str]) -> int:
    count = 0
    if not isinstance(payload, list):
        return count
    for item in payload:
        if not isinstance(item, dict):
            continue
        symbol = item.get("code") or item.get("symbol")
        side = item.get("action") or item.get("side")
        qty = item.get("qty") or item.get("quantity")
        price = item.get("price") or item.get("sell_price")
        if not symbol or not side or qty is None:
            continue
        append_trade(
            symbol=str(symbol),
            side=str(side),
            qty=float(qty),
            price=float(price) if price is not None else None,
            reason=item.get("reason"),
            raw=item,
            ts=item.get("timestamp") or (f"{ts} 00:00:00" if ts else None),
            db_path=db_path,
        )
        count += 1
    return count


def _migrate_positions(payload: Any, ts: Optional[str], db_path: Optional[str]) -> int:
    count = 0
    if not isinstance(payload, list):
        return count
    for item in payload:
        if not isinstance(item, dict):
            continue
        symbol = item.get("code") or item.get("symbol")
        qty = item.get("quantity") or item.get("qty")
        price = item.get("buy_price") or item.get("avg_price")
        if not symbol or qty is None:
            continue
        upsert_position(
            symbol=str(symbol),
            status="OPEN",
            qty=float(qty),
            avg_price=float(price) if price is not None else None,
            entry_ts=item.get("timestamp") or (f"{ts} 00:00:00" if ts else None),
            data=item,
            db_path=db_path,
        )
        count += 1
    return count


def _classify_and_migrate(path: str, payload: Any, db_path: Optional[str]) -> int:
    name = os.path.basename(path).lower()
    ts = _extract_date(path)

    if "trades_" in name or "trade" in name:
        return _migrate_trade_list(payload, ts, db_path)

    if "positions" in name or "current_positions" in name:
        return _migrate_positions(payload, ts, db_path)

    if "universe" in name:
        save_snapshot("UNIVERSE", payload, force=True, ts=f"{ts} 00:00:00" if ts else None, db_path=db_path)
        return 1

    if "watchlist" in name:
        save_snapshot("WATCHLIST", payload, force=True, ts=f"{ts} 00:00:00" if ts else None, db_path=db_path)
        return 1

    if "candle" in name:
        save_snapshot("CANDLE", payload, force=True, ts=f"{ts} 00:00:00" if ts else None, db_path=db_path)
        return 1

    if "summary" in name:
        save_snapshot("SUMMARY", payload, force=True, ts=f"{ts} 00:00:00" if ts else None, db_path=db_path)
        return 1

    # fallback
    save_snapshot(
        "UNKNOWN_JSON",
        {"path": path, "data": payload},
        force=True,
        ts=f"{ts} 00:00:00" if ts else None,
        db_path=db_path,
    )
    return 1


def migrate(src_dir: str, archive_dir: Optional[str] = None, delete: bool = False, db_path: Optional[str] = None) -> None:
    json_files = glob(os.path.join(src_dir, "**", "*.json"), recursive=True)
    for path in json_files:
        try:
            payload = _read_json(path)
            count = _classify_and_migrate(path, payload, db_path)
            append_event(level="INFO", type="MIGRATION", message=f"{path} -> {count} rows", db_path=db_path)
        except Exception as e:
            append_event(level="ERROR", type="MIGRATION_ERROR", message=str(e), data={"path": path}, db_path=db_path)
            continue

        if delete:
            try:
                os.remove(path)
            except Exception as e:
                append_event(level="WARN", type="MIGRATION_ERROR", message=str(e), data={"path": path}, db_path=db_path)
        elif archive_dir:
            rel = os.path.relpath(path, src_dir)
            dst = os.path.join(archive_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                shutil.move(path, dst)
            except Exception as e:
                append_event(level="WARN", type="MIGRATION_ERROR", message=str(e), data={"path": path}, db_path=db_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True, help="source directory to scan for JSON files")
    parser.add_argument("--db", default=None, help="sqlite db path (default: storage/bot.db)")
    parser.add_argument("--archive", default=None, help="archive directory for migrated files")
    parser.add_argument("--delete", action="store_true", help="delete files after migration")
    args = parser.parse_args()

    migrate(args.src, archive_dir=args.archive, delete=args.delete, db_path=args.db)


if __name__ == "__main__":
    main()
