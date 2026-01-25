# ✅ 안전하게 숫자 변환
def safe_int(val, default=0):
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default