import requests
import uuid
import math
import time
from decimal import Decimal, ROUND_DOWN
from config.auth import build_signed_params
from config.exchange import BINANCE_BASE_URL, QUOTE_ASSET
from data.fetch_balance import fetch_active_balances
from utils.symbols import format_symbol
from utils.telegram import send_telegram_message
from utils.logger import logger
from storage.repo import append_trade, append_event

_LOT_CACHE = {}
_MIN_NOTIONAL_CACHE = {}
_LOT_CACHE_TS = 0.0
_LOT_CACHE_TTL_SEC = 6 * 3600


def _extract_lot(symbol_pair: str, symbols):
    if not symbols:
        return None
    target = None
    for s in symbols:
        if s.get("symbol") == symbol_pair:
            target = s
            break
    if not target:
        return None
    filters = target.get("filters", [])
    for f in filters:
        if f.get("filterType") == "LOT_SIZE":
            return f
    return None


def _extract_min_notional(symbol_pair: str, symbols):
    if not symbols:
        return None
    target = None
    for s in symbols:
        if s.get("symbol") == symbol_pair:
            target = s
            break
    if not target:
        return None
    filters = target.get("filters", [])
    for f in filters:
        if f.get("filterType") == "MIN_NOTIONAL":
            return f
    return None


def _refresh_lot_cache_full() -> bool:
    global _LOT_CACHE_TS
    try:
        res = requests.get(f"{BINANCE_BASE_URL}/api/v3/exchangeInfo", timeout=8)
        if res.status_code != 200:
            return False
        data = res.json()
        updated = 0
        for s in data.get("symbols", []):
            symbol = s.get("symbol")
            if not symbol:
                continue
            lot = _extract_lot(symbol, [s])
            if not lot:
                continue
            min_qty = lot.get("minQty")
            step = lot.get("stepSize")
            if not min_qty or not step:
                continue
            if Decimal(str(step)) <= 0 or Decimal(str(min_qty)) <= 0:
                continue
            _LOT_CACHE[symbol] = (str(min_qty), str(step))
            mn = _extract_min_notional(symbol, [s])
            if mn:
                val = mn.get("minNotional")
                if val:
                    _MIN_NOTIONAL_CACHE[symbol] = str(val)
            updated += 1
        if updated:
            _LOT_CACHE_TS = time.time()
        return updated > 0
    except Exception as e:
        logger.warning(f"LOT_SIZE 전체 캐시 갱신 실패: {e}")
        return False


def _get_lot_size(symbol_pair: str):
    cached = _LOT_CACHE.get(symbol_pair)
    if cached:
        return cached

    try:
        res = requests.get(f"{BINANCE_BASE_URL}/api/v3/exchangeInfo", params={"symbol": symbol_pair}, timeout=5)
        if res.status_code == 200:
            data = res.json()
            symbols = data.get("symbols", [])
            lot = _extract_lot(symbol_pair, symbols)
            mn = _extract_min_notional(symbol_pair, symbols)
            if mn:
                val = mn.get("minNotional")
                if val:
                    _MIN_NOTIONAL_CACHE[symbol_pair] = str(val)
        else:
            lot = None
        if not lot:
            now = time.time()
            if not _LOT_CACHE or (now - _LOT_CACHE_TS) > _LOT_CACHE_TTL_SEC:
                _refresh_lot_cache_full()
            return _LOT_CACHE.get(symbol_pair)
        if not lot:
            return None
        min_qty = lot.get("minQty")
        step = lot.get("stepSize")
        if not min_qty or not step:
            return None
        if Decimal(str(step)) <= 0 or Decimal(str(min_qty)) <= 0:
            return None
        _LOT_CACHE[symbol_pair] = (str(min_qty), str(step))
        return _LOT_CACHE[symbol_pair]
    except Exception as e:
        logger.warning(f"LOT_SIZE 조회 실패: {symbol_pair} {e}")
        return None


def _adjust_qty(symbol_pair: str, qty: float):
    lot = _get_lot_size(symbol_pair)
    if not lot:
        return None
    min_qty, step = lot
    d_qty = Decimal(str(qty))
    d_step = Decimal(step)
    if d_step <= 0:
        return None
    d_min = Decimal(min_qty)
    if d_qty < d_min:
        return None
    adj = (d_qty // d_step) * d_step
    if adj < d_min:
        return None
    precision = abs(d_step.as_tuple().exponent)
    adj_str = format(adj.quantize(Decimal(10) ** -precision, rounding=ROUND_DOWN), "f")
    return adj_str


def get_lot_size(symbol: str):
    symbol_pair = format_symbol(symbol, QUOTE_ASSET)
    lot = _get_lot_size(symbol_pair)
    if not lot:
        return None
    min_qty, step = lot
    return Decimal(min_qty), Decimal(step)


def get_symbol_filters(symbol: str):
    symbol_pair = format_symbol(symbol, QUOTE_ASSET)
    lot = _get_lot_size(symbol_pair)
    if not lot:
        return None
    min_qty, step = lot
    min_notional = _MIN_NOTIONAL_CACHE.get(symbol_pair)
    d_min_notional = Decimal(min_notional) if min_notional else None
    return Decimal(min_qty), Decimal(step), d_min_notional


def place_limit_order(symbol: str, price: float, qty: float, side: str = "BUY", retry: int = 0):
    """
    지정가 주문 (LIMIT)
    """
    url = f"{BINANCE_BASE_URL}/api/v3/order"
    params = {
        "symbol": format_symbol(symbol, QUOTE_ASSET),
        "side": side.upper(),
        "type": "LIMIT",
        "timeInForce": "GTC",
        "price": str(price),
        "quantity": str(qty),
        "newClientOrderId": str(uuid.uuid4())[:16]
    }
    try:
        headers, signed = build_signed_params(params)
    except Exception as e:
        logger.error(f"❌ 인증 파라미터 생성 실패: {e}")
        return None
    response = requests.post(url, headers=headers, params=signed)

    if response.status_code in (200, 201):
        data = response.json()
        logger.info(f"✅ LIMIT {side} 주문 성공: {symbol} @ {price} x {qty}")
        send_telegram_message(
            f"📈 {'매수' if side=='BUY' else '매도'} 완료 (지정가): {symbol} {qty}개 @ {price} {QUOTE_ASSET}"
        )
        append_trade(
            symbol=symbol.upper(),
            side=side.upper(),
            qty=float(qty),
            price=float(price),
            quote_qty=float(price) * float(qty),
            order_id=str(data.get("orderId")) if isinstance(data, dict) else None,
            reason="LIMIT",
            raw=data,
        )
        return data

    err = response.json() if response.content else {"msg": response.text}
    logger.error(f"⚠️ LIMIT 주문 실패: {err}")
    append_event(level="ERROR", type="ORDER_ERROR", symbol=symbol.upper(), message=str(err))
    return None


def buy_limit(symbol: str, price: float, qty: float):
    return place_limit_order(symbol, price, qty, side="BUY")


def sell_limit(symbol: str, price: float, qty: float):
    return place_limit_order(symbol, price, qty, side="SELL")


def place_market_order(symbol: str,
                       amount: float = None,
                       qty: float = None,
                       side: str = "BUY",
                       limit_price: float = None,
                       retry: int = 0):
    """
    시장가 주문 (MARKET)
    """
    url = f"{BINANCE_BASE_URL}/api/v3/order"
    symbol_pair = format_symbol(symbol, QUOTE_ASSET)
    params = {
        "symbol": symbol_pair,
        "side": side.upper(),
        "type": "MARKET"
    }
    if side.upper() == "BUY":
        if amount is None:
            raise ValueError("시장가 매수 시 amount를 지정해야 합니다.")
        params["quoteOrderQty"] = str(math.floor(amount * 0.9995))  # 수수료 고려
    else:
        if qty is None:
            raise ValueError("시장가 매도 시 qty를 지정해야 합니다.")
        adj_qty = _adjust_qty(symbol_pair, qty)
        if adj_qty is None:
            logger.error(f"MARKET SELL 수량 보정 실패(LOT_SIZE): {symbol_pair} qty={qty}")
            append_event(level="ERROR", type="ORDER_ERROR", symbol=symbol.upper(), message="LOT_SIZE adjust failed or too small")
            return None
        params["quantity"] = adj_qty
    if limit_price is not None:
        params["price"] = str(limit_price)

    logger.info(f"📈 MARKET {side} 주문: {symbol} {amount} {QUOTE_ASSET}, params {params}")

    try:
        headers, signed = build_signed_params(params)
    except Exception as e:
        logger.error(f"❌ 인증 파라미터 생성 실패: {e}")
        return None
    response = requests.post(url, headers=headers, params=signed)

    if response.status_code in (200, 201):
        data = response.json()
        executed = data.get("executedQty") or data.get("origQty")
        quote_qty = data.get("cummulativeQuoteQty") or data.get("quoteOrderQty")
        fee = None
        fee_asset = None
        fills = data.get("fills", []) if isinstance(data, dict) else []
        if fills:
            try:
                fee = sum(float(f.get("commission", 0)) for f in fills)
                fee_asset = fills[0].get("commissionAsset")
            except Exception:
                fee = None
        logger.info(f"✅ MARKET {side} 주문 성공: {symbol} x{executed} @ 시장가")
        send_telegram_message(f"📈 {'매수' if side=='BUY' else '매도'} 완료 (시장가): {symbol} {executed}개 @ 시장가")
        append_trade(
            symbol=symbol.upper(),
            side=side.upper(),
            qty=float(executed) if executed else 0.0,
            price=None,
            quote_qty=float(quote_qty) if quote_qty else None,
            fee=fee,
            fee_asset=fee_asset,
            order_id=str(data.get("orderId")) if isinstance(data, dict) else None,
            reason="MARKET",
            raw=data,
        )
        return data

    err = response.json() if response.content else {"msg": response.text}
    logger.error(f"⚠️ MARKET 주문 실패: {err}")
    append_event(level="ERROR", type="ORDER_ERROR", symbol=symbol.upper(), message=str(err))
    return None


def buy_market(symbol: str, amount: float, limit_price: float = None):
    return place_market_order(symbol, amount=amount, side="BUY", limit_price=limit_price)


def sell_market(symbol: str, qty: float, limit_price: float = None):
    return place_market_order(symbol, qty=qty, side="SELL", limit_price=limit_price)

def sell_market_all(symbol: str):
    balances, _ = fetch_active_balances()
    for b in balances:
        if b["symbol"].upper() == symbol.upper():
            qty = float(b["available"])
            if qty > 0:
                return sell_market(symbol, qty=qty)
    logger.warning(f"❌ {symbol} 전량 매도 실패: 보유 수량 없음")
    return None

