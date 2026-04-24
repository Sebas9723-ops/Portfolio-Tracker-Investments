from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class PositionCreate(BaseModel):
    ticker: str
    name: Optional[str] = None
    shares: float
    avg_cost_native: Optional[float] = None
    currency: str = "USD"
    market: str = "US"


class PositionUpdate(BaseModel):
    name: Optional[str] = None
    shares: Optional[float] = None
    avg_cost_native: Optional[float] = None
    currency: Optional[str] = None


class Position(PositionCreate):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime


class PortfolioRow(BaseModel):
    ticker: str
    name: str
    shares: float
    currency: str          # exchange currency (EUR for .DE, GBP for .L, USD for US)
    cost_currency: str = "USD"  # currency in which avg_cost_native was entered
    market: str
    price_native: float
    price_base: float
    fx_rate: float
    avg_cost_native: Optional[float]
    avg_cost_base: Optional[float]
    value_native: float
    value_base: float
    invested_base: Optional[float]
    unrealized_pnl: Optional[float]
    unrealized_pnl_pct: Optional[float]
    weight: float
    change_pct_1d: Optional[float]
    data_source: str = "yfinance"


class PortfolioSummary(BaseModel):
    rows: list[PortfolioRow]
    total_value_base: float
    total_invested_base: Optional[float]
    total_unrealized_pnl: Optional[float]
    total_unrealized_pnl_pct: Optional[float]
    total_day_change_base: Optional[float]
    base_currency: str
    as_of: datetime
    pending_tickers: list[str] = []  # positions with 0 shares (watchlist/pre-buy)


class CashBalance(BaseModel):
    currency: str
    amount: float
    account_name: Optional[str] = None
    value_base: Optional[float] = None


class SnapshotCreate(BaseModel):
    snapshot_date: Optional[str] = None  # ISO date; defaults to today
    notes: Optional[str] = None


class Snapshot(BaseModel):
    id: str
    snapshot_date: str
    total_value_usd: Optional[float]
    total_value_base: Optional[float]
    invested_base: Optional[float] = None
    base_currency: str
    created_at: datetime
