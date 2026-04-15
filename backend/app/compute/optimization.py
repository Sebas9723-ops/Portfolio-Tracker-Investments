"""
Efficient frontier, Max Sharpe, Min Vol, Risk Parity optimization.
Port of simulate_constrained_efficient_frontier from app_core.py.
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from typing import Optional

from app.models.analytics import FrontierPoint, OptimizationResult


def simulate_efficient_frontier(
    returns_df: pd.DataFrame,
    risk_free_rate: float = 0.045,
    n_simulations: int = 3000,
    max_single_asset: float = 0.40,
    min_bonds: float = 0.0,
    min_gold: float = 0.0,
    current_weights: Optional[dict[str, float]] = None,
) -> OptimizationResult:
    """Monte Carlo efficient frontier simulation."""
    if returns_df.empty or returns_df.shape[1] < 2:
        return OptimizationResult(
            frontier=[], max_sharpe=_empty_point(),
            min_vol=_empty_point(), risk_parity={},
            current_weights=current_weights or {},
            current_metrics={},
        )

    tickers = list(returns_df.columns)
    n = len(tickers)
    mu = returns_df.mean() * 252
    cov = returns_df.cov() * 252

    frontier_points: list[FrontierPoint] = []
    best_sharpe = FrontierPoint(ret=0, vol=1e9, sharpe=-999, weights={})
    best_minvol = FrontierPoint(ret=0, vol=1e9, sharpe=0, weights={})

    rng = np.random.default_rng(42)
    for _ in range(n_simulations):
        w = rng.dirichlet(np.ones(n))
        # Apply constraints
        w = np.clip(w, 0, max_single_asset)
        w /= w.sum()

        port_ret = float(mu.values @ w)
        port_vol = float(np.sqrt(w @ cov.values @ w))
        sharpe = (port_ret - risk_free_rate) / port_vol if port_vol > 0 else 0

        point = FrontierPoint(
            ret=round(port_ret * 100, 3),
            vol=round(port_vol * 100, 3),
            sharpe=round(sharpe, 4),
            weights={t: round(float(w[i]), 4) for i, t in enumerate(tickers)},
        )
        frontier_points.append(point)

        if sharpe > best_sharpe.sharpe:
            best_sharpe = point
        if port_vol < best_minvol.vol:
            best_minvol = point

    # Compute current portfolio metrics
    current_metrics = {}
    if current_weights:
        cw = np.array([current_weights.get(t, 0) for t in tickers])
        if cw.sum() > 0:
            cw /= cw.sum()
            cr = float(mu.values @ cw)
            cv = float(np.sqrt(cw @ cov.values @ cw))
            cs = (cr - risk_free_rate) / cv if cv > 0 else 0
            current_metrics = {
                "return": round(cr * 100, 2),
                "volatility": round(cv * 100, 2),
                "sharpe": round(cs, 3),
            }

    rp_weights = _risk_parity(cov.values, tickers)

    return OptimizationResult(
        frontier=frontier_points,
        max_sharpe=best_sharpe,
        min_vol=best_minvol,
        risk_parity=rp_weights,
        current_weights={t: round(float(current_weights.get(t, 0)), 4) for t in tickers} if current_weights else {},
        current_metrics=current_metrics,
    )


def _risk_parity(cov_matrix: np.ndarray, tickers: list[str]) -> dict[str, float]:
    """Equal risk contribution weights."""
    n = len(tickers)
    w0 = np.ones(n) / n

    def objective(w):
        port_var = w @ cov_matrix @ w
        mrc = cov_matrix @ w
        rc = w * mrc / port_var
        return float(np.sum((rc - rc.mean()) ** 2))

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    bounds = [(0.01, 0.99)] * n
    try:
        result = minimize(objective, w0, method="SLSQP", bounds=bounds, constraints=constraints,
                          options={"ftol": 1e-9, "maxiter": 500})
        w = result.x / result.x.sum()
        return {t: round(float(w[i]), 4) for i, t in enumerate(tickers)}
    except Exception:
        return {t: round(1 / n, 4) for t in tickers}


def _empty_point() -> FrontierPoint:
    return FrontierPoint(ret=0, vol=0, sharpe=0, weights={})


def optimize_max_sharpe(
    returns_df: pd.DataFrame,
    risk_free_rate: float = 0.045,
    max_single_asset: float = 0.40,
) -> dict[str, float]:
    """Scipy-optimized Max Sharpe weights."""
    if returns_df.empty:
        return {}
    tickers = list(returns_df.columns)
    n = len(tickers)
    mu = returns_df.mean().values * 252
    cov = returns_df.cov().values * 252

    def neg_sharpe(w):
        r = w @ mu
        v = np.sqrt(w @ cov @ w)
        return -(r - risk_free_rate) / v if v > 0 else 0

    w0 = np.ones(n) / n
    bounds = [(0, max_single_asset)] * n
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    try:
        res = minimize(neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        w = np.clip(res.x, 0, None)
        w /= w.sum()
        return {t: round(float(w[i]), 4) for i, t in enumerate(tickers)}
    except Exception:
        return {t: round(1 / n, 4) for t in tickers}
