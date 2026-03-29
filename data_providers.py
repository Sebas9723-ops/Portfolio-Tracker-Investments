"""
Private-mode market data providers.

Routes US equities to Alpaca (IEX, free tier) and EU/UK tickers to yfinance.
Falls back to yfinance automatically for any Alpaca failures.

Public app continues using utils.py (yfinance only) — this module is never
imported in the public path.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import streamlit as st

from utils import get_prices as _yf_prices, get_historical_data as _yf_hist


# ── Exchange classification ────────────────────────────────────────────────────

def _exchange(ticker: str) -> str:
    t = str(ticker).upper().strip()
    if t.endswith(".L"):
        return "LSE"
    if t.endswith(".DE"):
        return "XETRA"
    if "." in t:
        return "OTHER_EU"
    return "US"


# (display label, delay_minutes)
_SOURCE_META: dict[str, tuple[str, int]] = {
    "US":       ("Live · Alpaca",    0),
    "XETRA":    ("~15 min · XETRA", 15),
    "LSE":      ("~15 min · LSE",   15),
    "OTHER_EU": ("~15 min · Yahoo", 15),
}


def data_source_labels(tickers: list[str]) -> dict[str, str]:
    """Return a badge label for each ticker, e.g. {"VOO": "Live · Alpaca"}."""
    return {
        t: _SOURCE_META.get(_exchange(t), ("~15 min · Yahoo", 15))[0]
        for t in tickers
    }


# ── Alpaca client (cached per session) ────────────────────────────────────────

@st.cache_resource
def _alpaca_client():
    from alpaca.data.historical import StockHistoricalDataClient
    return StockHistoricalDataClient(
        api_key=st.secrets["alpaca"]["api_key"],
        secret_key=st.secrets["alpaca"]["secret_key"],
    )


# ── Alpaca: latest prices ──────────────────────────────────────────────────────

def _alpaca_latest_prices(tickers: list[str]) -> dict[str, float]:
    if not tickers:
        return {}
    try:
        from alpaca.data.requests import StockLatestTradeRequest
        req = StockLatestTradeRequest(symbol_or_symbols=tickers, feed="iex")
        trades = _alpaca_client().get_stock_latest_trade(req)
        return {t: float(trades[t].price) for t in tickers if t in trades}
    except Exception:
        return {}


# ── Alpaca: historical daily bars ─────────────────────────────────────────────

_PERIOD_DAYS = {"1y": 365, "2y": 730, "5y": 1825}


def _alpaca_historical(tickers: list[str], period: str = "2y") -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    try:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        days = _PERIOD_DAYS.get(period, 730)
        start = datetime.now(timezone.utc) - timedelta(days=days)

        req = StockBarsRequest(
            symbol_or_symbols=tickers,
            timeframe=TimeFrame.Day,
            start=start,
            feed="iex",
            adjustment="all",
        )
        raw = _alpaca_client().get_stock_bars(req).df

        if raw.empty:
            return pd.DataFrame()

        raw = raw.reset_index()
        raw["timestamp"] = (
            pd.to_datetime(raw["timestamp"]).dt.tz_convert(None).dt.normalize()
        )
        pivot = raw.pivot_table(
            index="timestamp", columns="symbol", values="close", aggfunc="last"
        )
        pivot.index.name = None
        pivot.columns.name = None
        return pivot.sort_index().ffill().dropna(how="all")

    except Exception:
        return pd.DataFrame()


# ── Public interface ───────────────────────────────────────────────────────────

def get_prices_private(tickers: list[str]) -> dict[str, float]:
    """
    Drop-in replacement for utils.get_prices() in private mode.
    US tickers → Alpaca IEX; EU/UK → yfinance; yfinance fallback if Alpaca fails.
    """
    us = [t for t in tickers if _exchange(t) == "US"]
    non_us = [t for t in tickers if _exchange(t) != "US"]

    prices: dict[str, float] = {}

    if us:
        prices.update(_alpaca_latest_prices(us))
        failed = [t for t in us if not np.isfinite(prices.get(t, np.nan))]
        if failed:
            prices.update(_yf_prices(failed))

    if non_us:
        prices.update(_yf_prices(non_us))

    return prices


def get_historical_data_private(tickers: list[str], period: str = "2y") -> pd.DataFrame:
    """
    Drop-in replacement for utils.get_historical_data() in private mode.
    US tickers → Alpaca IEX daily bars; EU/UK → yfinance; yfinance fallback if Alpaca fails.
    """
    us = [t for t in tickers if _exchange(t) == "US"]
    non_us = [t for t in tickers if _exchange(t) != "US"]

    frames: list[pd.DataFrame] = []

    if us:
        alpaca_df = _alpaca_historical(us, period)
        if not alpaca_df.empty:
            frames.append(alpaca_df)
        failed = [t for t in us if alpaca_df.empty or t not in alpaca_df.columns]
        if failed:
            yf_fb = _yf_hist(failed, period)
            if not yf_fb.empty:
                frames.append(yf_fb)

    if non_us:
        yf_df = _yf_hist(non_us, period)
        if not yf_df.empty:
            frames.append(yf_df)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, axis=1)
    combined = combined.loc[:, ~combined.columns.duplicated()]
    return combined.sort_index().ffill().dropna(how="all")


def load_market_data_private(tickers: list[str], period: str = "2y"):
    """
    Drop-in replacement for app_core.load_market_data_with_proxies() in private mode.
    Applies PROXY_TICKER_MAP then routes by exchange.
    """
    from app_core import PROXY_TICKER_MAP

    source_tickers: list[str] = []
    seen: set[str] = set()
    for t in tickers:
        src = PROXY_TICKER_MAP.get(t, t)
        if src not in seen:
            source_tickers.append(src)
            seen.add(src)

    raw_prices = get_prices_private(source_tickers)
    raw_hist = get_historical_data_private(source_tickers, period)

    mapped_prices: dict[str, float] = {}
    mapped_hist = pd.DataFrame(index=raw_hist.index) if not raw_hist.empty else pd.DataFrame()

    for t in tickers:
        src = PROXY_TICKER_MAP.get(t, t)

        pv = raw_prices.get(src)
        if isinstance(pv, (int, float)) and pd.notna(pv):
            mapped_prices[t] = float(pv)

        if not raw_hist.empty and src in raw_hist.columns:
            mapped_hist[t] = pd.to_numeric(raw_hist[src], errors="coerce")

    return mapped_prices, mapped_hist
