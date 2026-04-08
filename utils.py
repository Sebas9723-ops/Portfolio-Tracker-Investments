from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytz
import streamlit as st
import yfinance as yf


@st.cache_data(ttl=300, show_spinner=False)
def get_prices(tickers: list[str]) -> dict[str, float]:
    if not tickers:
        return {}

    close_df = _download_close_frame(
        tickers=tickers,
        period="5d",
        interval="1h",
    )

    prices: dict[str, float] = {}
    for ticker in tickers:
        if ticker in close_df.columns:
            series = pd.to_numeric(close_df[ticker], errors="coerce").dropna()
            prices[ticker] = float(series.iloc[-1]) if not series.empty else np.nan
        else:
            prices[ticker] = np.nan

    return prices


@st.cache_data(ttl=7200, show_spinner=False)
def get_historical_data(tickers: list[str], period: str = "2y") -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()

    close_df = _download_close_frame(
        tickers=tickers,
        period=period,
        interval="1d",
    )

    if close_df.empty:
        return pd.DataFrame()

    close_df = close_df.sort_index()
    close_df = close_df.ffill()
    close_df = close_df.dropna(how="all")

    return close_df


def _download_close_frame(
    tickers: list[str],
    period: str,
    interval: str,
) -> pd.DataFrame:
    clean_tickers = [str(t).strip().upper() for t in tickers if str(t).strip()]
    clean_tickers = list(dict.fromkeys(clean_tickers))

    if not clean_tickers:
        return pd.DataFrame()

    combined = pd.DataFrame()

    bulk_df = _safe_download_bulk(
        tickers=clean_tickers,
        period=period,
        interval=interval,
    )
    bulk_close = _extract_close_frame(bulk_df, clean_tickers)

    if not bulk_close.empty:
        combined = bulk_close.copy()

    missing = [t for t in clean_tickers if t not in combined.columns or pd.to_numeric(combined[t], errors="coerce").dropna().empty]

    if missing:
        for ticker in missing:
            single_df = _safe_download_single(
                ticker=ticker,
                period=period,
                interval=interval,
            )
            single_close = _extract_close_frame(single_df, [ticker])

            if not single_close.empty and ticker in single_close.columns:
                combined[ticker] = pd.to_numeric(single_close[ticker], errors="coerce")

    if combined.empty:
        return pd.DataFrame()

    for ticker in clean_tickers:
        if ticker not in combined.columns:
            combined[ticker] = np.nan

    combined = combined[clean_tickers].copy()
    combined.index = pd.to_datetime(combined.index, errors="coerce")
    combined = combined[~combined.index.isna()]
    combined = combined.sort_index()

    try:
        if getattr(combined.index, "tz", None) is not None:
            combined.index = combined.index.tz_localize(None)
    except Exception:
        pass

    combined = combined.apply(pd.to_numeric, errors="coerce")

    return combined


def _safe_download_bulk(
    tickers: list[str],
    period: str,
    interval: str,
) -> pd.DataFrame:
    try:
        data = yf.download(
            tickers=tickers,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="column",
        )
        if isinstance(data, pd.DataFrame):
            return data
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _safe_download_single(
    ticker: str,
    period: str,
    interval: str,
) -> pd.DataFrame:
    try:
        data = yf.download(
            tickers=ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="column",
        )
        if isinstance(data, pd.DataFrame):
            return data
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _extract_close_frame(data: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    if data is None or data.empty:
        return pd.DataFrame()

    wanted = [str(t).strip().upper() for t in tickers if str(t).strip()]
    wanted = list(dict.fromkeys(wanted))

    if isinstance(data.columns, pd.MultiIndex):
        level0 = [str(x) for x in data.columns.get_level_values(0)]
        level1 = [str(x) for x in data.columns.get_level_values(1)]

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
                str(col[-1]).upper() if isinstance(col, tuple) else str(col).upper()
                for col in close_df.columns
            ]
        else:
            close_df.columns = [str(col).upper() for col in close_df.columns]

        close_df = close_df.apply(pd.to_numeric, errors="coerce")

        existing = [ticker for ticker in wanted if ticker in close_df.columns]
        if existing:
            return close_df[existing].copy()

        return close_df.copy()

    flat_cols = [str(c) for c in data.columns]

    if "Adj Close" in flat_cols:
        series = pd.to_numeric(data["Adj Close"], errors="coerce")
    elif "Close" in flat_cols:
        series = pd.to_numeric(data["Close"], errors="coerce")
    else:
        numeric_df = data.apply(pd.to_numeric, errors="coerce")
        if len(wanted) == 1 and not numeric_df.empty:
            if numeric_df.shape[1] >= 1:
                first_col = numeric_df.columns[0]
                return numeric_df[[first_col]].rename(columns={first_col: wanted[0]})
        return pd.DataFrame()

    if len(wanted) == 1:
        return series.to_frame(name=wanted[0])

    return pd.DataFrame()


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