import time
import json
import sys
import argparse
from strategy.hold_watch import start_scalping_thread
from strategy.stage1_filter import stage1_scan
from utils.logger import logger  # 로거 사용


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
    candidates = stage1_scan()
    symbols = [c["symbol"] for c in candidates]
    if args.max_watch and args.max_watch > 0:
        symbols = symbols[:args.max_watch]
    logger.info(f"1차 필터 통과 심볼 수: {len(symbols)}")
    return symbols

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", help="comma-separated symbols for debug (e.g., BTC,ETH,XRP)")
    parser.add_argument("--use-target-file", action="store_true", help="use config/target_currency.json")
    parser.add_argument("--max-watch", type=int, default=0, help="limit number of symbols to watch")
    args = parser.parse_args()

    target_symbols = load_symbols(args)
    if not target_symbols:
        logger.error("🚫 대상 심볼 없음 → 종료 프로그램")
        sys.exit(1)

    logger.info(f"🚀 감시 시작할 심볼 목록: {', '.join(target_symbols)}")

    for symbol in target_symbols:
        start_scalping_thread(symbol)
        logger.info(f"스케일핑 스레드 시작: {symbol}")

    # 메인 스레드는 로그만 남기고 주기적으로 대기
    while True:
        time.sleep(60)  # 1분 대기
        logger.debug("메인 스레드 대기 중...")
