import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from storage.db import connect
from utils.telegram import send_telegram_message

KST = timezone(timedelta(hours=9))

REPORT_EVERY_HOURS = 3
DB_PATH: Optional[str] = None  # None -> default storage/bot.db


def _utc_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _sum_event_counts(since_ts_utc: str) -> Tuple[int, int, int]:
    """ENTRY, EXIT_TP, EXIT_SL count"""
    with connect(DB_PATH) as conn:
        entry = conn.execute(
            "SELECT COUNT(*) AS c FROM event_log WHERE type='ENTRY' AND ts >= ?",
            (since_ts_utc,),
        ).fetchone()["c"]
        tp = conn.execute(
            "SELECT COUNT(*) AS c FROM event_log WHERE type='EXIT_TP' AND ts >= ?",
            (since_ts_utc,),
        ).fetchone()["c"]
        sl = conn.execute(
            "SELECT COUNT(*) AS c FROM event_log WHERE type='EXIT_SL' AND ts >= ?",
            (since_ts_utc,),
        ).fetchone()["c"]
    return int(entry), int(tp), int(sl)


def _realized_pnl_from_trade_log(since_ts_utc: str) -> Optional[float]:
    """
    trade_log에 quote_qty가 있으면
    realized = sum(SELL.quote_qty) - sum(BUY.quote_qty)
    (해당 구간 내 체결분만 집계. FIFO 정산은 아님)
    """
    with connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT
              SUM(CASE WHEN side='SELL' THEN COALESCE(quote_qty, qty*price, 0) ELSE 0 END) AS sell_q,
              SUM(CASE WHEN side='BUY'  THEN COALESCE(quote_qty, qty*price, 0) ELSE 0 END) AS buy_q
            FROM trade_log
            WHERE ts >= ?
            """,
            (since_ts_utc,),
        ).fetchone()

    sell_q = row["sell_q"]
    buy_q = row["buy_q"]
    if sell_q is None and buy_q is None:
        return None
    return float(sell_q or 0) - float(buy_q or 0)


def _fallback_pnl_from_positions(since_ts_utc: str) -> Optional[float]:
    """
    positions 테이블은 upsert 구조라 누적 정확도는 낮음.
    최근 종료 포지션의 pnl_pct 합계를 참고용으로 사용.
    """
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT pnl_pct
            FROM positions
            WHERE status='CLOSED'
              AND exit_ts IS NOT NULL
              AND exit_ts >= ?
              AND pnl_pct IS NOT NULL
            """,
            (since_ts_utc,),
        ).fetchall()

    if not rows:
        return None
    return float(sum([r["pnl_pct"] for r in rows]))


def _next_run_kst(now_kst: datetime) -> datetime:
    # 0,3,6,9,12,15,18,21 시각에 맞춰 전송
    hour = now_kst.hour
    next_block = ((hour // REPORT_EVERY_HOURS) + 1) * REPORT_EVERY_HOURS
    if next_block >= 24:
        target = (now_kst + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        target = now_kst.replace(hour=next_block, minute=0, second=0, microsecond=0)
    return target


def send_3h_report_once() -> None:
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    now_kst = now_utc.astimezone(KST)

    since_utc = now_utc - timedelta(hours=REPORT_EVERY_HOURS)
    since_ts = _utc_str(since_utc.replace(tzinfo=None))  # DB는 UTC naive string

    entry, tp, sl = _sum_event_counts(since_ts)

    pnl_quote = _realized_pnl_from_trade_log(since_ts)
    pnl_pct = None
    pnl_note = ""

    if pnl_quote is None:
        pnl_pct = _fallback_pnl_from_positions(since_ts)
        pnl_note = " (positions 기반, 참고)"
    else:
        pnl_note = " (trade_log 기반)"

    msg_lines = [
        f"📊 3시간 리포트({now_kst.strftime('%m/%d %H:%M')} KST)",
        f"✅ 진입(ENTRY): {entry}",
        f"✅ 익절(EXIT_TP): {tp}",
        f"✅ 손절(EXIT_SL): {sl}",
    ]

    if pnl_quote is not None:
        sign = "+" if pnl_quote >= 0 else ""
        msg_lines.append(f"💰 실현손익{pnl_note}: {sign}{pnl_quote:.2f} USDT")
    elif pnl_pct is not None:
        sign = "+" if pnl_pct >= 0 else ""
        msg_lines.append(f"💰 실현손익{pnl_note}: {sign}{pnl_pct:.2f}%")
    else:
        msg_lines.append("💰 실현손익: 집계 데이터 없음")

    send_telegram_message("\n".join(msg_lines))


def start_3h_reporter_thread() -> None:
    import threading

    def loop():
        while True:
            try:
                send_3h_report_once()
            except Exception:
                pass

            now_kst = datetime.utcnow().replace(tzinfo=timezone.utc).astimezone(KST)
            nxt = _next_run_kst(now_kst)
            sleep_sec = max(10, int((nxt - now_kst).total_seconds()))
            time.sleep(sleep_sec)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
