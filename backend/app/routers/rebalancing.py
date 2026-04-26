from fastapi import APIRouter, Depends, Query
import numpy as np
import pandas as pd
from app.auth.dependencies import get_user_id
from app.services.market_data import get_risk_free_rate, get_historical_multi
from app.compute.rebalancing import build_rebalancing_table, compute_target_weights_from_drift
from app.compute.optimization import simulate_efficient_frontier, optimize_max_sharpe, optimize_max_return
from app.compute.profile import compute_profile_weights, compute_profile_metrics
from app.models.analytics import RebalancingRow
from app.services.portfolio_service import load_portfolio_data
from app.db.quant_results import load_latest_quant_result, load_user_bl_views

router = APIRouter(prefix="/api/rebalancing", tags=["rebalancing"])

# ── Regime → threshold multiplier per profile ─────────────────────────────────
# Conservative in crisis → raise threshold (trade less, protect capital)
# Aggressive in bull    → lower threshold (rebalance more, capture upside)
_REGIME_THRESHOLD_MULT: dict[str, dict[str, float]] = {
    "bull_strong": {"conservative": 1.0, "base": 1.0, "aggressive": 0.8},
    "bull_weak":   {"conservative": 1.1, "base": 1.0, "aggressive": 0.9},
    "bear_mild":   {"conservative": 1.3, "base": 1.1, "aggressive": 1.0},
    "crisis":      {"conservative": 1.6, "base": 1.2, "aggressive": 1.0},
}

# ── Regime → CVaR limit scaling per profile ───────────────────────────────────
# In crisis: tighten CVaR for conservative/base; aggressive stays same
_REGIME_CVAR_MULT: dict[str, dict[str, float]] = {
    "bull_strong": {"conservative": 1.1, "base": 1.1, "aggressive": 1.2},
    "bull_weak":   {"conservative": 1.0, "base": 1.0, "aggressive": 1.1},
    "bear_mild":   {"conservative": 0.85, "base": 0.90, "aggressive": 1.0},
    "crisis":      {"conservative": 0.70, "base": 0.80, "aggressive": 0.95},
}


def _compute_bl_mu(
    returns_df: pd.DataFrame,
    bl_views: dict,
    risk_aversion: float = 2.5,
    tau: float = 0.05,
) -> np.ndarray:
    """
    Black-Litterman posterior expected returns (annualized).
    Uses equal-weight market portfolio as prior.
    bl_views: {ticker: {"return": float, "confidence": float}}
    """
    tickers = list(returns_df.columns)
    n = len(tickers)
    cov = returns_df.cov().values * 252
    w_eq = np.ones(n) / n
    pi = risk_aversion * cov @ w_eq  # equilibrium returns

    view_tickers = [t for t in bl_views if t in tickers]
    if not view_tickers:
        return pi

    k = len(view_tickers)
    P = np.zeros((k, n))
    q = np.zeros(k)
    omega_diag = np.zeros(k)
    for i, t in enumerate(view_tickers):
        j = tickers.index(t)
        P[i, j] = 1.0
        q[i] = float(bl_views[t]["return"])
        conf = float(bl_views[t].get("confidence", 0.5))
        # Higher confidence → smaller uncertainty (omega)
        omega_diag[i] = tau * cov[j, j] * max(1.0 - conf, 0.05)

    tau_sigma = tau * cov
    omega = np.diag(omega_diag)
    try:
        inv_tau_sigma = np.linalg.inv(tau_sigma + np.eye(n) * 1e-8)
        inv_omega = np.linalg.inv(omega + np.eye(k) * 1e-8)
        M = inv_tau_sigma + P.T @ inv_omega @ P
        mu_bl = np.linalg.solve(M + np.eye(n) * 1e-8, inv_tau_sigma @ pi + P.T @ inv_omega @ q)
        return mu_bl
    except np.linalg.LinAlgError:
        return pi


@router.get("/suggestions", response_model=list[RebalancingRow])
def suggestions(
    contribution: float = Query(default=0.0),
    tc_model: str = Query(default="broker"),
    user_id: str = Depends(get_user_id),
):
    summary, tickers, settings = load_portfolio_data(user_id)
    if not tickers:
        return []

    threshold = float(settings.get("rebalancing_threshold", 0.05))
    investor_profile = settings.get("investor_profile", "balanced")
    target_return = float(settings.get("target_return", 0.08))
    rfr = float(settings.get("risk_free_rate", 0.045))
    max_single = float(settings.get("max_single_asset", 0.40))

    rows_dicts = [r.model_dump() for r in summary.rows]

    # ── Motor 1 & 2 constraints ───────────────────────────────────────────────
    ticker_weight_rules = settings.get("ticker_weight_rules") or {}
    combination_ranges = settings.get("combination_ranges") or {}
    profile_key = investor_profile if investor_profile in ("conservative", "base", "aggressive") else None

    per_ticker_bounds = None
    combination_constraints = None
    if profile_key:
        profile_rules = ticker_weight_rules.get(profile_key, {})
        per_ticker_bounds = {
            ticker: (float(rule.get("floor", 0.0)), float(rule.get("cap", 1.0)))
            for ticker, rule in profile_rules.items()
            if isinstance(rule, dict)
        } or None
        combination_constraints = combination_ranges.get(profile_key, []) or None

    # ── Load quant cache (regime + CVaR + optimal weights) ───────────────────
    regime = None
    cvar_95_daily = None
    target_weights = None

    try:
        cached_qr = load_latest_quant_result(user_id)
        if cached_qr:
            regime = cached_qr.get("regime")  # e.g. "bull_strong", "crisis"
            cvar_raw = cached_qr.get("cvar_95")
            if cvar_raw is not None:
                cvar_95_daily = float(cvar_raw)

            # Priority 1: use cached optimal weights if they cover the portfolio
            raw_w = cached_qr.get("optimal_weights") or {}
            if isinstance(raw_w, dict):
                filtered = {t: float(w) for t, w in raw_w.items() if t in tickers}
                wsum = sum(filtered.values())
                if wsum > 0.5:
                    target_weights = {t: w / wsum for t, w in filtered.items()}
    except Exception:
        pass

    # ── Regime → adjust threshold per profile ────────────────────────────────
    if regime and profile_key and regime in _REGIME_THRESHOLD_MULT:
        mult = _REGIME_THRESHOLD_MULT[regime].get(profile_key, 1.0)
        threshold = threshold * mult

    # ── CVaR limit: scale regime multiplier per profile ───────────────────────
    cvar_limit = None
    if cvar_95_daily is not None and profile_key and regime in (_REGIME_CVAR_MULT or {}):
        cvar_mult = _REGIME_CVAR_MULT.get(regime, {}).get(profile_key, 1.0)
        cvar_limit = cvar_95_daily * cvar_mult
    elif profile_key:
        # Fallback: use profile default (defined inside profile.py)
        cvar_limit = None  # profile.py will apply _CVAR_LIMIT_DEFAULT

    # ── Priority 2: profile-driven weights with BL + CVaR ────────────────────
    if target_weights is None and profile_key:
        try:
            hist = get_historical_multi(tickers, period="2y")
            closes: dict[str, pd.Series] = {}
            for t, df in hist.items():
                if not df.empty:
                    col = "Close" if "Close" in df.columns else df.columns[0]
                    closes[t] = df[col].dropna()
            returns_df = pd.DataFrame(closes).dropna(how="all").ffill().pct_change().dropna()

            if not returns_df.empty:
                # Load BL views and compute BL-adjusted mu if views exist
                mu_bl = None
                try:
                    bl_views = load_user_bl_views(user_id)
                    if bl_views:
                        mu_bl = _compute_bl_mu(returns_df, bl_views)
                except Exception:
                    pass

                target_weights = compute_profile_weights(
                    returns_df,
                    profile_key,
                    rfr,
                    target_return,
                    max_single,
                    per_ticker_bounds,
                    combination_constraints,
                    mu_override=mu_bl,
                    cvar_limit=cvar_limit,
                )
        except Exception:
            pass

    # ── Priority 3: drift-based equal-weight fallback ─────────────────────────
    if target_weights is None:
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
    """
    summary, tickers, settings = load_portfolio_data(user_id)
    if not tickers:
        return {"required_contribution": 0, "max_sharpe_weights": {}, "buy_plan": {}}

    hist = get_historical_multi(tickers, period=period)
    closes: dict[str, pd.Series] = {}
    for t, df in hist.items():
        if not df.empty:
            col = "Close" if "Close" in df.columns else df.columns[0]
            closes[t] = df[col].dropna()

    returns_df = pd.DataFrame(closes).dropna(how="all").ffill().pct_change().dropna()
    rfr = get_risk_free_rate()

    investor_profile = settings.get("investor_profile", "base")
    profile_key = investor_profile if investor_profile in ("conservative", "base", "aggressive") else "base"
    ticker_weight_rules = settings.get("ticker_weight_rules") or {}
    combination_ranges_data = settings.get("combination_ranges") or {}

    profile_rules = ticker_weight_rules.get(profile_key, {})
    per_ticker_bounds = {
        ticker: (float(rule.get("floor", 0.0)), float(rule.get("cap", 1.0)))
        for ticker, rule in profile_rules.items()
        if isinstance(rule, dict)
    } or None
    combination_constraints = combination_ranges_data.get(profile_key, []) or None

    target_return_val = float(settings.get("target_return", 0.08))

    # Load BL views and CVaR from quant cache
    mu_bl = None
    cvar_limit = None
    try:
        bl_views = load_user_bl_views(user_id)
        if bl_views and not returns_df.empty:
            mu_bl = _compute_bl_mu(returns_df, bl_views)
    except Exception:
        pass
    try:
        cached_qr = load_latest_quant_result(user_id)
        if cached_qr and cached_qr.get("cvar_95") is not None:
            regime = cached_qr.get("regime", "bull_weak")
            cvar_mult = _REGIME_CVAR_MULT.get(regime, {}).get(profile_key, 1.0)
            cvar_limit = float(cached_qr["cvar_95"]) * cvar_mult
    except Exception:
        pass

    ms_weights = compute_profile_weights(
        returns_df, profile_key, rfr, target_return_val, max_single_asset,
        per_ticker_bounds, combination_constraints,
        mu_override=mu_bl, cvar_limit=cvar_limit,
    )

    if not ms_weights:
        return {"required_contribution": 0, "max_sharpe_weights": {}, "buy_plan": {}}

    current_values = {r.ticker: r.value_base for r in summary.rows}
    total_value = summary.total_value_base

    required = 0.0
    for ticker, w in ms_weights.items():
        if w > 0:
            v = current_values.get(ticker, 0.0)
            implied_total = v / w
            required = max(required, implied_total - total_value)

    required = max(0.0, round(required, 2))
    total_new = total_value + required

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

    profile_metrics = compute_profile_metrics(returns_df, ms_weights, rfr)

    return {
        "required_contribution": required,
        "max_sharpe_weights": {t: round(w * 100, 2) for t, w in ms_weights.items()},
        "buy_plan": buy_plan,
        "total_value": total_value,
        "total_after": round(total_new, 2),
        "profile": profile_key,
        "profile_metrics": profile_metrics,
    }
