import pandas as pd
import yfinance as yf


def get_prices(tickers):
    prices = {}

    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).history(period="7d", interval="1d", auto_adjust=False)

            if hist is None or hist.empty or "Close" not in hist.columns:
                prices[ticker] = None
                continue

            close = pd.to_numeric(hist["Close"], errors="coerce").dropna()

            if close.empty:
                prices[ticker] = None
            else:
                prices[ticker] = float(close.iloc[-1])

        except Exception:
            prices[ticker] = None

    return prices


def get_historical_data(tickers, period="2y"):
    series = {}

    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)

            if hist is None or hist.empty or "Close" not in hist.columns:
                continue

            close = pd.to_numeric(hist["Close"], errors="coerce").dropna()

            if not close.empty:
                series[ticker] = close.rename(ticker)

        except Exception:
            continue

    if not series:
        return pd.DataFrame()

    df = pd.concat(series.values(), axis=1)
    df.columns = list(series.keys())
    df = df.sort_index().ffill().dropna(how="all")

    return df