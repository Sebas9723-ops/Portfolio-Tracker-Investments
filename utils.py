import pandas as pd
import yfinance as yf


def _extract_last_close(df: pd.DataFrame):
    if df is None or df.empty:
        return None

    if "Close" not in df.columns:
        return None

    close = pd.to_numeric(df["Close"], errors="coerce").dropna()

    if close.empty:
        return None

    return float(close.iloc[-1])


def get_prices(tickers):
    prices = {}

    for ticker in tickers:
        try:
            df = yf.download(
                ticker,
                period="7d",
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            )

            prices[ticker] = _extract_last_close(df)

        except Exception:
            prices[ticker] = None

    return prices


def get_historical_data(tickers, period="1y"):
    series_dict = {}

    for ticker in tickers:
        try:
            df = yf.download(
                ticker,
                period=period,
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            )

            if df is None or df.empty or "Close" not in df.columns:
                continue

            close = pd.to_numeric(df["Close"], errors="coerce").dropna()

            if not close.empty:
                series_dict[ticker] = close.rename(ticker)

        except Exception:
            continue

    if not series_dict:
        return pd.DataFrame()

    historical = pd.concat(series_dict, axis=1)
    historical = historical.sort_index().ffill().dropna(how="all")

    return historical