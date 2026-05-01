"""
Agent endpoints:
  POST /api/agents/analyze       — run 3-agent pipeline on a contribution plan
  GET  /api/agents/last-results  — retrieve latest scheduled agent results (macro, doctor)
  POST /api/agents/run-now       — manually trigger macro + doctor agents
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth.dependencies import get_user_id
from app.services.agent_pipeline import run_full_agent_pipeline, run_contribution_research_agent
from app.db.agent_results import save_agent_result, load_latest_agent_result

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


@router.get("/last-results")
def last_results(user_id: str = Depends(get_user_id)) -> dict[str, Any]:
    """Return latest macro and doctor agent results for this user."""
    macro = load_latest_agent_result(user_id, "macro")
    doctor = load_latest_agent_result(user_id, "doctor")
    return {
        "macro": macro,
        "doctor": doctor,
    }


@router.post("/run-now")
def run_now(user_id: str = Depends(get_user_id)) -> dict[str, Any]:
    """Manually trigger Macro + Portfolio Doctor agents for the current user."""
    from app.db.supabase_client import get_admin_client
    from app.db.quant_results import load_latest_quant_result
    from app.services.agent_pipeline import run_macro_agent, run_portfolio_doctor_agent
    from app.services.market_data import get_quotes
    from app.services.fx_service import get_fx_rates
    from app.services.exchange_classifier import get_native_currency
    from app.compute.portfolio_builder import build_portfolio

    db = get_admin_client()
    settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    settings = settings_res.data or {}
    base_currency = settings.get("base_currency", "USD")

    positions = db.table("positions").select("*").eq("user_id", user_id).execute().data or []
    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
    if not tickers:
        return {"macro": None, "doctor": None, "error": "No positions found"}

    shares = {p["ticker"]: float(p["shares"]) for p in positions if float(p.get("shares", 0)) > 0}
    total_shares = sum(shares.values())
    weights = {t: shares[t] / total_shares for t in tickers} if total_shares > 0 else {}

    qr = load_latest_quant_result(user_id)
    expected_sharpe = float((qr or {}).get("expected_sharpe") or 1.0)
    cvar_95 = float((qr or {}).get("cvar_95") or 0.02)
    optimal_weights = (qr or {}).get("optimal_weights") or {}

    avg_drift = 0.0
    if optimal_weights:
        drifts = [abs(float(optimal_weights.get(t, 0)) - weights.get(t, 0)) for t in set(list(weights) + list(optimal_weights))]
        avg_drift = (sum(drifts) / len(drifts) * 100) if drifts else 0.0

    sharpe_score = min(25.0, max(0.0, expected_sharpe * 10.0))
    cvar_score = max(0.0, 25.0 - cvar_95 * 500)
    drift_score = max(0.0, 25.0 - avg_drift * 2.5)
    n = len(weights)
    hhi = sum(w ** 2 for w in weights.values()) if weights else 1.0
    hhi_score = max(0.0, 25.0 - (hhi - 1 / n if n > 0 else hhi) * 100) if n > 0 else 0.0
    health_score = sharpe_score + cvar_score + drift_score + hhi_score
    health_components = {
        "Sharpe": sharpe_score,
        "Diversificación": hhi_score,
        "CVaR headroom": cvar_score,
        "Drift": drift_score,
    }

    quotes = get_quotes(tickers)
    exchange_currencies = [get_native_currency(t) for t in tickers]
    fx_rates = get_fx_rates(list(set(exchange_currencies)), base=base_currency)
    transactions = db.table("transactions").select("*").eq("user_id", user_id).execute().data or []
    summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)
    total_value = float(summary.total_value_base)

    errors: list[str] = []

    try:
        macro_result = run_macro_agent(tickers, weights, base_currency)
    except Exception as exc:
        macro_result = None
        errors.append(f"Macro agent error: {exc}")

    if macro_result:
        try:
            save_agent_result(user_id, "macro", macro_result, triggered_by="manual")
        except Exception as exc:
            errors.append(f"Save macro failed: {exc}")
    else:
        if not any("Macro" in e for e in errors):
            errors.append("Macro agent returned None — check GROQ_API_KEY and yfinance connectivity")

    risk_level = "yellow"
    if macro_result:
        regime = macro_result.get("macro_regime", "")
        if regime == "crisis":
            risk_level = "red"
        elif regime in ("risk_on", "goldilocks"):
            risk_level = "green"

    try:
        doctor_result = run_portfolio_doctor_agent(
            health_score=health_score,
            health_components=health_components,
            var_1d=total_value * cvar_95 * 0.8,
            cvar_1d=total_value * cvar_95,
            max_stress_loss_pct=cvar_95 * 300,
            avg_drift_pct=avg_drift,
            risk_level=risk_level,
            base_currency=base_currency,
        )
    except Exception as exc:
        doctor_result = None
        errors.append(f"Doctor agent error: {exc}")

    if doctor_result:
        try:
            save_agent_result(user_id, "doctor", doctor_result, triggered_by="manual")
        except Exception as exc:
            errors.append(f"Save doctor failed: {exc}")
    else:
        if not any("Doctor" in e for e in errors):
            errors.append("Doctor agent returned None — check GROQ_API_KEY")

    return {"macro": macro_result, "doctor": doctor_result, "errors": errors}


class ContributionResearchRequest(BaseModel):
    allocations: list[dict]
    profile: str = "base"
    base_currency: str = "USD"


@router.post("/contribution-research")
def contribution_research(
    req: ContributionResearchRequest,
    user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """
    Contribution Research Agent: evaluates each ticker in the contribution plan
    across momentum, fundamentals, quality, and valuation signals weighted by profile.
    Returns per-ticker {score, signals, weight_adjustment, key_insight}.
    """
    result = run_contribution_research_agent(
        allocations=req.allocations,
        profile=req.profile,
        base_currency=req.base_currency,
    )
    return result or {}


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
