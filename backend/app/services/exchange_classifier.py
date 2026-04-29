"""
Classifies tickers by exchange to route to correct data source.
Mirrors the logic from data_providers.py and app_core.py.
"""

# Tickers where yfinance symbol differs from display symbol
PROXY_TICKER_MAP: dict[str, str] = {
    # EIMI.UK is the USD share class of iShares MSCI EM IMI on LSE.
    # yfinance doesn't support .UK tickers directly; EIMI.L (GBP class)
    # tracks the same index and gives the closest available price.
    "EIMI.UK": "EIMI.L",
}

# Tickers where currency is not derivable from the suffix
TICKER_CURRENCY_OVERRIDE: dict[str, str] = {
    "IGLN.L": "USD",   # physically-backed gold, priced in USD on LSE
    "EIMI.UK": "USD",  # USD share class — price from EIMI.L proxy, treated as USD
}

# Suffixes that identify non-US exchanges
_EU_SUFFIXES = {".DE", ".PA", ".AM", ".MI", ".BR", ".VI", ".MC"}
_UK_SUFFIXES = {".L", ".UK"}
_AU_SUFFIXES = {".AX"}
_OTHER_SUFFIXES = {".TO", ".HK", ".TW", ".KS", ".NS"}

# Indexes & special
_INDEX_PREFIXES = {"^"}


def get_exchange(ticker: str) -> str:
    """Returns 'US', 'LSE', 'XETRA', 'EURONEXT', 'AU', or 'OTHER'."""
    upper = ticker.upper()
    if any(upper.startswith(p) for p in _INDEX_PREFIXES):
        return "INDEX"
    for sfx in _EU_SUFFIXES:
        if upper.endswith(sfx.upper()):
            return "XETRA" if sfx == ".DE" else "EURONEXT"
    for sfx in _UK_SUFFIXES:
        if upper.endswith(sfx.upper()):
            return "LSE"
    for sfx in _AU_SUFFIXES:
        if upper.endswith(sfx.upper()):
            return "AU"
    for sfx in _OTHER_SUFFIXES:
        if upper.endswith(sfx.upper()):
            return "OTHER"
    return "US"


def is_us(ticker: str) -> bool:
    return get_exchange(ticker) == "US"


def get_native_currency(ticker: str) -> str:
    """Best-guess native currency for a ticker."""
    if ticker in TICKER_CURRENCY_OVERRIDE:
        return TICKER_CURRENCY_OVERRIDE[ticker]
    ex = get_exchange(ticker)
    mapping = {
        "US": "USD",
        "LSE": "GBP",
        "XETRA": "EUR",
        "EURONEXT": "EUR",
        "AU": "AUD",
        "INDEX": "USD",
        "OTHER": "USD",
    }
    return mapping.get(ex, "USD")


def yf_ticker(ticker: str) -> str:
    """Return the yfinance-compatible ticker symbol (handle proxies)."""
    return PROXY_TICKER_MAP.get(ticker, ticker)


def get_ticker_pairs(ticker: str) -> list[str]:
    """
    Return alternative ticker symbols to try if the primary fails in a data provider.
    Order matters — best alternative first.
    Examples:
      EIMI.L  → [EIMI.UK]
      EIMI.UK → [EIMI.L]
      VOO.US  → [VOO]
      VOO     → [VOO.US]
      IGLN.L  → [IGLN.UK]
      8RMY.DE → [8RMY.F]   (Frankfurt mirror on yfinance)
    """
    # Already in proxy map → its target is the canonical yfinance symbol; no extra pairs needed
    if ticker in PROXY_TICKER_MAP:
        return []

    pairs: list[str] = []

    if ticker.endswith(".L"):
        pairs.append(ticker[:-2] + ".UK")
    elif ticker.endswith(".UK"):
        pairs.append(ticker[:-3] + ".L")
    elif ticker.endswith(".US"):
        pairs.append(ticker[:-3])
    elif ticker.endswith(".DE"):
        # yfinance sometimes lists German ETFs under .F (Frankfurt) instead of .DE
        pairs.append(ticker[:-3] + ".F")
    elif "." not in ticker:
        pairs.append(ticker + ".US")

    return pairs
