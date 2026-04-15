"""FX rate fetching via yfinance. Mirrors build_fx_data() from app_core.py."""
import yfinance as yf
import pandas as pd
from app.services import cache

_FX_PAIR_MAP = {
    "EUR": "EURUSD=X",
    "GBP": "GBPUSD=X",
    "COP": "COPUSD=X",
    "CHF": "CHFUSD=X",
    "AUD": "AUDUSD=X",
    "USD": None,  # base
}

_FALLBACK_RATES = {"EUR": 1.10, "GBP": 1.27, "COP": 0.00025, "CHF": 1.11, "AUD": 0.65}


def get_fx_rates(currencies: list[str], base: str = "USD") -> dict[str, float]:
    """Returns {currency: rate_to_base} for all requested currencies."""
    key = f"fx:{','.join(sorted(currencies))}:{base}"
    cached = cache.get(key)
    if cached:
        return cached

    rates: dict[str, float] = {}
    pairs_needed = []
    for ccy in set(currencies):
        if ccy == base:
            rates[ccy] = 1.0
        else:
            pairs_needed.append(ccy)

    if pairs_needed:
        yf_symbols = [_FX_PAIR_MAP.get(c, f"{c}{base}=X") for c in pairs_needed if _FX_PAIR_MAP.get(c) or True]
        yf_symbols = [s for s in yf_symbols if s is not None]
        try:
            raw = yf.download(yf_symbols, period="5d", interval="1d",
                              auto_adjust=False, progress=False)
            closes = raw["Close"] if "Close" in raw.columns else raw
            if not isinstance(closes, pd.DataFrame):
                closes = closes.to_frame()
            for ccy in pairs_needed:
                sym = _FX_PAIR_MAP.get(ccy, f"{ccy}{base}=X")
                if sym and sym in closes.columns:
                    series = closes[sym].dropna()
                    if len(series) > 0:
                        # All pairs are quoted as X/USD — invert if base != USD
                        rates[ccy] = float(series.iloc[-1])
                        continue
                rates[ccy] = _FALLBACK_RATES.get(ccy, 1.0)
        except Exception:
            for ccy in pairs_needed:
                rates[ccy] = _FALLBACK_RATES.get(ccy, 1.0)

    # If base is not USD, normalize
    if base != "USD":
        base_rate = rates.get(base, 1.0)
        if base_rate != 0:
            rates = {c: r / base_rate for c, r in rates.items()}

    cache.set(key, rates, ttl=cache.TTL_FX)
    return rates


def get_fx_history(currencies: list[str], base: str = "USD", period: str = "1y") -> pd.DataFrame:
    """Returns a DataFrame of daily FX rates indexed by date."""
    pairs = [_FX_PAIR_MAP.get(c, f"{c}{base}=X") for c in currencies
             if c != base and _FX_PAIR_MAP.get(c)]
    if not pairs:
        return pd.DataFrame()
    try:
        raw = yf.download(pairs, period=period, interval="1d",
                          auto_adjust=False, progress=False)
        closes = raw["Close"] if "Close" in raw.columns else raw
        return closes.ffill().dropna(how="all")
    except Exception:
        return pd.DataFrame()
