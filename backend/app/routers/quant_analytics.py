"""
Quant Analytics v2 — FastAPI router.

POST /api/analytics/quant-advanced
  Starts background computation; returns {job_id, status:"computing"} immediately.

GET  /api/analytics/quant-advanced/result/{job_id}
  Returns {status:"computing"} or {status:"done", result:{...}} or {status:"error", detail:str}.

Frontend polls every 3 s until status=="done".
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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

# ── In-memory job store ───────────────────────────────────────────────────────
# {job_id: {"status": "computing"|"done"|"error", "result": ..., "detail": ..., "ts": float}}
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_JOB_TTL = 600  # seconds — clean up old jobs


def _prune_jobs() -> None:
    now = time.time()
    with _jobs_lock:
        stale = [k for k, v in _jobs.items() if now - v["ts"] > _JOB_TTL]
        for k in stale:
            del _jobs[k]


class QuantAdvancedRequest(BaseModel):
    period: str = "1y"
    n_bootstrap: int = 20
    n_dd_sims: int = 50
    horizons_years: list[int] = [1, 3, 5]
    band_tolerance: float = 0.02
    te_budget: float = 0.10
    bl_views: dict[str, dict] = {}
    risk_free_rate: Optional[float] = None
    benchmark_ticker: str = "VOO"


def _closes_from_hist(hist: dict) -> dict[str, pd.Series]:
    closes: dict[str, pd.Series] = {}
    for t, df in hist.items():
        if not df.empty:
            col = "Close" if "Close" in df.columns else df.columns[0]
            closes[t] = df[col].dropna()
    return closes


def _returns_from_hist(hist: dict) -> pd.DataFrame:
    closes = _closes_from_hist(hist)
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


def _run_quant(job_id: str, body: QuantAdvancedRequest, user_id: str) -> None:
    """Runs in a background thread; writes result to _jobs[job_id]."""
    try:
        result = _compute_all(body, user_id)
        with _jobs_lock:
            _jobs[job_id] = {"status": "done", "result": result, "ts": time.time()}
    except HTTPException as exc:
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "detail": exc.detail, "ts": time.time()}
    except Exception as exc:
        log.exception("quant background job %s failed", job_id)
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "detail": str(exc), "ts": time.time()}


def _compute_all(body: QuantAdvancedRequest, user_id: str) -> dict:
    # ── Load portfolio ────────────────────────────────────────────────────────
    try:
        summary, tickers, settings = load_portfolio_data(user_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Portfolio load failed: {exc}")

    if not tickers:
        raise HTTPException(status_code=422, detail="Portfolio is empty")

    rfr = body.risk_free_rate or float(settings.get("risk_free_rate") or get_risk_free_rate())
    total_value = float(summary.total_value_base)

    current_weights: dict[str, float] = {r.ticker: r.weight / 100 for r in summary.rows}
    position_values: dict[str, float] = {r.ticker: r.value_base for r in summary.rows}
    current_prices: dict[str, float] = {
        r.ticker: float(getattr(r, "price_base", 0) or 0) for r in summary.rows
    }

    # ── Market data ───────────────────────────────────────────────────────────
    try:
        hist = get_historical_multi(tickers, period=body.period)
        asset_returns = _returns_from_hist(hist)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Return data unavailable: {exc}")

    if asset_returns.empty:
        raise HTTPException(status_code=422, detail="No return history available")

    portfolio_returns = build_portfolio_returns(hist, current_weights)
    benchmark_returns = _build_benchmark_returns(body.benchmark_ticker, body.period)

    # ── Transactions ──────────────────────────────────────────────────────────
    try:
        from app.db.supabase_client import get_admin_client
        db = get_admin_client()
        tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
        transactions = tx_res.data or []
    except Exception:
        transactions = []

    expected_returns: dict[str, float] = {
        t: float(asset_returns[t].mean() * 252) for t in asset_returns.columns
    }
    target_weights: dict[str, float] = current_weights

    result: dict = {}

    def _run(key: str, fn, **kwargs):
        try:
            result[key] = fn(**kwargs)
        except Exception as exc:
            log.warning("%s failed: %s", key, exc)
            result[key] = None

    _run("rebalancing_bands", compute_rebalancing_bands,
         current_weights=current_weights, target_weights=target_weights,
         total_value=total_value, band_tolerance=body.band_tolerance)

    _run("net_alpha", compute_net_alpha_after_costs,
         expected_returns=expected_returns, current_weights=current_weights,
         target_weights=target_weights, total_value=total_value)

    try:
        ann_return = float(
            (1 + portfolio_returns).prod() ** (252 / max(len(portfolio_returns), 1)) - 1
        ) if not portfolio_returns.empty else 0.0
        result["after_tax_drag"] = compute_after_tax_drag(
            portfolio_ann_return=ann_return,
            transactions=transactions,
            current_prices=current_prices,
        )
    except Exception as exc:
        log.warning("after_tax_drag failed: %s", exc)
        result["after_tax_drag"] = None

    try:
        adv_map: dict[str, float] = {}
        for t, df in hist.items():
            if not df.empty and "Volume" in df.columns and "Close" in df.columns:
                adv_map[t] = float((df["Close"].iloc[-30:] * df["Volume"].iloc[-30:]).mean())
        result["liquidity"] = compute_liquidity_score(
            tickers=tickers, adv_map=adv_map, position_values=position_values)
    except Exception as exc:
        log.warning("liquidity failed: %s", exc)
        result["liquidity"] = None

    try:
        eq_w = {t: 1 / len(tickers) for t in tickers}
        result["model_agreement"] = compute_model_agreement_score(
            optimizer_weights={"current": current_weights, "equal_weight": eq_w},
            tickers=list(asset_returns.columns),
        )
    except Exception as exc:
        log.warning("model_agreement failed: %s", exc)
        result["model_agreement"] = None

    _run("return_bands", compute_expected_return_bands,
         asset_returns=asset_returns, n_bootstrap=body.n_bootstrap)

    try:
        if body.bl_views:
            w_eq = np.array([1 / len(asset_returns.columns)] * len(asset_returns.columns))
            cov = asset_returns.cov().values * 252
            pi = 2.5 * cov @ w_eq
            equilibrium = {t: float(pi[i]) for i, t in enumerate(asset_returns.columns)}
            posterior = {
                t: equilibrium[t] + (body.bl_views.get(t, {}).get("return", 0) - equilibrium[t])
                * body.bl_views.get(t, {}).get("confidence", 0)
                for t in equilibrium
            }
            result["bl_explanation"] = explain_bl_posterior(
                equilibrium_returns=equilibrium, posterior_returns=posterior, views=body.bl_views)
        else:
            result["bl_explanation"] = []
    except Exception as exc:
        log.warning("bl_explanation failed: %s", exc)
        result["bl_explanation"] = None

    _run("tracking_error_budget", compute_tracking_error_budget,
         asset_returns=asset_returns, portfolio_weights=current_weights,
         benchmark_returns=benchmark_returns if not benchmark_returns.empty else None,
         te_budget=body.te_budget)

    _run("walk_forward", compute_walk_forward_metrics,
         portfolio_returns=portfolio_returns,
         benchmark_returns=benchmark_returns if not benchmark_returns.empty else None,
         risk_free_rate=rfr)

    _run("regime", compute_regime_probabilities, portfolio_returns=portfolio_returns)

    _run("dynamic_caps", compute_dynamic_weight_caps,
         asset_returns=asset_returns, current_weights=current_weights)

    _run("drawdown_profile", compute_expected_drawdown_profile,
         portfolio_returns=portfolio_returns, current_value=total_value,
         horizons_years=body.horizons_years, n_sims=body.n_dd_sims)

    _run("model_drift", compute_model_drift_score,
         asset_returns=asset_returns, risk_free_rate=rfr)

    _run("naive_benchmarks", benchmark_naive_portfolios,
         asset_returns=asset_returns, portfolio_returns=portfolio_returns,
         benchmark_returns=benchmark_returns if not benchmark_returns.empty else None,
         risk_free_rate=rfr)

    _run("factor_risk", compute_factor_risk_decomposition,
         asset_returns=asset_returns, portfolio_weights=current_weights, risk_free_rate=rfr)

    return result


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("")
def quant_advanced_start(
    body: QuantAdvancedRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_user_id),
):
    """Start background computation; returns job_id immediately."""
    _prune_jobs()
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "computing", "result": None, "ts": time.time()}

    # Run in a daemon thread so FastAPI can return the response immediately
    t = threading.Thread(target=_run_quant, args=(job_id, body, user_id), daemon=True)
    t.start()

    return {"job_id": job_id, "status": "computing"}


@router.get("/result/{job_id}")
def quant_advanced_result(job_id: str, user_id: str = Depends(get_user_id)):
    """Poll this endpoint until status=='done'."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    if job["status"] == "computing":
        return {"status": "computing"}
    if job["status"] == "error":
        return {"status": "error", "detail": job.get("detail", "Unknown error")}
    return {"status": "done", "result": job["result"]}
