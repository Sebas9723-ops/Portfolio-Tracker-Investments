"""
Persistence helpers for QuantResult and ContributionPlan.
Uses the service-role Supabase client (bypasses RLS for server-side writes).
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.db.supabase_client import get_admin_client
from app.services.quant_engine import QuantResult
from app.services.contribution_plan import ContributionPlan

log = logging.getLogger(__name__)


def save_quant_result(user_id: str, result: QuantResult, profile: str) -> str | None:
    """
    Upsert a QuantResult row into `quant_results`.
    Returns the inserted row id, or None on failure.
    """
    db = get_admin_client()
    row = {
        "user_id": user_id,
        "timestamp": result.timestamp.isoformat(),
        "profile": profile,
        "regime": result.regime,
        "regime_confidence": result.regime_confidence,
        "optimal_weights": result.optimal_weights,
        "expected_return": result.expected_return,
        "expected_volatility": result.expected_volatility,
        "expected_sharpe": result.expected_sharpe,
        "cvar_95": result.cvar_95,
        "correlation_alerts": result.correlation_alerts,
    }
    try:
        res = db.table("quant_results").insert(row).execute()
        if res.data:
            return res.data[0].get("id")
    except Exception as exc:
        log.error("Failed to save QuantResult for user %s: %s", user_id[:8], exc)
    return None


def save_contribution_plan(
    user_id: str,
    plan: ContributionPlan,
    quant_result_id: str | None,
) -> None:
    """
    Insert a ContributionPlan row into `contribution_plans`.
    """
    db = get_admin_client()
    row = {
        "user_id": user_id,
        "timestamp": datetime.utcnow().isoformat(),
        "available_cash": plan.total_cash,
        "total_slippage": plan.total_slippage,
        "net_invested": plan.net_invested,
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
        "quant_result_id": quant_result_id,
    }
    try:
        db.table("contribution_plans").insert(row).execute()
    except Exception as exc:
        log.error("Failed to save ContributionPlan for user %s: %s", user_id[:8], exc)


def load_latest_quant_result(user_id: str) -> dict | None:
    """
    Load the most recent QuantResult for a user (used for pre-cached results).
    Returns raw dict from DB or None.
    """
    db = get_admin_client()
    try:
        res = (
            db.table("quant_results")
            .select("*")
            .eq("user_id", user_id)
            .order("timestamp", desc=True)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as exc:
        log.error("Failed to load QuantResult for user %s: %s", user_id[:8], exc)
        return None


def load_user_bl_views(user_id: str) -> dict:
    """
    Load Black-Litterman views for a user from the `bl_views` table.
    Returns: {ticker: {"return": float, "confidence": float}}
    """
    db = get_admin_client()
    try:
        res = (
            db.table("bl_views")
            .select("ticker,expected_return,confidence")
            .eq("user_id", user_id)
            .execute()
        )
        views: dict = {}
        for row in res.data or []:
            views[row["ticker"]] = {
                "return": float(row["expected_return"]),
                "confidence": float(row["confidence"]),
            }
        return views
    except Exception as exc:
        log.warning("Failed to load BL views for user %s: %s", user_id[:8], exc)
        return {}
