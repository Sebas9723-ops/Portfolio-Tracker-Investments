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
    per_ticker_bounds: Optional[dict[str, tuple[float, float]]] = None,
    combination_constraints: Optional[list[dict]] = None,
) -> OptimizationResult:
    """Monte Carlo efficient frontier simulation."""
    if returns_df.empty or returns_df.shape[1] < 2:
        return OptimizationResult(
            frontier=[], max_sharpe=_empty_point(),
            min_vol=_empty_point(), max_return=_empty_point(),
            risk_parity={}, current_weights=current_weights or {},
            current_metrics={},
        )

    tickers = list(returns_df.columns)
    n = len(tickers)
    mu = returns_df.mean() * 252
    cov = returns_df.cov() * 252

    # Build per-ticker bounds for simulation
    lower_bounds = np.array([
        per_ticker_bounds[t][0] if per_ticker_bounds and t in per_ticker_bounds else 0.0
        for t in tickers
    ])
    upper_bounds = np.array([
        per_ticker_bounds[t][1] if per_ticker_bounds and t in per_ticker_bounds else max_single_asset
        for t in tickers
    ])

    frontier_points: list[FrontierPoint] = []
    best_sharpe = FrontierPoint(ret=0, vol=1e9, sharpe=-999, weights={})
    best_minvol = FrontierPoint(ret=0, vol=1e9, sharpe=0, weights={})
    best_maxret = FrontierPoint(ret=-1e9, vol=0, sharpe=0, weights={})

    rng = np.random.default_rng(42)
    for _ in range(n_simulations):
        w = rng.dirichlet(np.ones(n))
        w = np.clip(w, lower_bounds, upper_bounds)
        if w.sum() == 0:
            continue
        w /= w.sum()
        # Re-enforce bounds after normalization (floors may be violated after renorm)
        w = np.clip(w, lower_bounds, upper_bounds)
        if w.sum() == 0:
            continue
        w /= w.sum()

        # Filter portfolios that violate combination constraints (2% tolerance)
        if combination_constraints:
            skip = False
            for rule in combination_constraints:
                rule_tickers = rule.get("tickers", [])
                raw_min = rule.get("min")
                raw_max = rule.get("max")
                indices = [i for i, t in enumerate(tickers) if t in rule_tickers]
                if indices:
                    total = sum(w[i] for i in indices)
                    if raw_min is not None and total < float(raw_min) - 0.02:
                        skip = True
                        break
                    if raw_max is not None and total > float(raw_max) + 0.02:
                        skip = True
                        break
            if skip:
                continue

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
        if port_ret > best_maxret.ret:
            best_maxret = point

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

    # Exact Max Sharpe via scipy (overrides Monte Carlo best)
    ms_row = optimize_max_sharpe(returns_df, risk_free_rate, max_single_asset, per_ticker_bounds, combination_constraints)
    if ms_row:
        w_arr = np.array([ms_row.get(t, 0.0) for t in tickers])
        ms_ret = float(mu.values @ w_arr) * 100
        ms_vol = float(np.sqrt(w_arr @ cov.values @ w_arr)) * 100
        ms_shr = (ms_ret - risk_free_rate * 100) / ms_vol if ms_vol > 0 else 0
        best_sharpe = FrontierPoint(
            ret=round(ms_ret, 3), vol=round(ms_vol, 3),
            sharpe=round(ms_shr, 4), weights={t: round(float(ms_row.get(t, 0)), 4) for t in tickers},
        )

    # Exact Max Return via scipy (overrides Monte Carlo best)
    mr_row = optimize_max_return(returns_df, risk_free_rate, max_single_asset, per_ticker_bounds, combination_constraints)
    if mr_row:
        w_arr = np.array([mr_row.get(t, 0.0) for t in tickers])
        mr_ret = float(mu.values @ w_arr) * 100
        mr_vol = float(np.sqrt(w_arr @ cov.values @ w_arr)) * 100
        mr_shr = (mr_ret - risk_free_rate * 100) / mr_vol if mr_vol > 0 else 0
        best_maxret = FrontierPoint(
            ret=round(mr_ret, 3), vol=round(mr_vol, 3),
            sharpe=round(mr_shr, 4), weights={t: round(float(mr_row.get(t, 0)), 4) for t in tickers},
        )

    return OptimizationResult(
        frontier=frontier_points,
        max_sharpe=best_sharpe,
        min_vol=best_minvol,
        max_return=best_maxret,
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


def black_litterman(
    returns_df: pd.DataFrame,
    views: dict[str, float],          # ticker → expected annual return (e.g. 0.12 = 12%)
    tau: float = 0.05,
    risk_aversion: float = 3.0,
    max_single_asset: float = 0.40,
    per_ticker_bounds: Optional[dict[str, tuple[float, float]]] = None,
) -> dict[str, float]:
    """
    Black-Litterman optimization.
    Uses equal-weight market portfolio as prior.
    Views are absolute: user specifies expected annual return per ticker.
    Returns optimal weights dict.
    """
    if returns_df.empty or returns_df.shape[1] < 2:
        return {}

    tickers = list(returns_df.columns)
    n = len(tickers)
    cov = returns_df.cov().values * 252  # annualized covariance

    # Prior: market equilibrium with equal weights
    w_eq = np.ones(n) / n
    pi = risk_aversion * cov @ w_eq  # implied equilibrium returns

    if not views:
        # No views → optimize on equilibrium returns
        mu_bl = pi
    else:
        # Build P (views matrix) and q (views vector) for absolute views
        view_tickers = [t for t in views if t in tickers]
        k = len(view_tickers)
        if k == 0:
            mu_bl = pi
        else:
            P = np.zeros((k, n))
            q = np.zeros(k)
            for i, t in enumerate(view_tickers):
                j = tickers.index(t)
                P[i, j] = 1.0
                q[i] = views[t]

            # Uncertainty: proportional to variance of view assets
            omega = np.diag([tau * cov[tickers.index(t), tickers.index(t)] for t in view_tickers])

            tau_sigma = tau * cov
            try:
                inv_tau_sigma = np.linalg.inv(tau_sigma)
                inv_omega = np.linalg.inv(omega)
                M = inv_tau_sigma + P.T @ inv_omega @ P
                mu_bl = np.linalg.solve(M, inv_tau_sigma @ pi + P.T @ inv_omega @ q)
            except np.linalg.LinAlgError:
                mu_bl = pi

    # Optimize max Sharpe with BL expected returns
    def neg_sharpe(w: np.ndarray) -> float:
        r = float(mu_bl @ w)
        v = float(np.sqrt(w @ cov @ w))
        return -(r - 0.045) / v if v > 0 else 0.0

    bounds = _build_bounds(tickers, max_single_asset, per_ticker_bounds)
    w0 = _make_w0(n, bounds)
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    try:
        res = minimize(neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=constraints,
                       options={"ftol": 1e-9, "maxiter": 1000})
        w = np.clip(res.x, 0, None)
        w /= w.sum()
        return {t: round(float(w[i]), 4) for i, t in enumerate(tickers)}
    except Exception:
        return {t: round(1 / n, 4) for t in tickers}


def _empty_point() -> FrontierPoint:
    return FrontierPoint(ret=0, vol=0, sharpe=0, weights={})


def _build_combination_scipy_constraints(tickers: list[str], combination_constraints: list[dict]) -> list[dict]:
    """Convert combination range rules to scipy inequality constraints.
    min/max can be None (no bound on that side) or a fraction in [0, 1].
    """
    constraints = []
    for rule in combination_constraints:
        rule_tickers = rule.get("tickers", [])
        raw_min = rule.get("min")
        raw_max = rule.get("max")
        indices = [i for i, t in enumerate(tickers) if t in rule_tickers]
        if not indices:
            continue
        if raw_min is not None:
            min_w = float(raw_min)
            constraints.append({
                "type": "ineq",
                "fun": lambda w, idx=indices, m=min_w: sum(w[i] for i in idx) - m,
            })
        if raw_max is not None:
            max_w = float(raw_max)
            constraints.append({
                "type": "ineq",
                "fun": lambda w, idx=indices, m=max_w: m - sum(w[i] for i in idx),
            })
    return constraints


def optimize_max_sharpe(
    returns_df: pd.DataFrame,
    risk_free_rate: float = 0.045,
    max_single_asset: float = 0.40,
    per_ticker_bounds: Optional[dict[str, tuple[float, float]]] = None,
    combination_constraints: Optional[list[dict]] = None,
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

    bounds = _build_bounds(tickers, max_single_asset, per_ticker_bounds)
    w0 = _make_w0(n, bounds)
    combo_constraints = _build_combination_scipy_constraints(tickers, combination_constraints or [])
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}] + combo_constraints
    try:
        res = minimize(neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        w = np.clip(res.x, 0, None)
        w /= w.sum()
        return {t: round(float(w[i]), 4) for i, t in enumerate(tickers)}
    except Exception:
        return {t: round(1 / n, 4) for t in tickers}


def optimize_max_return(
    returns_df: pd.DataFrame,
    risk_free_rate: float = 0.045,
    max_single_asset: float = 0.40,
    per_ticker_bounds: Optional[dict[str, tuple[float, float]]] = None,
    combination_constraints: Optional[list[dict]] = None,
) -> dict[str, float]:
    """Scipy-optimized maximum-return portfolio."""
    if returns_df.empty:
        return {}
    tickers = list(returns_df.columns)
    n = len(tickers)
    mu = returns_df.mean().values * 252

    def neg_return(w):
        return -float(w @ mu)

    bounds = _build_bounds(tickers, max_single_asset, per_ticker_bounds)
    w0 = _make_w0(n, bounds)
    combo_constraints = _build_combination_scipy_constraints(tickers, combination_constraints or [])
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}] + combo_constraints
    try:
        res = minimize(neg_return, w0, method="SLSQP", bounds=bounds, constraints=constraints,
                       options={"ftol": 1e-12, "maxiter": 1000})
        w = np.clip(res.x, 0, None)
        w /= w.sum()
        return {t: round(float(w[i]), 4) for i, t in enumerate(tickers)}
    except Exception:
        return {t: round(1 / n, 4) for t in tickers}


def _build_bounds(
    tickers: list[str],
    max_single_asset: float,
    per_ticker_bounds: Optional[dict[str, tuple[float, float]]],
) -> list[tuple[float, float]]:
    bounds = []
    for t in tickers:
        if per_ticker_bounds and t in per_ticker_bounds:
            bounds.append(per_ticker_bounds[t])
        else:
            bounds.append((0.0, max_single_asset))
    return bounds


def _make_w0(n: int, bounds: list[tuple[float, float]]) -> np.ndarray:
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    w0 = np.clip(np.ones(n) / n, lo, hi)
    return w0 / w0.sum() if w0.sum() > 0 else np.ones(n) / n
