"""
Shared helper for loading a user's full portfolio data.
Used by risk, rebalancing, and other routers that need the complete portfolio build.
"""
from app.db.supabase_client import get_admin_client
from app.services.market_data import get_quotes
from app.services.fx_service import get_fx_rates
from app.compute.portfolio_builder import build_portfolio
from app.services.exchange_classifier import get_native_currency
from app.models.portfolio import PortfolioSummary


def load_portfolio_data(user_id: str) -> tuple[PortfolioSummary, list[str], dict]:
    """
    Load settings, positions, live quotes, FX rates, and transactions for a user,
    then build and return the full PortfolioSummary.

    Returns:
        (summary, tickers, settings)
        - summary: fully built PortfolioSummary with rows, total_value_base, etc.
        - tickers: list of tickers with shares > 0
        - settings: raw user_settings dict from DB
    """
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
