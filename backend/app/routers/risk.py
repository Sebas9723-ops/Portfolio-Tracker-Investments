from fastapi import APIRouter, Depends, Query
from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client
from app.services.market_data import get_historical_multi, get_quotes, get_risk_free_rate
from app.services.fx_service import get_fx_rates
from app.compute.portfolio_builder import build_portfolio
from app.compute.returns import build_portfolio_returns
from app.compute.risk import (
    compute_var_cvar, compute_rolling_metrics, compute_stress_tests,
    compute_correlation_matrix, compute_risk_budget, compute_fx_exposure,
)
from app.services.exchange_classifier import get_native_currency
from app.models.analytics import RiskMetrics
import pandas as pd

router = APIRouter(prefix="/api/risk", tags=["risk"])


def _load_portfolio_data(user_id: str):
    db = get_admin_client()
    settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    settings = settings_res.data or {}
    base_currency = settings.get("base_currency", "USD")

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
    quotes = get_quotes(tickers) if tickers else {}
    currencies = list(set(get_native_currency(t) for t in tickers)) if tickers else []
    fx_rates = get_fx_rates(currencies, base=base_currency) if currencies else {}

    tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
    summary = build_portfolio(positions, quotes, fx_rates, base_currency, tx_res.data or [])
    return summary, tickers, settings


@router.get("/var")
def var_endpoint(
    confidence: float = Query(default=0.95),
    period: str = Query(default="2y"),
    user_id: str = Depends(get_user_id),
):
    summary, tickers, settings = _load_portfolio_data(user_id)
    if not tickers:
        return {}
    weights = {r.ticker: r.weight / 100 for r in summary.rows}
    hist = get_historical_multi(tickers, period=period)
    port_returns = build_portfolio_returns(hist, weights)
    return compute_var_cvar(port_returns, confidence, summary.total_value_base)


@router.get("/rolling")
def rolling_endpoint(
    window: int = Query(default=63),
    period: str = Query(default="2y"),
    user_id: str = Depends(get_user_id),
):
    summary, tickers, settings = _load_portfolio_data(user_id)
    if not tickers:
        return []
    weights = {r.ticker: r.weight / 100 for r in summary.rows}
    rfr = settings.get("risk_free_rate", get_risk_free_rate())
    hist = get_historical_multi(tickers, period=period)
    port_returns = build_portfolio_returns(hist, weights)
    return compute_rolling_metrics(port_returns, window, rfr)


@router.get("/stress-test")
def stress_test(user_id: str = Depends(get_user_id)):
    summary, _, _ = _load_portfolio_data(user_id)
    weights = {r.ticker: r.weight / 100 for r in summary.rows}
    return compute_stress_tests(weights, summary.total_value_base)


@router.get("/correlation")
def correlation(period: str = Query(default="1y"), user_id: str = Depends(get_user_id)):
    _, tickers, _ = _load_portfolio_data(user_id)
    if not tickers:
        return {"tickers": [], "matrix": []}
    hist = get_historical_multi(tickers, period=period)
    return compute_correlation_matrix(hist, tickers)


@router.get("/fx-exposure")
def fx_exposure(user_id: str = Depends(get_user_id)):
    summary, _, settings = _load_portfolio_data(user_id)
    base_currency = settings.get("base_currency", "USD")
    rows = [r.model_dump() for r in summary.rows]
    return compute_fx_exposure(rows, base_currency)


@router.get("/budget")
def risk_budget(period: str = Query(default="1y"), user_id: str = Depends(get_user_id)):
    summary, tickers, _ = _load_portfolio_data(user_id)
    if not tickers:
        return {}
    weights = {r.ticker: r.weight / 100 for r in summary.rows}
    hist = get_historical_multi(tickers, period=period)
    ticker_returns = {}
    for t, df in hist.items():
        if not df.empty:
            col = "Close" if "Close" in df.columns else df.columns[0]
            ticker_returns[t] = df[col].pct_change().dropna()
    return compute_risk_budget(ticker_returns, weights)
