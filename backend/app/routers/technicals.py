import numpy as np
import pandas as pd
import yfinance as yf
from fastapi import APIRouter, Query
from app.services import cache
from app.services.exchange_classifier import yf_ticker

router = APIRouter(prefix="/api/technicals", tags=["technicals"])


def _compute_rsi(closes: pd.Series, window: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = -delta.clip(upper=0).rolling(window).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _compute_macd(closes: pd.Series):
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist


def _compute_bb(closes: pd.Series, window: int = 20, num_std: float = 2.0):
    sma = closes.rolling(window).mean()
    std = closes.rolling(window).std()
    return sma + num_std * std, sma, sma - num_std * std


@router.get("/{ticker}")
def technicals(ticker: str, period: str = Query(default="1y")):
    key = f"technicals:{ticker}:{period}"
    cached = cache.get(key)
    if cached:
        return cached

    yft = yf_ticker(ticker)
    raw = yf.download(yft, period=period, interval="1d", auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.droplevel(1)
    raw = raw.dropna(how="all").ffill()
    if raw.empty:
        return {"ticker": ticker, "bars": [], "indicators": {}}

    c = raw["Close"]
    rsi = _compute_rsi(c)
    macd, signal, macd_hist = _compute_macd(c)
    bb_upper, bb_mid, bb_lower = _compute_bb(c)
    sma20 = c.rolling(20).mean()
    sma50 = c.rolling(50).mean()
    sma200 = c.rolling(200).mean()

    def s(series: pd.Series):
        return [{"date": str(d.date()), "value": round(float(v), 4) if not np.isnan(v) else None}
                for d, v in series.items()]

    bars = []
    for dt, row in raw.iterrows():
        bars.append({
            "date": str(dt.date()),
            "open": round(float(row.get("Open", 0)), 4),
            "high": round(float(row.get("High", 0)), 4),
            "low": round(float(row.get("Low", 0)), 4),
            "close": round(float(row.get("Close", 0)), 4),
            "volume": float(row.get("Volume", 0)) if "Volume" in row else None,
        })

    result = {
        "ticker": ticker,
        "bars": bars,
        "indicators": {
            "sma20": s(sma20), "sma50": s(sma50), "sma200": s(sma200),
            "bb_upper": s(bb_upper), "bb_mid": s(bb_mid), "bb_lower": s(bb_lower),
            "rsi": s(rsi),
            "macd": s(macd), "macd_signal": s(signal), "macd_hist": s(macd_hist),
        },
    }
    cache.set(key, result, ttl=600)
    return result
