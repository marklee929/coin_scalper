def calc_order_quote(available_quote: float,
                     alloc_pct: float,
                     max_open_positions: int,
                     reserve_quote: float) -> float:
    tradable = max(0.0, available_quote * alloc_pct - reserve_quote)
    if max_open_positions <= 0:
        return 0.0
    return tradable / max_open_positions
