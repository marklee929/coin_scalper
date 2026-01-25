import requests
import uuid
import math
from config.auth import build_signed_params
from config.exchange import BINANCE_BASE_URL, QUOTE_ASSET
from data.fetch_balance import fetch_active_balances
from utils.symbols import format_symbol
from utils.telegram import send_telegram_message
from utils.logger import logger


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
        return data

    err = response.json() if response.content else {"msg": response.text}
    logger.error(f"⚠️ LIMIT 주문 실패: {err}")
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
    params = {
        "symbol": format_symbol(symbol, QUOTE_ASSET),
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
        params["quantity"] = str(qty)
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
        logger.info(f"✅ MARKET {side} 주문 성공: {symbol} x{executed} @ 시장가")
        send_telegram_message(f"📈 {'매수' if side=='BUY' else '매도'} 완료 (시장가): {symbol} {executed}개 @ 시장가")
        return data

    err = response.json() if response.content else {"msg": response.text}
    logger.error(f"⚠️ MARKET 주문 실패: {err}")
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

