from fastapi import APIRouter, Depends, Query
from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client
from app.services.market_data import get_quotes, get_risk_free_rate, get_historical_multi
from app.services.fx_service import get_fx_rates
from app.compute.portfolio_builder import build_portfolio
from app.compute.rebalancing import build_rebalancing_table, compute_target_weights_from_drift
from app.compute.optimization import optimize_max_sharpe
from app.compute.profile import compute_profile_weights
from app.services.exchange_classifier import get_native_currency
from app.models.analytics import RebalancingRow
import pandas as pd

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
    investor_profile = settings.get("investor_profile", "balanced")
    target_return = float(settings.get("target_return", 0.08))
    rfr = float(settings.get("risk_free_rate", 0.045))
    max_single = float(settings.get("max_single_asset", 0.40))

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

    # Use profile-driven target weights when a recognized profile is active
    profile_map = {"conservative": "conservative", "base": "base", "aggressive": "aggressive"}
    if investor_profile in profile_map:
        try:
            hist = get_historical_multi(tickers, period="2y")
            closes: dict[str, pd.Series] = {}
            for t, df in hist.items():
                if not df.empty:
                    col = "Close" if "Close" in df.columns else df.columns[0]
                    closes[t] = df[col].dropna()
            returns_df = pd.DataFrame(closes).dropna(how="all").ffill().pct_change().dropna()
            if not returns_df.empty:
                target_weights = compute_profile_weights(
                    returns_df,
                    profile_map[investor_profile],  # type: ignore[arg-type]
                    rfr,
                    target_return,
                    max_single,
                )
            else:
                target_weights = compute_target_weights_from_drift(rows_dicts, threshold)
        except Exception:
            target_weights = compute_target_weights_from_drift(rows_dicts, threshold)
    else:
        target_weights = compute_target_weights_from_drift(rows_dicts, threshold)

    return build_rebalancing_table(
        portfolio_rows=rows_dicts,
        target_weights=target_weights,
        total_value=summary.total_value_base,
        contribution=contribution,
        tc_model=tc_model,
        threshold=threshold,
    )


@router.get("/required-for-max-sharpe")
def required_for_max_sharpe(
    period: str = Query(default="2y"),
    max_single_asset: float = Query(default=0.40),
    user_id: str = Depends(get_user_id),
):
    """
    Computes the minimum cash contribution needed to reach Max Sharpe weights
    without selling any existing positions.

    Returns:
      - required_contribution: minimum cash to add
      - max_sharpe_weights: {ticker: weight}
      - buy_plan: {ticker: {buy_value, buy_pct_of_contribution}}
    """
    db = get_admin_client()
    settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    settings = settings_res.data or {}
    base_currency = settings.get("base_currency", "USD")

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    if not positions:
        return {"required_contribution": 0, "max_sharpe_weights": {}, "buy_plan": {}}

    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
    quotes = get_quotes(tickers)
    currencies = list(set(get_native_currency(t) for t in tickers))
    fx_rates = get_fx_rates(currencies, base=base_currency)

    tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
    summary = build_portfolio(positions, quotes, fx_rates, base_currency, tx_res.data or [])

    # Get Max Sharpe weights
    hist = get_historical_multi(tickers, period=period)
    closes: dict[str, pd.Series] = {}
    for t, df in hist.items():
        if not df.empty:
            col = "Close" if "Close" in df.columns else df.columns[0]
            closes[t] = df[col].dropna()

    returns_df = pd.DataFrame(closes).dropna(how="all").ffill().pct_change().dropna()
    rfr = get_risk_free_rate()

    # Apply per-ticker fixed-weight rules from user settings
    rules = settings.get("ticker_weight_rules") or {}
    per_ticker_bounds = {}
    for ticker, rule in rules.items():
        if isinstance(rule, dict) and rule.get("mode") == "fixed":
            w = float(rule.get("weight", 0.0))
            per_ticker_bounds[ticker] = (w, w)

    ms_weights = optimize_max_sharpe(returns_df, rfr, max_single_asset, per_ticker_bounds or None)

    if not ms_weights:
        return {"required_contribution": 0, "max_sharpe_weights": {}, "buy_plan": {}}

    # Current values per ticker
    current_values = {r.ticker: r.value_base for r in summary.rows}
    total_value = summary.total_value_base

    # Minimum contribution = max(v_i / w_i*) - V for all overweight tickers
    required = 0.0
    for ticker, w in ms_weights.items():
        if w > 0:
            v = current_values.get(ticker, 0.0)
            implied_total = v / w  # total portfolio size at which this ticker is exactly on target
            required = max(required, implied_total - total_value)

    required = max(0.0, round(required, 2))
    total_new = total_value + required

    # Buy plan: how to allocate the required contribution
    buy_plan = {}
    for ticker, w in ms_weights.items():
        target_value = w * total_new
        current_v = current_values.get(ticker, 0.0)
        buy_value = max(0.0, target_value - current_v)
        buy_plan[ticker] = {
            "buy_value": round(buy_value, 2),
            "buy_pct": round(buy_value / required * 100, 2) if required > 0 else 0.0,
            "target_weight": round(w * 100, 2),
            "current_weight": round(current_v / total_value * 100, 2) if total_value > 0 else 0.0,
        }

    return {
        "required_contribution": required,
        "max_sharpe_weights": {t: round(w * 100, 2) for t, w in ms_weights.items()},
        "buy_plan": buy_plan,
        "total_value": total_value,
        "total_after": round(total_new, 2),
    }
