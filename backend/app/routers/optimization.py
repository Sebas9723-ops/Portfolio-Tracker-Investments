from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional
from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client
from app.services.market_data import get_historical_multi, get_risk_free_rate
from app.compute.optimization import simulate_efficient_frontier, optimize_max_sharpe, optimize_max_return, black_litterman
from app.models.analytics import OptimizationResult
import pandas as pd

router = APIRouter(prefix="/api/optimization", tags=["optimization"])


class OptimizationRequest(BaseModel):
    period: str = "2y"
    n_simulations: int = 3000
    max_single_asset: float = 0.40
    min_bonds: float = 0.0
    min_gold: float = 0.0
    profile: str = "base"


def _load_profile_constraints(
    user_id: str, db, profile: str
) -> tuple[dict[str, tuple[float, float]], list[dict]]:
    """Load per-ticker bounds and combination constraints for the given profile."""
    settings_res = (
        db.table("user_settings")
        .select("ticker_weight_rules,combination_ranges")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    data = settings_res.data or {}

    # Motor 1 — per-ticker floor/cap: {profile: {ticker: {floor, cap}}}
    rules = data.get("ticker_weight_rules") or {}
    profile_rules = rules.get(profile, {})
    per_ticker_bounds: dict[str, tuple[float, float]] = {}
    for ticker, rule in profile_rules.items():
        if isinstance(rule, dict):
            floor = float(rule.get("floor", 0.0))
            cap = float(rule.get("cap", 1.0))
            per_ticker_bounds[ticker] = (floor, cap)

    # Motor 2 — combination ranges: {profile: [{id, tickers, min, max}]}
    ranges = data.get("combination_ranges") or {}
    combination_constraints: list[dict] = ranges.get(profile, [])

    return per_ticker_bounds or {}, combination_constraints or []


def _build_returns_df(tickers: list[str], period: str) -> pd.DataFrame:
    hist = get_historical_multi(tickers, period=period)
    closes: dict[str, pd.Series] = {}
    for t, df in hist.items():
        if not df.empty:
            col = "Close" if "Close" in df.columns else df.columns[0]
            closes[t] = df[col].dropna()
    return pd.DataFrame(closes).dropna(how="all").ffill().pct_change().dropna()


def _load_user_rfr(user_id: str, db) -> float:
    """Load risk_free_rate from user_settings, fallback to live rate."""
    res = db.table("user_settings").select("risk_free_rate").eq("user_id", user_id).maybe_single().execute()
    val = (res.data or {}).get("risk_free_rate")
    return float(val) if val is not None else get_risk_free_rate()


@router.post("/frontier", response_model=OptimizationResult)
def frontier(body: OptimizationRequest, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    pos_res = db.table("positions").select("ticker,shares").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
    shares = {p["ticker"]: float(p["shares"]) for p in positions}
    total = sum(shares.values())
    current_weights = {t: shares[t] / total for t in tickers} if total > 0 else {}

    returns_df = _build_returns_df(tickers, body.period)
    rfr = _load_user_rfr(user_id, db)
    per_ticker_bounds, combination_constraints = _load_profile_constraints(user_id, db, body.profile)

    return simulate_efficient_frontier(
        returns_df=returns_df,
        risk_free_rate=rfr,
        n_simulations=body.n_simulations,
        max_single_asset=body.max_single_asset,
        current_weights=current_weights,
        per_ticker_bounds=per_ticker_bounds or None,
        combination_constraints=combination_constraints or None,
    )


class BLRequest(BaseModel):
    views: dict[str, float] = {}   # ticker → expected annual return (e.g. 0.12)
    tau: float = 0.05
    risk_aversion: float = 3.0
    max_single_asset: float = 0.40
    period: str = "2y"


@router.post("/black-litterman")
def bl_optimization(body: BLRequest, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    pos_res = db.table("positions").select("ticker,shares").eq("user_id", user_id).execute()
    tickers = [p["ticker"] for p in (pos_res.data or []) if float(p.get("shares", 0)) > 0]

    hist = get_historical_multi(tickers, period=body.period)
    closes: dict[str, pd.Series] = {}
    for t, df in hist.items():
        if not df.empty:
            col = "Close" if "Close" in df.columns else df.columns[0]
            closes[t] = df[col].dropna()

    returns_df = pd.DataFrame(closes).dropna(how="all").ffill().pct_change().dropna()
    weights = black_litterman(
        returns_df=returns_df,
        views=body.views,
        tau=body.tau,
        risk_aversion=body.risk_aversion,
        max_single_asset=body.max_single_asset,
    )
    return {"weights": weights}


@router.post("/max-sharpe")
def max_sharpe(body: OptimizationRequest, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    pos_res = db.table("positions").select("ticker,shares").eq("user_id", user_id).execute()
    tickers = [p["ticker"] for p in (pos_res.data or []) if float(p.get("shares", 0)) > 0]

    returns_df = _build_returns_df(tickers, body.period)
    rfr = _load_user_rfr(user_id, db)
    per_ticker_bounds, combination_constraints = _load_profile_constraints(user_id, db, body.profile)
    weights = optimize_max_sharpe(returns_df, rfr, body.max_single_asset, per_ticker_bounds or None, combination_constraints or None)
    return {"weights": weights}


@router.post("/max-return")
def max_return_endpoint(body: OptimizationRequest, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    pos_res = db.table("positions").select("ticker,shares").eq("user_id", user_id).execute()
    tickers = [p["ticker"] for p in (pos_res.data or []) if float(p.get("shares", 0)) > 0]

    returns_df = _build_returns_df(tickers, body.period)
    rfr = _load_user_rfr(user_id, db)
    per_ticker_bounds, combination_constraints = _load_profile_constraints(user_id, db, body.profile)
    weights = optimize_max_return(returns_df, rfr, body.max_single_asset, per_ticker_bounds or None, combination_constraints or None)
    return {"weights": weights}


# ── Dedicated endpoints to save Motor 1 & Motor 2 constraints ────────────────

class TickerWeightRulesUpdate(BaseModel):
    profile: str
    rules: dict[str, dict]  # {ticker: {floor: float, cap: float}}


class CombinationRangesUpdate(BaseModel):
    profile: str
    ranges: list[dict]  # [{id, tickers, min, max}]


@router.put("/ticker-weight-rules")
def save_ticker_weight_rules(body: TickerWeightRulesUpdate, user_id: str = Depends(get_user_id)):
    """Save Motor 1 floor/cap rules for a specific profile."""
    from fastapi import HTTPException
    if body.profile not in ("conservative", "base", "aggressive"):
        raise HTTPException(status_code=400, detail=f"Invalid profile: {body.profile!r}")

    try:
        db = get_admin_client()
        res = db.table("user_settings").select("ticker_weight_rules").eq("user_id", user_id).maybe_single().execute()
        raw_existing = (res.data or {}).get("ticker_weight_rules")
        existing = raw_existing if isinstance(raw_existing, dict) else {}

        # Sanitize rules: ensure values are {floor: float, cap: float}
        clean_rules: dict = {}
        for ticker, rule in body.rules.items():
            if isinstance(rule, dict):
                clean_rules[ticker] = {
                    "floor": float(rule.get("floor", 0.0)),
                    "cap": float(rule.get("cap", 1.0)),
                }

        merged = {**existing, body.profile: clean_rules}
        db.table("user_settings").upsert(
            {"user_id": user_id, "ticker_weight_rules": merged},
            on_conflict="user_id",
        ).execute()
        return {"profile": body.profile, "rules": clean_rules}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Motor 1 save failed: {e}")


@router.put("/combination-ranges")
def save_combination_ranges(body: CombinationRangesUpdate, user_id: str = Depends(get_user_id)):
    """Save Motor 2 combination range rules for a specific profile."""
    db = get_admin_client()
    res = db.table("user_settings").select("combination_ranges").eq("user_id", user_id).maybe_single().execute()
    existing = (res.data or {}).get("combination_ranges") or {}

    if body.profile not in ("conservative", "base", "aggressive"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid profile")

    merged = {**existing, body.profile: body.ranges}

    db.table("user_settings").upsert(
        {"user_id": user_id, "combination_ranges": merged},
        on_conflict="user_id",
    ).execute()
    return {"profile": body.profile, "ranges": body.ranges}
