"""
Quant Analytics v2 — FastAPI router.

POST /api/analytics/quant-advanced
  Runs all 15 advanced analytics modules against the authenticated user's
  portfolio and returns a structured JSON response.

The endpoint is intentionally a POST so callers can pass optional overrides
(BL views, custom horizons, bootstrap count) without polluting the URL.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import get_user_id
from app.services.market_data import get_historical_multi, get_risk_free_rate
from app.services.portfolio_service import load_portfolio_data
from app.compute.returns import build_portfolio_returns
from app.services.quant_analytics import (
    compute_rebalancing_bands,
    compute_net_alpha_after_costs,
    compute_after_tax_drag,
    compute_liquidity_score,
    compute_model_agreement_score,
    compute_expected_return_bands,
    explain_bl_posterior,
    compute_tracking_error_budget,
    compute_walk_forward_metrics,
    compute_regime_probabilities,
    compute_dynamic_weight_caps,
    compute_expected_drawdown_profile,
    compute_model_drift_score,
    benchmark_naive_portfolios,
    compute_factor_risk_decomposition,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analytics/quant-advanced", tags=["quant-analytics"])


class QuantAdvancedRequest(BaseModel):
    period: str = "2y"
    n_bootstrap: int = 500
    n_dd_sims: int = 1000
    horizons_years: list[int] = [1, 3, 5]
    band_tolerance: float = 0.02
    te_budget: float = 0.10
    bl_views: dict[str, dict] = {}       # {ticker: {return: float, confidence: float}}
    risk_free_rate: Optional[float] = None
    benchmark_ticker: str = "VOO"


def _build_asset_returns(tickers: list[str], period: str) -> pd.DataFrame:
    hist = get_historical_multi(tickers, period=period)
    closes: dict[str, pd.Series] = {}
    for t, df in hist.items():
        if not df.empty:
            col = "Close" if "Close" in df.columns else df.columns[0]
            closes[t] = df[col].dropna()
    return pd.DataFrame(closes).dropna(how="all").ffill().pct_change().dropna()


def _build_benchmark_returns(benchmark_ticker: str, period: str) -> pd.Series:
    try:
        hist = get_historical_multi([benchmark_ticker], period=period)
        df = hist.get(benchmark_ticker, pd.DataFrame())
        if df.empty:
            return pd.Series(dtype=float)
        col = "Close" if "Close" in df.columns else df.columns[0]
        return df[col].dropna().pct_change().dropna()
    except Exception:
        return pd.Series(dtype=float)


@router.post("")
def quant_advanced(
    body: QuantAdvancedRequest,
    user_id: str = Depends(get_user_id),
):
    """
    Run all 15 Quant Analytics v2 modules and return results as a flat JSON object.
    Each module is wrapped in try/except — a failure in one module never breaks
    the other modules or the response.
    """
    # ── Load portfolio ────────────────────────────────────────────────────────
    try:
        summary, tickers, settings = load_portfolio_data(user_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Portfolio load failed: {exc}")

    if not tickers:
        raise HTTPException(status_code=422, detail="Portfolio is empty")

    rfr = body.risk_free_rate or float(settings.get("risk_free_rate") or get_risk_free_rate())
    total_value = float(summary.total_value_base)

    current_weights: dict[str, float] = {
        r.ticker: r.weight / 100 for r in summary.rows
    }
    position_values: dict[str, float] = {
        r.ticker: r.value_base for r in summary.rows
    }
    current_prices: dict[str, float] = {
        r.ticker: float(getattr(r, "price_base", 0) or 0) for r in summary.rows
    }

    # ── Load returns ──────────────────────────────────────────────────────────
    try:
        asset_returns = _build_asset_returns(tickers, body.period)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Return data unavailable: {exc}")

    if asset_returns.empty:
        raise HTTPException(status_code=422, detail="No return history available")

    portfolio_returns = build_portfolio_returns(
        get_historical_multi(tickers, period=body.period), current_weights
    )
    benchmark_returns = _build_benchmark_returns(body.benchmark_ticker, body.period)

    # ── Load transactions for tax drag ───────────────────────────────────────
    try:
        from app.db.supabase_client import get_admin_client
        db = get_admin_client()
        tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
        transactions = tx_res.data or []
    except Exception:
        transactions = []

    # ── Expected returns (simple historical mean) ─────────────────────────────
    expected_returns: dict[str, float] = {
        t: float(asset_returns[t].mean() * 252)
        for t in asset_returns.columns
    }

    # ── Policy target weights (from settings or equal-weight) ─────────────────
    target_weights: dict[str, float] = current_weights  # fallback: hold current

    # ── Run all 15 analytics modules ─────────────────────────────────────────

    result: dict = {}

    # 1. Rebalancing bands
    try:
        result["rebalancing_bands"] = compute_rebalancing_bands(
            current_weights=current_weights,
            target_weights=target_weights,
            total_value=total_value,
            band_tolerance=body.band_tolerance,
        )
    except Exception as exc:
        log.warning("rebalancing_bands failed: %s", exc)
        result["rebalancing_bands"] = None

    # 2. Net alpha after costs
    try:
        result["net_alpha"] = compute_net_alpha_after_costs(
            expected_returns=expected_returns,
            current_weights=current_weights,
            target_weights=target_weights,
            total_value=total_value,
        )
    except Exception as exc:
        log.warning("net_alpha failed: %s", exc)
        result["net_alpha"] = None

    # 3. After-tax drag
    try:
        ann_return = float((1 + portfolio_returns).prod() ** (252 / max(len(portfolio_returns), 1)) - 1) \
            if not portfolio_returns.empty else 0.0
        result["after_tax_drag"] = compute_after_tax_drag(
            portfolio_ann_return=ann_return,
            transactions=transactions,
            current_prices=current_prices,
        )
    except Exception as exc:
        log.warning("after_tax_drag failed: %s", exc)
        result["after_tax_drag"] = None

    # 4. Liquidity score (uses pre-fetched ADV from asset data)
    try:
        # ADV approximation from historical data already loaded
        hist_raw = get_historical_multi(tickers, period="1mo")
        adv_map: dict[str, float] = {}
        for t, df in hist_raw.items():
            if not df.empty and "Volume" in df.columns and "Close" in df.columns:
                adv_map[t] = float((df["Close"] * df["Volume"]).mean())
        result["liquidity"] = compute_liquidity_score(
            tickers=tickers,
            adv_map=adv_map,
            position_values=position_values,
        )
    except Exception as exc:
        log.warning("liquidity failed: %s", exc)
        result["liquidity"] = None

    # 5. Model agreement (uses current portfolio as single "model" unless caller
    #    provides multiple weight sets — expose as a single model for now)
    try:
        # Build a simple 2-model comparison: current weights vs equal weight
        eq_w = {t: 1 / len(tickers) for t in tickers}
        result["model_agreement"] = compute_model_agreement_score(
            optimizer_weights={"current": current_weights, "equal_weight": eq_w},
            tickers=list(asset_returns.columns),
        )
    except Exception as exc:
        log.warning("model_agreement failed: %s", exc)
        result["model_agreement"] = None

    # 6. Expected return bands
    try:
        result["return_bands"] = compute_expected_return_bands(
            asset_returns=asset_returns,
            n_bootstrap=body.n_bootstrap,
        )
    except Exception as exc:
        log.warning("return_bands failed: %s", exc)
        result["return_bands"] = None

    # 7. BL explainability
    try:
        if body.bl_views:
            # Derive equilibrium returns from asset_returns CAPM proxy
            w_eq = np.array([1 / len(asset_returns.columns)] * len(asset_returns.columns))
            cov = asset_returns.cov().values * 252
            pi = 2.5 * cov @ w_eq
            equilibrium = {t: float(pi[i]) for i, t in enumerate(asset_returns.columns)}
            # BL posterior ≈ equilibrium pulled by views (simplified here)
            posterior = {t: equilibrium[t] + (body.bl_views.get(t, {}).get("return", 0)
                         - equilibrium[t]) * body.bl_views.get(t, {}).get("confidence", 0)
                         for t in equilibrium}
            result["bl_explanation"] = explain_bl_posterior(
                equilibrium_returns=equilibrium,
                posterior_returns=posterior,
                views=body.bl_views,
            )
        else:
            result["bl_explanation"] = []
    except Exception as exc:
        log.warning("bl_explanation failed: %s", exc)
        result["bl_explanation"] = None

    # 8. Tracking error budget
    try:
        bench_series = benchmark_returns if not benchmark_returns.empty else None
        result["tracking_error_budget"] = compute_tracking_error_budget(
            asset_returns=asset_returns,
            portfolio_weights=current_weights,
            benchmark_returns=bench_series,
            te_budget=body.te_budget,
        )
    except Exception as exc:
        log.warning("tracking_error_budget failed: %s", exc)
        result["tracking_error_budget"] = None

    # 9. Walk-forward validation
    try:
        result["walk_forward"] = compute_walk_forward_metrics(
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns if not benchmark_returns.empty else None,
            risk_free_rate=rfr,
        )
    except Exception as exc:
        log.warning("walk_forward failed: %s", exc)
        result["walk_forward"] = None

    # 10. Regime probabilities
    try:
        result["regime"] = compute_regime_probabilities(portfolio_returns)
    except Exception as exc:
        log.warning("regime failed: %s", exc)
        result["regime"] = None

    # 11. Dynamic weight caps
    try:
        result["dynamic_caps"] = compute_dynamic_weight_caps(
            asset_returns=asset_returns,
            current_weights=current_weights,
        )
    except Exception as exc:
        log.warning("dynamic_caps failed: %s", exc)
        result["dynamic_caps"] = None

    # 12. Expected drawdown profile
    try:
        result["drawdown_profile"] = compute_expected_drawdown_profile(
            portfolio_returns=portfolio_returns,
            current_value=total_value,
            horizons_years=body.horizons_years,
            n_sims=body.n_dd_sims,
        )
    except Exception as exc:
        log.warning("drawdown_profile failed: %s", exc)
        result["drawdown_profile"] = None

    # 13. Model drift
    try:
        result["model_drift"] = compute_model_drift_score(
            asset_returns=asset_returns,
            risk_free_rate=rfr,
        )
    except Exception as exc:
        log.warning("model_drift failed: %s", exc)
        result["model_drift"] = None

    # 14. Naive benchmark comparison
    try:
        result["naive_benchmarks"] = benchmark_naive_portfolios(
            asset_returns=asset_returns,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns if not benchmark_returns.empty else None,
            risk_free_rate=rfr,
        )
    except Exception as exc:
        log.warning("naive_benchmarks failed: %s", exc)
        result["naive_benchmarks"] = None

    # 15. Factor risk decomposition
    try:
        result["factor_risk"] = compute_factor_risk_decomposition(
            asset_returns=asset_returns,
            portfolio_weights=current_weights,
            risk_free_rate=rfr,
        )
    except Exception as exc:
        log.warning("factor_risk failed: %s", exc)
        result["factor_risk"] = None

    return result
