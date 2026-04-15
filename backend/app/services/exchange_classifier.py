"""
Classifies tickers by exchange to route to correct data source.
Mirrors the logic from data_providers.py and app_core.py.
"""

# Tickers where yfinance symbol differs from display symbol
PROXY_TICKER_MAP: dict[str, str] = {}

# Tickers where currency is not derivable from the suffix
TICKER_CURRENCY_OVERRIDE: dict[str, str] = {
    "IGLN.L": "USD",   # physically-backed gold, priced in USD on LSE
    "EIMI.UK": "USD",  # USD share class of iShares MSCI EM IMI on LSE
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
