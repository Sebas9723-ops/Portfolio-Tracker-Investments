from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class QuoteResponse(BaseModel):
    ticker: str
    price: float
    change: Optional[float] = None
    change_pct: Optional[float] = None
    prev_close: Optional[float] = None
    currency: str = "USD"
    source: str = "finnhub"
    delay_minutes: int = 0
    as_of: Optional[datetime] = None


class HistoricalBar(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None


class HistoricalResponse(BaseModel):
    ticker: str
    period: str
    currency: str
    bars: list[HistoricalBar]


class MarketStatus(BaseModel):
    us_open: bool
    london_open: bool
    frankfurt_open: bool
    next_open_utc: Optional[str] = None
