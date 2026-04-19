"""
POST /api/contribution-plan

Triggers the full QuantEngine pipeline and returns an optimized
contribution plan with slippage breakdown, regime info, and correlation alerts.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import get_user_id
from app.services.portfolio_service import load_portfolio_data
from app.services.quant_engine import QuantEngine
from app.services.contribution_plan import generate_contribution_plan
from app.db.quant_results import (
    save_quant_result,
    save_contribution_plan,
    load_user_bl_views,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contribution-plan", tags=["contribution"])


class ContributionRequest(BaseModel):
    available_cash: float
    profile: str = "base"   # conservative | base | aggressive


@router.post("")
def run_contribution_plan(
    req: ContributionRequest,
    user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """
    Full pipeline:
      1. Load portfolio + settings from DB
      2. Load user BL views from DB (default: empty → CAPM equilibrium)
      3. Load Motor 1 & Motor 2 constraints for the active profile
      4. Run QuantEngine.run_full_optimization()
      5. estimate_slippage() for tickers that will be bought
      6. generate_contribution_plan()
      7. Persist QuantResult + ContributionPlan
      8. Return full response
    """
    if req.available_cash <= 0:
        raise HTTPException(status_code=400, detail="available_cash must be > 0")

    profile = req.profile if req.profile in ("conservative", "base", "aggressive") else "base"

    # ── Load portfolio ────────────────────────────────────────────────────
    summary, tickers, settings = load_portfolio_data(user_id)
    if not tickers:
        raise HTTPException(status_code=422, detail="No positions found. Add positions first.")

    # Include all tickers from positions table (even 0-share pending ones) so
    # the optimizer can allocate to them and their Motor 1/2 constraints apply.
    rows_by_ticker = {r.ticker: r for r in summary.rows}
    portfolio: dict = {
        t: {
            "value_base": rows_by_ticker[t].value_base if t in rows_by_ticker else 0.0,
            "shares": rows_by_ticker[t].shares if t in rows_by_ticker else 0.0,
        }
        for t in tickers
    }

    # ── Motor 1 & Motor 2 constraints ─────────────────────────────────────
    ticker_weight_rules = settings.get("ticker_weight_rules") or {}
    combination_ranges = settings.get("combination_ranges") or {}
    active_profile = profile

    constraints_motor1: dict = {}
    profile_rules = ticker_weight_rules.get(active_profile, {})
    for ticker, rule in profile_rules.items():
        if isinstance(rule, dict):
            constraints_motor1[ticker] = {
                "floor": float(rule.get("floor", 0.0)),
                "cap": float(rule.get("cap", 1.0)),
            }

    constraints_motor2: list[dict] = combination_ranges.get(active_profile, []) or []

    # ── BL views from DB ──────────────────────────────────────────────────
    bl_views = load_user_bl_views(user_id)

    # ── Risk-free rate from settings ──────────────────────────────────────
    rfr = float(settings.get("risk_free_rate", 0.045))

    # ── Run optimization ──────────────────────────────────────────────────
    engine = QuantEngine(risk_free_rate=rfr)

    try:
        result = engine.run_full_optimization(
            portfolio=portfolio,
            profile=active_profile,
            bl_views=bl_views,
            constraints_motor1=constraints_motor1,
            constraints_motor2=constraints_motor2,
            available_cash=req.available_cash,
        )
    except Exception as exc:
        log.error("QuantEngine failed for user %s: %s", user_id[:8], exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Optimization failed: {exc}")

    # ── Estimate slippage for buying tickers ──────────────────────────────
    # Only estimate for tickers that will receive allocation
    current_values = {r.ticker: r.value_base for r in summary.rows}
    total_after = summary.total_value_base + req.available_cash
    candidate_tickers = [
        t for t, w in result.optimal_weights.items()
        if w * total_after > current_values.get(t, 0.0)
    ]

    # Approximate trade sizes for slippage estimation
    trade_sizes: dict[str, float] = {}
    for t in candidate_tickers:
        cur_val = current_values.get(t, 0.0)
        target_val = result.optimal_weights.get(t, 0.0) * total_after
        trade_sizes[t] = max(0.0, target_val - cur_val)

    slippage = {}
    if candidate_tickers:
        try:
            slippage = engine.estimate_slippage(candidate_tickers, trade_sizes)
        except Exception as exc:
            log.warning("Slippage estimation failed: %s", exc)
            slippage = {t: {"spread_cost": 0.001, "volume_impact": 0.0, "total": 0.001}
                        for t in candidate_tickers}

    # ── Generate contribution plan ─────────────────────────────────────────
    plan = generate_contribution_plan(
        result=result,
        current_portfolio=portfolio,
        available_cash=req.available_cash,
        slippage_estimates=slippage,
    )

    # ── Persist ───────────────────────────────────────────────────────────
    qr_id = save_quant_result(user_id, result, active_profile)
    save_contribution_plan(user_id, plan, qr_id)

    # ── Serialize response ────────────────────────────────────────────────
    return {
        "contribution_plan": {
            "allocations": [
                {
                    "ticker": r.ticker,
                    "current_weight": r.current_weight,
                    "target_weight": r.target_weight,
                    "gap": r.gap,
                    "gross_amount": r.gross_amount,
                    "slippage_cost": r.slippage_cost,
                    "net_amount": r.net_amount,
                }
                for r in plan.allocations
            ],
            "total_cash": plan.total_cash,
            "total_slippage": plan.total_slippage,
            "net_invested": plan.net_invested,
        },
        "quant_result": {
            "optimal_weights": result.optimal_weights,
            "expected_return": result.expected_return,
            "expected_volatility": result.expected_volatility,
            "expected_sharpe": result.expected_sharpe,
            "cvar_95": result.cvar_95,
        },
        "regime": result.regime,
        "regime_confidence": result.regime_confidence,
        "regime_probs": result.regime_probs,
        "ml_diagnostics": result.ml_diagnostics,
        "correlation_alerts": result.correlation_alerts,
        "slippage_breakdown": slippage,
        "optimization_timestamp": result.timestamp.isoformat(),
        "profile": active_profile,
    }
