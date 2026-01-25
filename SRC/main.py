import time
import json
import sys
import argparse
from strategy.hold_watch import start_scalping_thread
from strategy.stage1_filter import stage1_scan
from utils.logger import logger  # 로거 사용
from storage.repo import fetch_open_positions, save_snapshot
from config.exchange import MAX_OPEN_POSITIONS
from utils.ws_price import start_price_stream


def load_target_symbols(path: str = "config/target_currency.json") -> list:
    """
    JSON 파일에서 대상 코인 심볼 목록을 로드합니다.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        symbols = data.get("target_currencies", [])
        logger.info(f"대상 심볼 목록 로드 완료: {symbols}")
        return symbols
    except Exception as e:
        logger.error(f"⚠️ 대상 코인 목록 불러오기 실패: {e}")
        return []

def parse_symbols_arg(raw: str) -> list:
    symbols = [s.strip().upper() for s in (raw or "").split(",") if s.strip()]
    return symbols

def load_symbols(args) -> list:
    # 1) CLI 지정 심볼 (디버그용)
    if args.symbols:
        symbols = parse_symbols_arg(args.symbols)
        logger.info(f"CLI 심볼 사용: {symbols}")
        return symbols

    # 2) 기존 파일 기반 (디버그용)
    if args.use_target_file:
        symbols = load_target_symbols()
        logger.info(f"target_currency.json 사용: {symbols}")
        return symbols

    # 3) 기본: 전체 유니버스 스캔 → 1차 필터 통과 리스트
    open_positions = fetch_open_positions()
    if len(open_positions) >= MAX_OPEN_POSITIONS:
        logger.info("⚠️ max 포지션 도달: 스캔 중지, watch-only 모드")
        symbols = open_positions
        return symbols

    candidates = stage1_scan(exclude_symbols=set(open_positions))
    symbols = [c["symbol"] for c in candidates]
    if args.max_watch and args.max_watch > 0:
        symbols = symbols[:args.max_watch]
    logger.info(f"1차 필터 통과 심볼 수: {len(symbols)}")
    return symbols


ACTIVE_WATCHLIST_KIND = "ACTIVE_WATCHLIST"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", help="comma-separated symbols for debug (e.g., BTC,ETH,XRP)")
    parser.add_argument("--use-target-file", action="store_true", help="use config/target_currency.json")
    parser.add_argument("--max-watch", type=int, default=0, help="limit number of symbols to watch")
    args = parser.parse_args()

    target_symbols = load_symbols(args)
    open_positions = fetch_open_positions()
    for sym in open_positions:
        if sym not in target_symbols:
            target_symbols.append(sym)
    if not target_symbols:
        logger.error("⚠️ 대상 심볼 없음 → 종료 프로그램")
        sys.exit(1)

    active_symbols = set(target_symbols)
    save_snapshot(ACTIVE_WATCHLIST_KIND, sorted(active_symbols), min_interval_sec=0, force=True)

    logger.info(f"✅ 감시 시작할 심볼 목록: {', '.join(sorted(active_symbols))}")

    # start websocket price stream for watchlist symbols
    ws_stream = start_price_stream(list(active_symbols))

    started_symbols = set()
    for symbol in sorted(active_symbols):
        start_scalping_thread(symbol)
        started_symbols.add(symbol)
        logger.info(f"📌 감시 스레드 시작: {symbol}")

    last_mode = None
    last_open_positions = set(open_positions)

    # 메인 스레드는 로그만 찍고 주기적으로 대기
    while True:
        time.sleep(60)  # 1분 대기
        try:
            open_positions = fetch_open_positions()
            open_set = set(open_positions)

            if args.symbols or args.use_target_file:
                mode = "MANUAL"
                desired = set(target_symbols) | open_set
            else:
                if len(open_positions) >= MAX_OPEN_POSITIONS:
                    mode = "WATCH"
                    desired = open_set
                else:
                    mode = "SCAN"
                    need_scan = (last_mode != "SCAN") or (open_set != last_open_positions)
                    if need_scan:
                        candidates = stage1_scan(exclude_symbols=open_set)
                        symbols = [c["symbol"] for c in candidates]
                        if args.max_watch and args.max_watch > 0:
                            symbols = symbols[:args.max_watch]
                        desired = open_set | set(symbols)
                    else:
                        desired = set(active_symbols) | open_set

            if desired and desired != active_symbols:
                save_snapshot(ACTIVE_WATCHLIST_KIND, sorted(desired), min_interval_sec=0, force=True)
                ws_stream.update_symbols(list(desired))
                for sym in sorted(desired - started_symbols):
                    start_scalping_thread(sym)
                    started_symbols.add(sym)
                    logger.info(f"📌 감시 스레드 시작: {sym}")
                active_symbols = set(desired)
                logger.info(f"ACTIVE watchlist 갱신: {sorted(active_symbols)} (mode={mode})")

            last_mode = mode
            last_open_positions = open_set
        except Exception as e:
            logger.warning(f"WS watchlist 갱신 실패: {e}")
        logger.debug("메인 스레드 대기 중...")
