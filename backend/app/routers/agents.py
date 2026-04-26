"""
POST /api/agents/analyze
Runs the 3-agent AI pipeline (Director + Risk Manager + Research) on a contribution plan.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import get_user_id
from app.services.agent_pipeline import run_full_agent_pipeline

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentAnalysisRequest(BaseModel):
    # Contribution plan allocations (from POST /api/contribution-plan response)
    allocations: list[dict]
    regime: str | None = None
    regime_confidence: float = 0.0
    regime_probs: dict = {}
    profile: str = "base"
    total_value: float = 0.0
    total_cash: float = 0.0
    expected_sharpe: float = 0.0
    cvar_95: float = 0.02
    n_corr_alerts: int = 0
    correlation_alerts: list[dict] = []
    base_currency: str = "USD"


@router.post("/analyze")
def analyze(
    req: AgentAnalysisRequest,
    user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """
    Run Director Agent (thesis) + Risk Manager Agent + Research Agent per ticker.
    Accepts the contribution plan response payload from the frontend.
    Returns {thesis, risk: {risk_level, top_risk, narrative}, research: {ticker: text}}
    """
    return run_full_agent_pipeline(
        allocations=req.allocations,
        regime=req.regime,
        regime_confidence=req.regime_confidence,
        regime_probs=req.regime_probs,
        profile=req.profile,
        total_value=req.total_value,
        total_cash=req.total_cash,
        expected_sharpe=req.expected_sharpe,
        cvar_95=req.cvar_95,
        n_corr_alerts=req.n_corr_alerts,
        correlation_alerts=req.correlation_alerts,
        base_currency=req.base_currency,
    )
