"""
POST /api/contribution-plan

Unified smart contribution plan:
  1. Run QuantEngine live  (fresh GJR-GARCH + HMM + BL-XGBoost mu)
  2. Apply regime-probability weighted mu scaling
  3. Apply correlation penalty on mu
  4. SLSQP buy-only optimisation (maximise μᵀw) with Motor 1/2 + CVaR constraints
  5. Estimate real slippage for each buy
  6. Tag per-ticker signals (why each ticker was chosen)
  7. Persist QuantResult + ContributionPlan to DB
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from scipy.optimize import minimize

from app.auth.dependencies import get_user_id
from app.services.portfolio_service import load_portfolio_data
from app.services.quant_engine import QuantEngine
from app.services.contribution_plan import generate_contribution_plan
from app.compute.rebalancing import TC_MODELS
from app.db.quant_results import (
    save_quant_result,
    save_contribution_plan,
    load_user_bl_views,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contribution-plan", tags=["contribution"])

# Regime → mu scaling (same as Smart Capital)
_REGIME_MU_SCALE: dict[str, float] = {
    "bull_strong": 1.10,
    "bull_weak":   1.02,
    "bear_mild":   0.85,
    "crisis":      0.70,
}


class ContributionRequest(BaseModel):
    available_cash: float
    profile: str = "base"        # conservative | base | aggressive
    time_horizon: str = "long"   # short | medium | long
    tc_model: str = "broker"


@router.post("")
def run_contribution_plan(
    req: ContributionRequest,
    user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """
    Full unified pipeline:
      1. Load portfolio + settings (Motor 1/2, BL params) from DB
      2. Run QuantEngine.run_full_optimization() — fresh signals
      3. Regime-probability weighted mu scaling
      4. Correlation penalty on mu
      5. Net-alpha filter (TC drag)
      6. Liquidity caps (5% of 30d ADV)
      7. SLSQP buy-only optimisation with Motor 1/2 + CVaR constraints
      8. Estimate real slippage
      9. Tag per-ticker signals
     10. Persist QuantResult + ContributionPlan
    """
    if req.available_cash <= 0:
        raise HTTPException(status_code=400, detail="available_cash must be > 0")

    profile = req.profile if req.profile in ("conservative", "base", "aggressive") else "base"
    horizon = req.time_horizon if req.time_horizon in ("short", "medium", "long") else "long"
    tc_params = TC_MODELS.get(req.tc_model, TC_MODELS["broker"])
    amount = req.available_cash

    # ── Load portfolio ─────────────────────────────────────────────────────
    summary, tickers, settings = load_portfolio_data(user_id)
    if not tickers:
        raise HTTPException(status_code=422, detail="No positions found. Add positions first.")

    rfr = float(settings.get("risk_free_rate", 0.045))
    macro_overlay: dict[str, float] = settings.get("macro_overlay") or {}
    max_single = float(settings.get("max_single_asset", 0.40))
    ticker_weight_rules = settings.get("ticker_weight_rules") or {}
    combination_ranges  = settings.get("combination_ranges") or {}

    rows_by_ticker = {r.ticker: r for r in summary.rows}
    portfolio: dict = {
        t: {
            "value_base": rows_by_ticker[t].value_base if t in rows_by_ticker else 0.0,
            "shares":     rows_by_ticker[t].shares     if t in rows_by_ticker else 0.0,
        }
        for t in tickers
    }

    current_values:  dict[str, float] = {t: float(portfolio[t]["value_base"]) for t in tickers}
    total_value = float(summary.total_value_base)
    current_weights: dict[str, float] = {
        t: current_values[t] / total_value if total_value > 0 else 0.0
        for t in tickers
    }

    # ── Motor 1 & 2 ───────────────────────────────────────────────────────
    profile_rules = ticker_weight_rules.get(profile, {})
    constraints_motor1: dict = {
        t: {"floor": float(r.get("floor", 0.0)), "cap": float(r.get("cap", 1.0))}
        for t, r in profile_rules.items() if isinstance(r, dict)
    }
    per_ticker_bounds: dict[str, tuple[float, float]] = {
        t: (float(r.get("floor", 0.0)), float(r.get("cap", 1.0)))
        for t, r in profile_rules.items() if isinstance(r, dict)
    }
    constraints_motor2: list[dict] = combination_ranges.get(profile, []) or []
    combination_constraints = constraints_motor2

    # ── BL views ──────────────────────────────────────────────────────────
    bl_views = load_user_bl_views(user_id)

    # ── Run QuantEngine ───────────────────────────────────────────────────
    engine = QuantEngine(risk_free_rate=rfr)
    try:
        result = engine.run_full_optimization(
            portfolio=portfolio,
            profile=profile,
            bl_views=bl_views,
            constraints_motor1=constraints_motor1,
            constraints_motor2=constraints_motor2,
            available_cash=amount,
            time_horizon=horizon,
        )
    except Exception as exc:
        log.error("QuantEngine failed for user %s: %s", user_id[:8], exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Optimization failed: {exc}")

    # ── Extract per-ticker mu and cov from engine ─────────────────────────
    last_returns: pd.DataFrame = engine.last_returns  # type: ignore[assignment]
    tickers_avail = [t for t in tickers if t in last_returns.columns and t in result.mu_vector]
    if not tickers_avail:
        raise HTTPException(status_code=422, detail="No return history available")

    n = len(tickers_avail)
    mu_raw = np.array([result.mu_vector[t] for t in tickers_avail])
    cov = last_returns[tickers_avail].cov().values * 252

    # ── Regime-probability weighted mu scaling ────────────────────────────
    regime_probs = result.regime_probs or {}
    total_p = sum(regime_probs.values())
    if total_p > 0:
        blended_scale = sum(
            (p / total_p) * _REGIME_MU_SCALE.get(r, 1.0)
            for r, p in regime_probs.items()
        )
    else:
        blended_scale = _REGIME_MU_SCALE.get(result.regime or "bull_weak", 1.0)
    mu = mu_raw * blended_scale

    # ── Correlation penalty ───────────────────────────────────────────────
    corr_penalised: set[str] = set()
    for alert in result.correlation_alerts:
        ta = alert.get("ticker_a", "")
        tb = alert.get("ticker_b", "")
        ow_a = current_weights.get(ta, 0)
        ow_b = current_weights.get(tb, 0)
        penalise = ta if ow_a >= ow_b else tb
        if penalise in tickers_avail:
            mu[tickers_avail.index(penalise)] *= 0.80
            corr_penalised.add(penalise)

    # ── Macro overlay ─────────────────────────────────────────────────────
    for i, t in enumerate(tickers_avail):
        if t in macro_overlay:
            mult = float(macro_overlay[t])
            mu[i] = mu[i] * max(0.5, min(mult, 2.0))  # clamp multiplier to [0.5, 2.0]

    # ── Net-alpha filter ──────────────────────────────────────────────────
    ann_tc_drag = (tc_params["fixed"] / max(amount / n, 1) + tc_params["pct"]) * 2
    no_edge: set[str] = set()
    for i, t in enumerate(tickers_avail):
        if mu[i] - ann_tc_drag < 0:
            mu[i] = max(mu[i], 0.0)
            no_edge.add(t)

    # ── Liquidity caps (5% of 30d ADV) ───────────────────────────────────
    hist = getattr(engine, "_last_hist", {})  # may not be cached; skip gracefully
    liquidity_caps: dict[str, float] = {}
    try:
        from app.services.market_data import get_historical_multi
        hist = get_historical_multi(tickers_avail, period="1y")
        for t, df in hist.items():
            if t not in tickers_avail:
                continue
            if not df.empty and "Volume" in df.columns and "Close" in df.columns:
                adv = float((df["Close"].iloc[-30:] * df["Volume"].iloc[-30:]).mean())
                liquidity_caps[t] = min(adv * 0.05 / amount, 1.0) if amount > 0 else 1.0
    except Exception:
        pass

    # ── Per-ticker capital-allocation bounds ──────────────────────────────
    total_new = total_value + amount
    bounds_alloc: list[tuple[float, float]] = []
    for t in tickers_avail:
        lo_w, hi_w = per_ticker_bounds.get(t, (0.0, max_single))
        cur_v = current_values.get(t, 0.0)
        max_buy = max(0.0, hi_w * total_new - cur_v)
        frac_portfolio = min(max_buy / amount, 1.0) if amount > 0 else 0.0
        max_frac = min(frac_portfolio, hi_w)  # Motor 1: also cap fraction of new capital
        if t in liquidity_caps:
            max_frac = min(max_frac, liquidity_caps[t])
        bounds_alloc.append((0.0, max(0.0, max_frac)))

    # ── SLSQP constraints ─────────────────────────────────────────────────
    constraints_list: list[dict] = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]

    # Motor 2 in portfolio-weight space (post-deployment)
    for rule in combination_constraints:
        rule_tickers = rule.get("tickers", [])
        raw_min = rule.get("min")
        raw_max = rule.get("max")
        indices = [i for i, t in enumerate(tickers_avail) if t in rule_tickers]
        if not indices:
            continue
        if raw_min is not None:
            m = float(raw_min)
            constraints_list.append({
                "type": "ineq",
                "fun": lambda w, idx=indices, mn=m: sum(
                    (current_values.get(tickers_avail[i], 0) + w[i] * amount) / total_new
                    for i in idx
                ) - mn,
            })
        if raw_max is not None:
            m = float(raw_max)
            constraints_list.append({
                "type": "ineq",
                "fun": lambda w, idx=indices, mx=m: mx - sum(
                    (current_values.get(tickers_avail[i], 0) + w[i] * amount) / total_new
                    for i in idx
                ),
            })

    # CVaR on post-deployment portfolio
    cvar_limit = float(result.cvar_95)

    def _cvar_total(w: np.ndarray) -> float:
        port_w = np.array([
            (current_values.get(t, 0) + w[i] * amount) / total_new
            for i, t in enumerate(tickers_avail)
        ])
        port_w = np.clip(port_w, 0, None)
        s = port_w.sum()
        if s > 0:
            port_w /= s
        mu_daily = mu / 252
        cov_daily = cov / 252
        port_ret = float(mu_daily @ port_w)
        port_vol = float(np.sqrt(max(float(port_w @ cov_daily @ port_w), 1e-12)))
        return float(cvar_limit - (-port_ret + 1.645 * port_vol))

    constraints_list.append({"type": "ineq", "fun": _cvar_total})

    # ── Initial guess ─────────────────────────────────────────────────────
    mu_pos = np.maximum(mu, 0.0)
    w0 = mu_pos / mu_pos.sum() if mu_pos.sum() > 0 else np.ones(n) / n
    lo = np.array([b[0] for b in bounds_alloc])
    hi = np.array([b[1] for b in bounds_alloc])
    w0 = np.clip(w0, lo, hi)
    w0 = w0 / w0.sum() if w0.sum() > 0 else hi / hi.sum() if hi.sum() > 0 else np.ones(n) / n

    # ── Profile-aware objective ───────────────────────────────────────────
    # aggressive: maximise expected return of deployment
    # base:       balance return vs variance (Sharpe-like)
    # conservative: minimise variance increase of post-deployment portfolio
    if profile == "conservative":
        def _objective(w: np.ndarray) -> float:
            # Minimise portfolio variance after deployment
            port_w = np.array([
                (current_values.get(t, 0) + w[i] * amount) / total_new
                for i, t in enumerate(tickers_avail)
            ])
            port_w = np.clip(port_w, 0, None)
            s = port_w.sum()
            if s > 0:
                port_w /= s
            return float(port_w @ cov @ port_w)
    elif profile == "base":
        _lambda_mv = 2.0
        def _objective(w: np.ndarray) -> float:
            ret = float(mu @ w)
            var = float(w @ (cov / 252) @ w)
            return -(ret - _lambda_mv * var)
    else:  # aggressive
        def _objective(w: np.ndarray) -> float:
            return -float(mu @ w)

    # ── Optimise ──────────────────────────────────────────────────────────
    try:
        res = minimize(
            _objective,
            w0,
            method="SLSQP",
            bounds=bounds_alloc,
            constraints=constraints_list,
            options={"ftol": 1e-10, "maxiter": 1000},
        )
        w_opt = np.clip(res.x, 0, None)
        w_opt = w_opt / w_opt.sum() if w_opt.sum() > 0 else w0
    except Exception as exc:
        log.warning("SLSQP failed, falling back to gap-proportional: %s", exc)
        w_opt = w0

    # ── Estimate slippage ─────────────────────────────────────────────────
    trade_sizes: dict[str, float] = {
        tickers_avail[i]: round(float(w_opt[i]) * amount, 2)
        for i in range(n) if w_opt[i] > 0
    }
    slippage: dict[str, dict] = {}
    if trade_sizes:
        try:
            slippage = engine.estimate_slippage(list(trade_sizes.keys()), trade_sizes)
        except Exception as exc:
            log.warning("Slippage estimation failed: %s", exc)
            slippage = {t: {"spread_cost": 0.001, "volume_impact": 0.0, "total": 0.001}
                        for t in trade_sizes}

    # ── Build allocations with signals ────────────────────────────────────
    allocations = []
    total_slippage = 0.0
    for i, t in enumerate(tickers_avail):
        frac = float(w_opt[i])
        gross = round(frac * amount, 2)
        if gross < 0.01:
            continue
        slip_rate = slippage.get(t, {}).get("total", tc_params["pct"])
        slip_cost = round(gross * slip_rate, 2)
        net_amt = round(max(0.0, gross - slip_cost), 2)
        total_slippage += slip_cost

        target_w_post = (current_values.get(t, 0.0) + gross) / total_new

        signals: list[str] = []
        if t not in no_edge:
            signals.append("net_alpha_positive")
        if current_weights.get(t, 0.0) < result.optimal_weights.get(t, 0.0):
            signals.append("underweight")
        if t in corr_penalised:
            signals.append("corr_penalty_applied")
        if t in liquidity_caps and liquidity_caps[t] < 1.0:
            signals.append("liquidity_capped")
        if mu[i] > mu_raw.mean() * blended_scale * 1.1:
            signals.append("high_expected_return")

        allocations.append({
            "ticker": t,
            "current_weight": round(current_weights.get(t, 0.0), 6),
            "target_weight":  round(float(result.optimal_weights.get(t, 0.0)), 6),
            "gap": round(float(result.optimal_weights.get(t, 0.0)) - current_weights.get(t, 0.0), 6),
            "gross_amount": gross,
            "slippage_cost": slip_cost,
            "net_amount": net_amt,
            "pct_of_capital": round(frac * 100, 2),
            "expected_return_pct": round(float(mu_raw[i]) * 100, 2),
            "signals": signals,
        })

    allocations.sort(key=lambda x: x["gross_amount"], reverse=True)
    net_invested = round(sum(a["net_amount"] for a in allocations), 2)
    total_slippage = round(total_slippage, 2)

    plan_summary = {
        "allocations": allocations,
        "total_cash": round(amount, 2),
        "total_slippage": round(total_slippage, 2),
        "net_invested": net_invested,
    }

    # ── Persist ───────────────────────────────────────────────────────────
    # Build a ContributionPlan-compatible object for save_contribution_plan
    from app.services.contribution_plan import ContributionPlan, AllocationRow
    cp_rows = [
        AllocationRow(
            ticker=a["ticker"],
            current_weight=a["current_weight"],
            target_weight=a["target_weight"],
            gap=a["gap"],
            gross_amount=a["gross_amount"],
            slippage_cost=a["slippage_cost"],
            net_amount=a["net_amount"],
        )
        for a in allocations
    ]
    cp = ContributionPlan(
        allocations=cp_rows,
        total_cash=plan_summary["total_cash"],
        total_slippage=plan_summary["total_slippage"],
        net_invested=net_invested,
    )
    qr_id = save_quant_result(user_id, result, profile)
    save_contribution_plan(user_id, cp, qr_id)

    # Feature B: log predictions for tracking
    try:
        from app.db.quant_results import save_prediction_log
        save_prediction_log(user_id, qr_id, allocations)
    except Exception as _pl_exc:
        log.warning("Prediction log failed: %s", _pl_exc)

    # ── Fast analytics (9 modules, reuse engine.last_returns) ─────────────
    quant_analytics_v2: dict = {}
    try:
        from app.services.quant_analytics import (
            compute_rebalancing_bands, compute_net_alpha_after_costs,
            compute_after_tax_drag, compute_liquidity_score,
            compute_model_agreement_score, compute_tracking_error_budget,
            compute_regime_probabilities, compute_dynamic_weight_caps,
            compute_model_drift_score,
        )
        from app.compute.returns import build_portfolio_returns
        _ret = engine.last_returns
        if _ret is not None and not _ret.empty:
            _cw  = current_weights
            _ow  = result.optimal_weights
            _tv  = total_value
            _pv  = current_values
            _cp2 = {r.ticker: float(getattr(r, "price_base", 0) or 0) for r in summary.rows}
            _er  = {t: float(_ret[t].mean() * 252) for t in _ret.columns}
            _eq_w = {t: 1 / len(tickers) for t in tickers}
            _pr  = (_ret * pd.Series(_cw)).sum(axis=1)

            def _safe(fn, *a, **kw):
                try:
                    return fn(*a, **kw)
                except Exception as _e:
                    log.debug("qa_fast %s: %s", fn.__name__, _e)
                    return None

            _txs: list[dict] = []
            try:
                from app.db.supabase_client import get_admin_client
                _txs = get_admin_client().table("transactions").select("*").eq("user_id", user_id).execute().data or []
            except Exception:
                pass

            quant_analytics_v2 = {
                "rebalancing_bands":     _safe(compute_rebalancing_bands,     current_weights=_cw, target_weights=_ow, total_value=_tv),
                "net_alpha":             _safe(compute_net_alpha_after_costs, expected_returns=_er, current_weights=_cw, target_weights=_ow, total_value=_tv),
                "after_tax_drag":        _safe(compute_after_tax_drag,        portfolio_ann_return=float((_pr + 1).prod() ** (252 / max(len(_pr), 1)) - 1), transactions=_txs, current_prices=_cp2),
                "liquidity":             _safe(compute_liquidity_score,       tickers=tickers, adv_map={}, position_values=_pv),
                "model_agreement":       _safe(compute_model_agreement_score, optimizer_weights={"quant_engine": _ow, "equal_weight": _eq_w}, tickers=list(_ret.columns)),
                "tracking_error_budget": _safe(compute_tracking_error_budget, asset_returns=_ret, portfolio_weights=_cw, benchmark_returns=None),
                "regime":                _safe(compute_regime_probabilities,  portfolio_returns=_pr),
                "dynamic_caps":          _safe(compute_dynamic_weight_caps,   asset_returns=_ret, current_weights=_cw),
                "model_drift":           _safe(compute_model_drift_score,     asset_returns=_ret, risk_free_rate=rfr),
            }
    except Exception as exc:
        log.warning("qa_fast failed: %s", exc)

    return {
        "contribution_plan": plan_summary,
        "quant_result": {
            "optimal_weights":    result.optimal_weights,
            "expected_return":    result.expected_return,
            "expected_volatility": result.expected_volatility,
            "expected_sharpe":    result.expected_sharpe,
            "cvar_95":            result.cvar_95,
        },
        "regime":              result.regime,
        "regime_confidence":   result.regime_confidence,
        "regime_probs":        result.regime_probs,
        "ml_diagnostics":      result.ml_diagnostics,
        "correlation_alerts":  result.correlation_alerts,
        "slippage_breakdown":  slippage,
        "optimization_timestamp": result.timestamp.isoformat(),
        "profile":             profile,
        "time_horizon":        horizon,
        "regime_mu_scale":     round(blended_scale, 3),
        "n_corr_alerts":       len(result.correlation_alerts),
        "n_no_edge":           len(no_edge),
        "quant_analytics_v2":  quant_analytics_v2 or None,
    }
