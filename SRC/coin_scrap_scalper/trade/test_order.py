import json
import time
from trade.order_executor import buy_limit, sell_limit, buy_market, sell_market, sell_market_all

symbol = "SHIB"        # ✅ 고정된 테스트 심볼
# 테스트용 파라미터
test_price = 10000        # 테스트용 낮은 가격 (지정가 매수 실패 유도)
test_qty = 0.01        # 소량 수량
test_amount = 5000       # 시장가 매수용 금액

def test_orders():
    print(f"\n--- {symbol} 테스트 시작 ---")

    # 지정가 매수 테스트
    print("🟦 지정가 매수 테스트")
    buy_limit(symbol, price=test_price, qty=test_qty)
    time.sleep(1)

    # 지정가 매도 테스트
    print("🟥 지정가 매도 테스트")
    sell_limit(symbol, price=test_price * 2, qty=test_qty)
    time.sleep(1)

    # 시장가 매수 테스트
    #print("🟩 시장가 매수 테스트")
    #buy_market(symbol, amount=test_amount)
    #time.sleep(1)

    # 시장가 매도 테스트
    print("🟨 시장가 매도 테스트")
    sell_market(symbol, qty=259067.3575)
    time.sleep(1)

    # 시장가 전체 매도 테스트
    print("🟨 시장가 매도 테스트")
    sell_market_all(symbol)
    time.sleep(1)

    print(f"✅ {symbol} 테스트 완료\n")

if __name__ == "__main__":
    test_orders()
