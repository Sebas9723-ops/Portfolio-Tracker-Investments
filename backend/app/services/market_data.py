"""
Central market data router.
- US tickers  → Finnhub (with yfinance fallback)
- EU/UK tickers → yfinance
"""
import time
import finnhub
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from app.config import get_settings
from app.models.market import QuoteResponse, HistoricalBar, HistoricalResponse
from app.services import cache
from app.services.exchange_classifier import is_us, get_native_currency, yf_ticker, get_ticker_pairs


@lru_cache
def _finnhub_client() -> finnhub.Client:
    return finnhub.Client(api_key=get_settings().FINNHUB_API_KEY)


# ── Quotes ────────────────────────────────────────────────────────────────────

def get_quote(ticker: str) -> QuoteResponse:
    cached = cache.get(f"quote:{ticker}")
    if cached:
        return cached
    result = _fetch_quote(ticker)
    cache.set(f"quote:{ticker}", result, ttl=cache.TTL_QUOTES)
    return result


def get_quotes(tickers: list[str]) -> dict[str, QuoteResponse]:
    results: dict[str, QuoteResponse] = {}
    missing: list[str] = []
    for t in tickers:
        cached = cache.get(f"quote:{t}")
        if cached:
            results[t] = cached
        else:
            missing.append(t)

    if missing:
        # Batch yfinance for EU/UK; individual Finnhub for US
        us = [t for t in missing if is_us(t)]
        non_us = [t for t in missing if not is_us(t)]

        for t in us:
            q = _fetch_quote_finnhub(t)
            cache.set(f"quote:{t}", q, ttl=cache.TTL_QUOTES)
            results[t] = q

        if non_us:
            batch = _fetch_quotes_yfinance(non_us)
            for t, q in batch.items():
                cache.set(f"quote:{t}", q, ttl=cache.TTL_QUOTES)
                results[t] = q

    return results


def _fetch_quote(ticker: str) -> QuoteResponse:
    if is_us(ticker):
        return _fetch_quote_finnhub(ticker)
    return _fetch_quote_yfinance(ticker)


def _fetch_quote_finnhub(ticker: str) -> QuoteResponse:
    try:
        fh = _finnhub_client()
        data = fh.quote(ticker)
        if data and data.get("c", 0) > 0:
            return QuoteResponse(
                ticker=ticker,
                price=data["c"],
                change=data.get("d"),
                change_pct=data.get("dp"),
                prev_close=data.get("pc"),
                currency=get_native_currency(ticker),
                source="finnhub",
                delay_minutes=0,
                as_of=datetime.fromtimestamp(data.get("t", time.time()), tz=timezone.utc),
            )
    except Exception:
        pass
    # yfinance fallback (uses proxy map internally)
    result = _fetch_quote_yfinance(ticker)
    if result.price > 0:
        return result
    # Try ticker pairs as last resort
    for pair in get_ticker_pairs(ticker):
        r = _fetch_quote_yfinance_raw(pair, original_ticker=ticker)
        if r.price > 0:
            return r
    return result


def _fetch_quote_yfinance_raw(yf_symbol: str, original_ticker: str) -> QuoteResponse:
    """Fetch a quote from yfinance using an explicit yf symbol, returning result tagged with original_ticker."""
    try:
        t = yf.Ticker(yf_symbol)
        info = t.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
        prev = getattr(info, "previous_close", None)
        if price:
            change = (price - prev) if prev else None
            change_pct = (change / prev * 100) if (prev and change is not None) else None
            return QuoteResponse(
                ticker=original_ticker,
                price=price,
                change=change,
                change_pct=change_pct,
                prev_close=prev,
                currency=get_native_currency(original_ticker),
                source="yfinance",
                delay_minutes=15,
                as_of=datetime.now(tz=timezone.utc),
            )
    except Exception:
        pass
    return QuoteResponse(
        ticker=original_ticker, price=0.0, currency=get_native_currency(original_ticker),
        source="unavailable", delay_minutes=-1,
    )


def _fetch_quote_yfinance(ticker: str) -> QuoteResponse:
    # Try the canonical yfinance symbol (handles proxy map e.g. EIMI.UK → EIMI.L)
    result = _fetch_quote_yfinance_raw(yf_ticker(ticker), original_ticker=ticker)
    if result.price > 0:
        return result
    # Try ticker pairs (e.g. IGLN.L → IGLN.UK, 8RMY.DE → 8RMY.F)
    for pair in get_ticker_pairs(ticker):
        r = _fetch_quote_yfinance_raw(yf_ticker(pair), original_ticker=ticker)
        if r.price > 0:
            return r
    return result


def _fetch_quotes_yfinance(tickers: list[str]) -> dict[str, QuoteResponse]:
    results: dict[str, QuoteResponse] = {}
    try:
        yf_map = {yf_ticker(t): t for t in tickers}
        # Use 1h interval to get the most recent price within the last hour
        data = yf.download(list(yf_map.keys()), period="5d", interval="1h",
                           auto_adjust=True, progress=False, threads=True)
        closes = data["Close"] if "Close" in data.columns else data
        # Also fetch daily data to get accurate prev_close for 1d change calculation
        daily = yf.download(list(yf_map.keys()), period="5d", interval="1d",
                            auto_adjust=True, progress=False, threads=True)
        daily_closes = daily["Close"] if "Close" in daily.columns else daily
        for yft, orig in yf_map.items():
            try:
                series = closes[yft].dropna() if yft in closes.columns else pd.Series()
                daily_series = daily_closes[yft].dropna() if yft in daily_closes.columns else pd.Series()
                if len(series) >= 1:
                    price = float(series.iloc[-1])
                    prev = float(daily_series.iloc[-2]) if len(daily_series) >= 2 else None
                    change = (price - prev) if prev else None
                    change_pct = (change / prev * 100) if (prev and change is not None) else None
                    results[orig] = QuoteResponse(
                        ticker=orig, price=price, change=change, change_pct=change_pct,
                        prev_close=prev, currency=get_native_currency(orig),
                        source="yfinance", delay_minutes=60,
                        as_of=datetime.now(tz=timezone.utc),
                    )
                else:
                    # No data in batch — try individual fetch with pair fallback
                    results[orig] = _fetch_quote_yfinance(orig)
            except Exception:
                results[orig] = _fetch_quote_yfinance(orig)
    except Exception:
        for t in tickers:
            results[t] = _fetch_quote_yfinance(t)

    # Final pass: any ticker still at price=0 → try its pairs individually
    for orig in list(results):
        if results[orig].price == 0:
            for pair in get_ticker_pairs(orig):
                r = _fetch_quote_yfinance_raw(yf_ticker(pair), original_ticker=orig)
                if r.price > 0:
                    results[orig] = r
                    break

    return results


# ── Historical ────────────────────────────────────────────────────────────────

PERIOD_DAYS = {"1m": 30, "3m": 90, "6m": 180, "1y": 365, "2y": 730, "5y": 1825}


def get_historical(ticker: str, period: str = "1y") -> HistoricalResponse:
    key = f"hist:{ticker}:{period}"
    cached = cache.get(key)
    if cached:
        return cached
    result = _fetch_historical(ticker, period)
    cache.set(key, result, ttl=cache.TTL_HISTORICAL)
    return result


def get_historical_multi(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Returns a dict of ticker → OHLCV DataFrame. Used internally by compute modules."""
    key = f"hist_multi:{','.join(sorted(tickers))}:{period}"
    cached = cache.get(key)
    if cached:
        return cached

    try:
        yf_map = {yf_ticker(t): t for t in tickers}
        raw = yf.download(list(yf_map.keys()), period=period, interval="1d",
                          auto_adjust=True, progress=False, threads=True)
        if isinstance(raw.columns, pd.MultiIndex):
            result = {}
            for yft, orig in yf_map.items():
                try:
                    df = raw.xs(yft, axis=1, level=1) if yft in raw.columns.get_level_values(1) else pd.DataFrame()
                    df = df.dropna(how="all").ffill()
                    result[orig] = df
                except Exception:
                    result[orig] = pd.DataFrame()
        else:
            # Single ticker
            orig = list(yf_map.values())[0]
            result = {orig: raw.dropna(how="all").ffill()}
    except Exception:
        result = {t: pd.DataFrame() for t in tickers}

    cache.set(key, result, ttl=cache.TTL_HISTORICAL)
    return result


def _fetch_historical(ticker: str, period: str) -> HistoricalResponse:
    try:
        yft = yf_ticker(ticker)
        raw = yf.download(yft, period=period, interval="1d",
                          auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.droplevel(1)
        raw = raw.dropna(how="all").ffill()
        bars = []
        for dt, row in raw.iterrows():
            bars.append(HistoricalBar(
                date=str(dt.date()),
                open=round(float(row.get("Open", 0)), 4),
                high=round(float(row.get("High", 0)), 4),
                low=round(float(row.get("Low", 0)), 4),
                close=round(float(row.get("Close", 0)), 4),
                volume=float(row.get("Volume", 0)) if "Volume" in row else None,
            ))
        return HistoricalResponse(
            ticker=ticker, period=period,
            currency=get_native_currency(ticker), bars=bars,
        )
    except Exception:
        return HistoricalResponse(ticker=ticker, period=period,
                                  currency=get_native_currency(ticker), bars=[])


# ── Risk-Free Rate ────────────────────────────────────────────────────────────

def get_risk_free_rate() -> float:
    cached = cache.get("rfr")
    if cached is not None:
        return cached
    try:
        t = yf.Ticker("^IRX")
        info = t.fast_info
        rate = getattr(info, "last_price", None)
        if rate and rate > 0:
            rfr = rate / 100.0
            cache.set("rfr", rfr, ttl=cache.TTL_RFR)
            return rfr
    except Exception:
        pass
    return 0.045
