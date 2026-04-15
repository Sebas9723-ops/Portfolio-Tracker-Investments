from fastapi import APIRouter, Query
from app.models.market import QuoteResponse, HistoricalResponse, MarketStatus
from app.services.market_data import get_quotes, get_historical, get_risk_free_rate
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
    weekday = now_utc.weekday()  # 0=Mon 6=Sun
    t = now_utc.time()

    def between(start_h, start_m, end_h, end_m):
        return dtime(start_h, start_m) <= t <= dtime(end_h, end_m)

    us_open = weekday < 5 and between(13, 30, 20, 0)
    london_open = weekday < 5 and between(8, 0, 16, 30)
    frankfurt_open = weekday < 5 and between(8, 0, 16, 30)

    return MarketStatus(us_open=us_open, london_open=london_open, frankfurt_open=frankfurt_open)
