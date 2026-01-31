from config.exchange import QUOTE_ASSET


def format_symbol(symbol: str, quote_asset: str = QUOTE_ASSET) -> str:
    base = symbol.upper()
    quote = quote_asset.upper()
    return base if base.endswith(quote) else f"{base}{quote}"
