from fastapi import APIRouter, Query
from app.models.market import QuoteResponse, HistoricalResponse, MarketStatus
from app.services.market_data import get_quotes, get_historical, get_risk_free_rate
from app.services import cache
from datetime import datetime, timezone, time as dtime

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/quotes", response_model=dict[str, QuoteResponse])
def quotes(tickers: str = Query(..., description="Comma-separated ticker list")):
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    return get_quotes(ticker_list)


@router.get("/quote/{ticker}", response_model=QuoteResponse)
def single_quote(ticker: str):
    results = get_quotes([ticker])
    return results.get(ticker, QuoteResponse(ticker=ticker, price=0, currency="USD"))


@router.get("/historical/{ticker}", response_model=HistoricalResponse)
def historical(ticker: str, period: str = Query(default="1y")):
    return get_historical(ticker, period)


@router.get("/risk-free-rate")
def risk_free_rate():
    return {"rate": get_risk_free_rate()}


@router.get("/status", response_model=MarketStatus)
def market_status():
    now_utc = datetime.now(timezone.utc)
    weekday = now_utc.weekday()
    t = now_utc.time()

    def between(start_h, start_m, end_h, end_m):
        return dtime(start_h, start_m) <= t <= dtime(end_h, end_m)

    us_open = weekday < 5 and between(13, 30, 20, 0)
    london_open = weekday < 5 and between(8, 0, 16, 30)
    frankfurt_open = weekday < 5 and between(8, 0, 16, 30)

    return MarketStatus(us_open=us_open, london_open=london_open, frankfurt_open=frankfurt_open)


# ── Market Breadth ────────────────────────────────────────────────────────────

@router.get("/breadth")
def market_breadth():
    """
    Market breadth indicators: advancing/declining, new highs/lows,
    % stocks above SMA50/200, and relative volume leaders.
    """
    import yfinance as yf
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor

    cached = cache.get("market_breadth")
    if cached:
        return cached

    # Breadth ETF proxies
    BREADTH_TICKERS = {
        "^NYAD":  "NYSE Advance/Decline",
        "^NAHGH": "NYSE New Highs",
        "^NALOW": "NYSE New Lows",
        "^SPXADP": "S&P Adv/Dec",
    }

    # Large cap universe for breadth calculation
    UNIVERSE = [
        "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","BRK-B","JPM","V",
        "WMT","XOM","LLY","ORCL","MA","UNH","AVGO","COST","HD","PG",
        "JNJ","BAC","NFLX","ABBV","KO","CSCO","CVX","CRM","AMD","MCD",
        "ACN","PEP","TMO","LIN","ABT","MRK","WFC","DIS","TXN","NEE",
        "INTC","QCOM","HON","IBM","GE","CAT","AMGN","BA","SPGI","GS",
        "BLK","MMM","RTX","LOW","UNP","AXP","ISRG","ADI","BKNG","GILD",
        "MDLZ","SYK","VRTX","DE","NOW","PANW","AMAT","MU","LRCX","KLAC",
        "REGN","ZTS","BSX","ADI","PLD","WELL","O","PSA","AMT","CCI",
        "SPY","QQQ","IWM","GLD","TLT","HYG","EEM","VNQ","XLK","XLF",
    ]

    def _fetch_ticker_breadth(t: str) -> dict:
        try:
            info = yf.Ticker(t).info or {}
            price = float(info.get("regularMarketPrice") or info.get("currentPrice") or 0)
            sma50 = float(info.get("fiftyDayAverage") or 0)
            sma200 = float(info.get("twoHundredDayAverage") or 0)
            vol = float(info.get("volume") or info.get("regularMarketVolume") or 0)
            avg_vol = float(info.get("averageVolume") or info.get("averageDailyVolume10Day") or 1)
            chg_pct = float(info.get("regularMarketChangePercent") or 0)
            return {
                "ticker": t,
                "price": price,
                "change_pct": chg_pct,
                "above_sma50": price > sma50 if price > 0 and sma50 > 0 else None,
                "above_sma200": price > sma200 if price > 0 and sma200 > 0 else None,
                "rel_vol": round(vol / avg_vol, 2) if avg_vol > 0 and vol > 0 else None,
                "vol": vol,
                "avg_vol": avg_vol,
            }
        except Exception:
            return {"ticker": t, "price": 0, "change_pct": 0, "above_sma50": None, "above_sma200": None, "rel_vol": None}

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(_fetch_ticker_breadth, UNIVERSE[:60]))

    valid = [r for r in results if r["price"] > 0]
    n = len(valid)

    advancing = sum(1 for r in valid if r["change_pct"] > 0)
    declining = sum(1 for r in valid if r["change_pct"] < 0)
    above_sma50 = sum(1 for r in valid if r["above_sma50"] is True)
    above_sma200 = sum(1 for r in valid if r["above_sma200"] is True)

    # Relative volume leaders
    rel_vol_leaders = sorted(
        [r for r in valid if r["rel_vol"] and r["rel_vol"] > 1.5],
        key=lambda x: -(x["rel_vol"] or 0)
    )[:10]

    top_gainers = sorted(valid, key=lambda x: -x["change_pct"])[:5]
    top_losers = sorted(valid, key=lambda x: x["change_pct"])[:5]

    result = {
        "universe_size": n,
        "advancing": advancing,
        "declining": declining,
        "unchanged": n - advancing - declining,
        "advancing_pct": round(advancing / n * 100, 1) if n > 0 else 0,
        "declining_pct": round(declining / n * 100, 1) if n > 0 else 0,
        "above_sma50": above_sma50,
        "above_sma50_pct": round(above_sma50 / n * 100, 1) if n > 0 else 0,
        "above_sma200": above_sma200,
        "above_sma200_pct": round(above_sma200 / n * 100, 1) if n > 0 else 0,
        "rel_vol_leaders": rel_vol_leaders,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }

    cache.set("market_breadth", result, ttl=300)  # 5 min cache
    return result


# ── Stock Screener ─────────────────────────────────────────────────────────────

_SCREENER_UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","JPM","V","WMT",
    "XOM","LLY","ORCL","MA","UNH","AVGO","COST","HD","PG","JNJ",
    "BAC","NFLX","ABBV","KO","CSCO","CVX","CRM","AMD","MCD","ACN",
    "PEP","TMO","LIN","ABT","MRK","WFC","DIS","TXN","NEE","INTC",
    "QCOM","HON","IBM","GE","CAT","AMGN","BA","SPGI","GS","BLK",
    "MMM","RTX","LOW","UNP","AXP","ISRG","BKNG","GILD","MDLZ","SYK",
    "VRTX","DE","NOW","PANW","AMAT","MU","LRCX","KLAC","REGN","ZTS",
    "BSX","PLD","WELL","AMT","CCI","UBER","ABNB","SHOP","SQ","PYPL",
    "SNAP","TWLO","DDOG","NET","CRWD","ZS","SNOW","PLTR","RBLX","COIN",
    "F","GM","RIVN","NIO","LCID","HOOD","SOFI","AFRM","UPST","OPEN",
    "SPY","QQQ","IWM","VTI","VOO","GLD","TLT","HYG","EEM","VNQ",
    "XLK","XLF","XLV","XLC","XLY","XLP","XLI","XLE","XLU","XLRE",
]


@router.get("/screener")
def stock_screener(
    sector: str = Query(default=""),
    min_pe: float = Query(default=0),
    max_pe: float = Query(default=0),
    min_div_yield: float = Query(default=0),
    min_roe: float = Query(default=0),
    max_debt_eq: float = Query(default=0),
    min_market_cap_b: float = Query(default=0),
    max_market_cap_b: float = Query(default=0),
    min_rel_vol: float = Query(default=0),
    sort_by: str = Query(default="marketCap"),
    sort_desc: bool = Query(default=True),
    limit: int = Query(default=50),
    tickers: str = Query(default=""),
):
    """
    Screen stocks by fundamental/technical criteria.
    Uses a universe of popular stocks + any user-provided tickers.
    """
    from concurrent.futures import ThreadPoolExecutor

    cache_key = f"screener:{sector}:{min_pe}:{max_pe}:{min_div_yield}:{min_roe}:{max_debt_eq}:{min_market_cap_b}:{max_market_cap_b}:{min_rel_vol}:{sort_by}:{sort_desc}:{tickers}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    custom = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else []
    universe = list(dict.fromkeys(custom + _SCREENER_UNIVERSE))[:150]

    import yfinance as yf

    def _fetch(t: str) -> dict | None:
        try:
            info = yf.Ticker(t).info or {}
            price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
            if price <= 0:
                return None

            pe = info.get("trailingPE")
            fpe = info.get("forwardPE")
            mc = info.get("marketCap") or 0
            div_yield = float(info.get("dividendYield") or 0) * 100
            roe = float(info.get("returnOnEquity") or 0) * 100
            debt_eq = float(info.get("debtToEquity") or 0)
            pb = info.get("priceToBook")
            gm = info.get("grossMargins")
            pm = info.get("profitMargins")
            beta = info.get("beta")
            vol = float(info.get("volume") or info.get("regularMarketVolume") or 0)
            avg_vol = float(info.get("averageVolume") or 1)
            rel_vol = round(vol / avg_vol, 2) if avg_vol > 0 else None
            chg = float(info.get("regularMarketChangePercent") or 0)
            sma50 = float(info.get("fiftyDayAverage") or 0)
            sma200 = float(info.get("twoHundredDayAverage") or 0)
            dist_sma50 = round((price / sma50 - 1) * 100, 2) if sma50 > 0 else None
            dist_sma200 = round((price / sma200 - 1) * 100, 2) if sma200 > 0 else None
            short_float = float(info.get("shortPercentOfFloat") or 0) * 100
            rec = info.get("recommendationKey") or ""
            target = info.get("targetMeanPrice")

            return {
                "ticker": t,
                "name": info.get("longName") or info.get("shortName") or t,
                "sector": info.get("sector") or info.get("category") or "",
                "price": round(price, 2),
                "change_pct": round(chg, 2),
                "market_cap": mc,
                "market_cap_b": round(mc / 1e9, 2) if mc else None,
                "pe": round(float(pe), 1) if pe else None,
                "forward_pe": round(float(fpe), 1) if fpe else None,
                "pb": round(float(pb), 2) if pb else None,
                "div_yield": round(div_yield, 2),
                "roe": round(roe, 1),
                "gross_margin": round(float(gm) * 100, 1) if gm else None,
                "profit_margin": round(float(pm) * 100, 1) if pm else None,
                "debt_equity": round(debt_eq, 1),
                "beta": round(float(beta), 2) if beta else None,
                "rel_vol": rel_vol,
                "dist_sma50": dist_sma50,
                "dist_sma200": dist_sma200,
                "short_float": round(short_float, 1),
                "recommendation": rec,
                "target_price": round(float(target), 2) if target else None,
                "upside": round((float(target) / price - 1) * 100, 1) if target and price > 0 else None,
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=20) as pool:
        rows = [r for r in pool.map(_fetch, universe) if r is not None]

    # Apply filters
    def _passes(r: dict) -> bool:
        if sector and sector.lower() not in (r["sector"] or "").lower():
            return False
        if min_pe > 0 and (r["pe"] is None or r["pe"] < min_pe):
            return False
        if max_pe > 0 and (r["pe"] is None or r["pe"] > max_pe):
            return False
        if min_div_yield > 0 and r["div_yield"] < min_div_yield:
            return False
        if min_roe > 0 and r["roe"] < min_roe:
            return False
        if max_debt_eq > 0 and r["debt_equity"] > max_debt_eq:
            return False
        if min_market_cap_b > 0 and (r["market_cap_b"] is None or r["market_cap_b"] < min_market_cap_b):
            return False
        if max_market_cap_b > 0 and (r["market_cap_b"] is None or r["market_cap_b"] > max_market_cap_b):
            return False
        if min_rel_vol > 0 and (r["rel_vol"] is None or r["rel_vol"] < min_rel_vol):
            return False
        return True

    filtered = [r for r in rows if _passes(r)]

    # Sort
    def _sort_key(r: dict):
        v = r.get(sort_by)
        if v is None:
            return float("-inf") if sort_desc else float("inf")
        return float(v)

    filtered.sort(key=_sort_key, reverse=sort_desc)
    result = {"rows": filtered[:limit], "total": len(filtered), "universe_fetched": len(rows)}
    cache.set(cache_key, result, ttl=1800)  # 30min cache
    return result


# ── Upcoming Earnings Calendar ─────────────────────────────────────────────────

@router.get("/earnings-calendar")
def earnings_calendar(days_ahead: int = Query(default=14)):
    """Upcoming earnings for a universe of popular stocks (next N days)."""
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date, timedelta

    cache_key = f"earnings_cal:{days_ahead}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    WATCH_LIST = [
        "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","JPM","V","WMT",
        "XOM","LLY","ORCL","MA","UNH","AVGO","COST","HD","PG","JNJ",
        "BAC","NFLX","ABBV","KO","CSCO","CVX","CRM","AMD","MCD","ACN",
        "INTC","QCOM","HON","IBM","GE","CAT","AMGN","BA","GS","BLK",
        "RTX","LOW","UNP","AXP","ISRG","BKNG","GILD","SYK","VRTX","DE",
        "NOW","PANW","AMAT","MU","LRCX","KLAC","REGN","ZTS","UBER","SHOP",
    ]

    def _fetch_earnings(t: str) -> dict | None:
        try:
            info = yf.Ticker(t).info or {}
            ed_raw = info.get("earningsTimestamp") or info.get("earningsDate")
            if ed_raw is None:
                return None
            if isinstance(ed_raw, (list, tuple)):
                ed_raw = ed_raw[0]
            if isinstance(ed_raw, (int, float)):
                from datetime import datetime
                ed = datetime.utcfromtimestamp(ed_raw).date()
            else:
                try:
                    ed = date.fromisoformat(str(ed_raw)[:10])
                except Exception:
                    return None
            if ed < today or ed > cutoff:
                return None
            return {
                "ticker": t,
                "name": info.get("shortName") or info.get("longName") or t,
                "earnings_date": str(ed),
                "eps_estimate": info.get("epsForward"),
                "revenue_estimate": info.get("revenueEstimate"),
                "market_cap_b": round(float(info.get("marketCap") or 0) / 1e9, 1),
                "sector": info.get("sector") or "",
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = [r for r in pool.map(_fetch_earnings, WATCH_LIST) if r is not None]

    results.sort(key=lambda x: x["earnings_date"])
    result = {"events": results, "days_ahead": days_ahead, "as_of": str(today)}
    cache.set(cache_key, result, ttl=3600)
    return result
