from __future__ import annotations

import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime
import pytz


def get_prices(tickers: list[str]) -> dict[str, float]:
    if not tickers:
        return {}

    prices = {}

    for ticker in tickers:
        try:
            data = yf.download(
                ticker,
                period="5d",
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            if data is None or data.empty:
                prices[ticker] = np.nan
                continue

            if "Adj Close" in data.columns:
                val = data["Adj Close"].dropna()
            elif "Close" in data.columns:
                val = data["Close"].dropna()
            else:
                prices[ticker] = np.nan
                continue

            prices[ticker] = float(val.iloc[-1]) if not val.empty else np.nan
        except Exception:
            prices[ticker] = np.nan

    return prices


def get_historical_data(
    tickers: list[str],
    period: str = "2y",
    interval: str = "1d",
) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()

    try:
        data = yf.download(
            tickers,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="column",
        )
    except Exception:
        return pd.DataFrame()

    if data is None or data.empty:
        return pd.DataFrame()

    if len(tickers) == 1:
        ticker = tickers[0]
        if "Adj Close" in data.columns:
            series = pd.to_numeric(data["Adj Close"], errors="coerce")
        elif "Close" in data.columns:
            series = pd.to_numeric(data["Close"], errors="coerce")
        else:
            return pd.DataFrame()
        return pd.DataFrame({ticker: series}).dropna(how="all")

    if "Adj Close" in data.columns:
        out = data["Adj Close"].copy()
    elif "Close" in data.columns:
        out = data["Close"].copy()
    else:
        return pd.DataFrame()

    if isinstance(out, pd.Series):
        out = out.to_frame()

    for ticker in tickers:
        if ticker not in out.columns:
            out[ticker] = np.nan

    out = out[tickers]
    out = out.apply(pd.to_numeric, errors="coerce")
    return out.dropna(how="all")


def get_market_times() -> dict[str, tuple[str, str]]:
    markets = {
        "New York": "America/New_York",
        "London": "Europe/London",
        "Frankfurt": "Europe/Berlin",
        "Zurich": "Europe/Zurich",
        "Tokyo": "Asia/Tokyo",
        "Shanghai": "Asia/Shanghai",
        "Singapore": "Asia/Singapore",
        "Bogota": "America/Bogota",
        "Sydney": "Australia/Sydney",
    }

    output = {}
    for name, tz_string in markets.items():
        tz = pytz.timezone(tz_string)
        now = datetime.now(tz)
        output[name] = (now.strftime("%H:%M:%S"), now.strftime("%a %d %b"))
    return output