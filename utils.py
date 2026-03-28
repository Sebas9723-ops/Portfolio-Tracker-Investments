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

    try:
        data = yf.download(
            tickers=tickers,
            period="5d",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="column",
        )
    except Exception:
        return {ticker: np.nan for ticker in tickers}

    close_df = _extract_close_frame(data, tickers)

    if close_df.empty:
        return {ticker: np.nan for ticker in tickers}

    for ticker in tickers:
        if ticker in close_df.columns:
            series = pd.to_numeric(close_df[ticker], errors="coerce").dropna()
            prices[ticker] = float(series.iloc[-1]) if not series.empty else np.nan
        else:
            prices[ticker] = np.nan

    return prices


def get_historical_data(tickers: list[str], period: str = "2y") -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()

    try:
        data = yf.download(
            tickers=tickers,
            period=period,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="column",
        )
    except Exception:
        return pd.DataFrame()

    close_df = _extract_close_frame(data, tickers)

    if close_df.empty:
        return pd.DataFrame()

    close_df = close_df.sort_index().ffill().dropna(how="all")
    return close_df


def _extract_close_frame(data: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    if data is None or data.empty:
        return pd.DataFrame()

    if isinstance(data.columns, pd.MultiIndex):
        level0 = list(data.columns.get_level_values(0))
        level1 = list(data.columns.get_level_values(1))

        close_df = pd.DataFrame()

        if "Adj Close" in level0:
            close_df = data["Adj Close"].copy()
        elif "Close" in level0:
            close_df = data["Close"].copy()
        elif "Adj Close" in level1:
            close_df = data.xs("Adj Close", axis=1, level=1).copy()
        elif "Close" in level1:
            close_df = data.xs("Close", axis=1, level=1).copy()

        if isinstance(close_df, pd.Series):
            close_df = close_df.to_frame()

        if isinstance(close_df.columns, pd.MultiIndex):
            close_df.columns = [
                col[-1] if isinstance(col, tuple) else col
                for col in close_df.columns
            ]

        close_df = close_df.apply(pd.to_numeric, errors="coerce")

        existing = [ticker for ticker in tickers if ticker in close_df.columns]
        if existing:
            close_df = close_df[existing]

        return close_df

    if "Adj Close" in data.columns:
        series = pd.to_numeric(data["Adj Close"], errors="coerce")
    elif "Close" in data.columns:
        series = pd.to_numeric(data["Close"], errors="coerce")
    else:
        return pd.DataFrame()

    if len(tickers) == 1:
        return series.to_frame(name=tickers[0])

    return series.to_frame(name="VALUE")


def compute_returns_and_covariance(price_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if price_df is None or price_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    returns = price_df.pct_change().dropna(how="all")
    if returns.empty:
        return pd.DataFrame(), pd.DataFrame()

    cov = returns.cov() * 252
    return returns, cov


def get_market_times() -> dict[str, tuple[str, str]]:
    markets = {
        "New York": "America/New_York",
        "London": "Europe/London",
        "Frankfurt": "Europe/Berlin",
        "Zurich": "Europe/Zurich",
        "Tokyo": "Asia/Tokyo",
        "Shanghai": "Asia/Shanghai",
        "Singapore": "Asia/Singapore",
        "Bogotá": "America/Bogota",
        "Sydney": "Australia/Sydney",
    }

    output = {}

    for name, tz_name in markets.items():
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
        output[name] = (
            now.strftime("%H:%M:%S"),
            now.strftime("%a %d %b"),
        )

    return output