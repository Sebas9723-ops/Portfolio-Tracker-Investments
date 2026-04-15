from fastapi import APIRouter, Depends, Query
from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client
from app.services.market_data import get_quotes, get_risk_free_rate
from app.services.fx_service import get_fx_rates
from app.compute.portfolio_builder import build_portfolio
from app.compute.rebalancing import build_rebalancing_table, compute_target_weights_from_drift
from app.services.exchange_classifier import get_native_currency
from app.models.analytics import RebalancingRow

router = APIRouter(prefix="/api/rebalancing", tags=["rebalancing"])


@router.get("/suggestions", response_model=list[RebalancingRow])
def suggestions(
    contribution: float = Query(default=0.0),
    tc_model: str = Query(default="broker"),
    user_id: str = Depends(get_user_id),
):
    db = get_admin_client()
    settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    settings = settings_res.data or {}
    base_currency = settings.get("base_currency", "USD")
    threshold = float(settings.get("rebalancing_threshold", 0.05))

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    if not positions:
        return []

    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
    quotes = get_quotes(tickers)
    currencies = list(set(get_native_currency(t) for t in tickers))
    fx_rates = get_fx_rates(currencies, base=base_currency)

    tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
    summary = build_portfolio(positions, quotes, fx_rates, base_currency, tx_res.data or [])

    rows_dicts = [r.model_dump() for r in summary.rows]
    target_weights = compute_target_weights_from_drift(rows_dicts, threshold)

    return build_rebalancing_table(
        portfolio_rows=rows_dicts,
        target_weights=target_weights,
        total_value=summary.total_value_base,
        contribution=contribution,
        tc_model=tc_model,
        threshold=threshold,
    )
