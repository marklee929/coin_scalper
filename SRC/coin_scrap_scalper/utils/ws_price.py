import json
import random
import threading
import time
import re
from typing import List, Optional, Dict

from utils.logger import logger
from utils.symbols import format_symbol
from config.exchange import QUOTE_ASSET

try:
    import websocket  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    websocket = None

_PRICE_CACHE: Dict[str, float] = {}
_VALID_SYMBOL_RE = re.compile(r"^[A-Z0-9]+$")


def _build_stream_url(symbols: List[str]) -> Optional[str]:
    if not symbols:
        return None
    valid_streams = []
    for s in symbols:
        full = format_symbol(s, QUOTE_ASSET).upper()
        if not _VALID_SYMBOL_RE.match(full):
            logger.warning(f"WS skip invalid symbol: {full}")
            continue
        valid_streams.append(f"{full.lower()}@miniTicker")
    if not valid_streams:
        return None
    streams = "/".join(valid_streams)
    return f"wss://stream.binance.com:9443/stream?streams={streams}"


def get_price(symbol: str) -> Optional[float]:
    return _PRICE_CACHE.get(symbol.upper())


class MiniTickerStream:
    def __init__(self, symbols: List[str]):
        self._symbols = sorted({s.upper() for s in symbols})
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ws = None

    def update_symbols(self, symbols: List[str]) -> None:
        new_symbols = sorted({s.upper() for s in symbols})
        if new_symbols == self._symbols:
            return
        self._symbols = new_symbols
        self.restart()

    def start(self) -> None:
        if websocket is None:
            logger.warning("websocket-client not installed; WS price feed disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def restart(self) -> None:
        self.stop()
        time.sleep(1)
        self.start()

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            url = _build_stream_url(self._symbols)
            if not url:
                time.sleep(5)
                continue
            logger.info(f"WS connect: {url}")

            def on_message(_, message: str):
                try:
                    payload = json.loads(message)
                    data = payload.get("data", payload)
                    symbol = data.get("s")
                    price = data.get("c")
                    if symbol and price is not None:
                        _PRICE_CACHE[symbol.upper()] = float(price)
                except Exception:
                    return

            def on_error(_, error):
                logger.warning(f"WS error: {error}")

            def on_close(*_):
                logger.info("WS closed, reconnecting...")

            self._ws = websocket.WebSocketApp(
                url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )

            try:
                self._ws.run_forever(ping_interval=30, ping_timeout=10)
                backoff = 1.0
            except Exception as e:
                logger.warning(f"WS run_forever error: {e}")
            sleep_sec = min(backoff, 60.0) + random.random()
            time.sleep(sleep_sec)
            backoff = min(backoff * 2.0, 60.0)


_GLOBAL_STREAM: Optional[MiniTickerStream] = None


def start_price_stream(symbols: List[str]) -> MiniTickerStream:
    global _GLOBAL_STREAM
    if _GLOBAL_STREAM is None:
        _GLOBAL_STREAM = MiniTickerStream(symbols)
        _GLOBAL_STREAM.start()
    else:
        _GLOBAL_STREAM.update_symbols(symbols)
    return _GLOBAL_STREAM
