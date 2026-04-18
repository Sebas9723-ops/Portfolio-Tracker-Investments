"""
Investor Profile — optimal weights and metrics per profile.
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional

from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client
from app.services.market_data import get_quotes, get_risk_free_rate, get_historical_multi
from app.services.fx_service import get_fx_rates
from app.compute.portfolio_builder import build_portfolio
from app.compute.profile import compute_profile_weights, compute_profile_metrics
from app.services.exchange_classifier import get_native_currency
import pandas as pd

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileUpdate(BaseModel):
    investor_profile: str
    target_return: Optional[float] = None


@router.get("/optimal")
def get_profile_optimal(
    period: str = Query(default="2y"),
    user_id: str = Depends(get_user_id),
):
    """
    Returns optimal weights + metrics for all 3 profiles and the current portfolio,
    based on actual historical returns for the user's holdings.
    """
    db = get_admin_client()
    settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    settings = settings_res.data or {}
    base_currency = settings.get("base_currency", "USD")
    rfr = float(settings.get("risk_free_rate", 0.045))
    max_single = float(settings.get("max_single_asset", 0.40))
    target_return = float(settings.get("target_return", 0.08))
    active_profile = settings.get("investor_profile", "balanced")

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    if not positions:
        return {"profiles": {}, "current": {}, "active_profile": active_profile}

    tickers = [p["ticker"] for p in positions]
    active_tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
    if not active_tickers:
        return {"profiles": {}, "current": {}, "active_profile": active_profile}

    # Build portfolio to get current weights (only active tickers need live quotes)
    quotes = get_quotes(active_tickers)
    currencies = list(set(get_native_currency(t) for t in active_tickers))
    fx_rates = get_fx_rates(currencies, base=base_currency)
    tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
    summary = build_portfolio(positions, quotes, fx_rates, base_currency, tx_res.data or [])

    current_weights = {
        r.ticker: r.value_base / summary.total_value_base
        for r in summary.rows
        if summary.total_value_base > 0
    }

    # Historical returns
    hist = get_historical_multi(tickers, period=period)
    closes: dict[str, pd.Series] = {}
    for t, df in hist.items():
        if not df.empty:
            col = "Close" if "Close" in df.columns else df.columns[0]
            closes[t] = df[col].dropna()

    returns_df = pd.DataFrame(closes).dropna(how="all").ffill().pct_change().dropna()

    if returns_df.empty:
        return {"profiles": {}, "current": {}, "active_profile": active_profile}

    # Load Motor 1 & Motor 2 constraints per profile
    ticker_weight_rules = settings.get("ticker_weight_rules") or {}
    combination_ranges = settings.get("combination_ranges") or {}

    # Compute optimal weights for all 3 profiles
    profiles_out = {}
    for profile in ["conservative", "base", "aggressive"]:
        tr = target_return if profile == "base" else 0.08

        # Per-ticker bounds for this profile
        profile_rules = ticker_weight_rules.get(profile, {})
        per_ticker_bounds = {
            ticker: (float(rule.get("floor", 0.0)), float(rule.get("cap", 1.0)))
            for ticker, rule in profile_rules.items()
            if isinstance(rule, dict)
        } or None

        # Combination constraints for this profile
        combo_constraints = combination_ranges.get(profile, []) or None

        w = compute_profile_weights(returns_df, profile, rfr, tr, max_single, per_ticker_bounds, combo_constraints)  # type: ignore[arg-type]
        m = compute_profile_metrics(returns_df, w, rfr)
        profiles_out[profile] = {"weights": w, "metrics": m}

    # Current portfolio metrics
    current_metrics = compute_profile_metrics(returns_df, current_weights, rfr)

    return {
        "profiles": profiles_out,
        "current": {"weights": current_weights, "metrics": current_metrics},
        "active_profile": active_profile,
        "target_return": target_return,
        "tickers": tickers,
        "period": period,
    }


@router.put("")
def update_profile(body: ProfileUpdate, user_id: str = Depends(get_user_id)):
    """Persist investor_profile (and optionally target_return) to user_settings."""
    db = get_admin_client()

    # Fetch current settings first
    res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    current = res.data or {}

    update_data = {"user_id": user_id, "investor_profile": body.investor_profile}
    if body.target_return is not None:
        update_data["target_return"] = body.target_return

    # Merge with existing settings so upsert doesn't wipe other fields
    merged = {**current, **update_data}
    db.table("user_settings").upsert(merged, on_conflict="user_id").execute()

    return {"investor_profile": body.investor_profile, "target_return": body.target_return}
