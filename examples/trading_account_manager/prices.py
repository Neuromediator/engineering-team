FIXED_SHARE_PRICES: dict[str, float] = {
    "AAPL": 150.00,
    "TSLA": 250.00,
    "GOOGL": 2800.00,
}

def get_share_price(symbol: str) -> float:
    normalized = symbol.upper().strip()
    if normalized not in FIXED_SHARE_PRICES:
        raise ValueError(f"Unknown symbol: {symbol}")
    return FIXED_SHARE_PRICES[normalized]
