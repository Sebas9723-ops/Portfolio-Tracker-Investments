from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional
from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client
from app.services.market_data import get_historical_multi, get_risk_free_rate
from app.compute.optimization import simulate_efficient_frontier, optimize_max_sharpe, black_litterman
from app.models.analytics import OptimizationResult
import pandas as pd

router = APIRouter(prefix="/api/optimization", tags=["optimization"])


class OptimizationRequest(BaseModel):
    period: str = "2y"
    n_simulations: int = 3000
    max_single_asset: float = 0.40
    min_bonds: float = 0.0
    min_gold: float = 0.0


@router.post("/frontier", response_model=OptimizationResult)
def frontier(body: OptimizationRequest, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    pos_res = db.table("positions").select("ticker,shares").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
    shares = {p["ticker"]: float(p["shares"]) for p in positions}
    total = sum(shares.values())
    current_weights = {t: shares[t] / total for t in tickers} if total > 0 else {}

    hist = get_historical_multi(tickers, period=body.period)
    rfr = get_risk_free_rate()

    closes: dict[str, pd.Series] = {}
    for t, df in hist.items():
        if not df.empty:
            col = "Close" if "Close" in df.columns else df.columns[0]
            closes[t] = df[col].dropna()

    returns_df = pd.DataFrame(closes).dropna(how="all").ffill().pct_change().dropna()

    return simulate_efficient_frontier(
        returns_df=returns_df,
        risk_free_rate=rfr,
        n_simulations=body.n_simulations,
        max_single_asset=body.max_single_asset,
        current_weights=current_weights,
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

    hist = get_historical_multi(tickers, period=body.period)
    rfr = get_risk_free_rate()
    closes = {t: hist[t]["Close"].dropna() for t in tickers if not hist.get(t, pd.DataFrame()).empty
              and "Close" in hist[t].columns}
    returns_df = pd.DataFrame(closes).dropna(how="all").ffill().pct_change().dropna()
    weights = optimize_max_sharpe(returns_df, rfr, body.max_single_asset)
    return {"weights": weights}
