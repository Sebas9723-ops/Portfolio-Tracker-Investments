"""
Investor Profile Engine — Conservative (Max Sharpe), Base (Target Return), Aggressive (Max Return).
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from typing import Literal

ProfileType = Literal["conservative", "base", "aggressive"]


def optimize_max_sharpe(
    mu: np.ndarray,
    cov: np.ndarray,
    tickers: list[str],
    risk_free_rate: float = 0.045,
    max_single_asset: float = 0.40,
) -> dict[str, float]:
    n = len(tickers)
    w0 = np.ones(n) / n
    bounds = [(0.0, max_single_asset)] * n
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]

    def neg_sharpe(w):
        r = w @ mu
        v = np.sqrt(w @ cov @ w)
        return -(r - risk_free_rate) / v if v > 0 else 0.0

    try:
        res = minimize(neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=constraints,
                       options={"ftol": 1e-10, "maxiter": 1000})
        w = np.clip(res.x, 0, None)
        w /= w.sum()
        return {t: round(float(w[i]), 4) for i, t in enumerate(tickers)}
    except Exception:
        return {t: round(1 / n, 4) for t in tickers}


def optimize_target_return(
    mu: np.ndarray,
    cov: np.ndarray,
    tickers: list[str],
    target_return: float,
    max_single_asset: float = 0.40,
) -> dict[str, float]:
    """Min variance with return >= target_return (annualized fraction, e.g. 0.10 = 10%)."""
    n = len(tickers)
    w0 = np.ones(n) / n
    bounds = [(0.0, max_single_asset)] * n
    constraints = [
        {"type": "eq", "fun": lambda w: np.sum(w) - 1},
        {"type": "ineq", "fun": lambda w: w @ mu - target_return},
    ]

    def portfolio_var(w):
        return float(w @ cov @ w)

    try:
        res = minimize(portfolio_var, w0, method="SLSQP", bounds=bounds, constraints=constraints,
                       options={"ftol": 1e-10, "maxiter": 1000})
        if res.success:
            w = np.clip(res.x, 0, None)
            w /= w.sum()
            return {t: round(float(w[i]), 4) for i, t in enumerate(tickers)}
        # fallback: relax return constraint, return min-variance
        constraints_relaxed = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        res2 = minimize(portfolio_var, w0, method="SLSQP", bounds=bounds, constraints=constraints_relaxed,
                        options={"ftol": 1e-10, "maxiter": 1000})
        w = np.clip(res2.x, 0, None)
        w /= w.sum()
        return {t: round(float(w[i]), 4) for i, t in enumerate(tickers)}
    except Exception:
        return {t: round(1 / n, 4) for t in tickers}


def optimize_max_return(
    mu: np.ndarray,
    cov: np.ndarray,
    tickers: list[str],
    max_single_asset: float = 0.40,
) -> dict[str, float]:
    """Maximize μ^T w — concentrates on highest-return asset up to max_single_asset cap."""
    n = len(tickers)
    w0 = np.ones(n) / n
    bounds = [(0.0, max_single_asset)] * n
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]

    def neg_return(w):
        return -float(w @ mu)

    try:
        res = minimize(neg_return, w0, method="SLSQP", bounds=bounds, constraints=constraints,
                       options={"ftol": 1e-10, "maxiter": 1000})
        w = np.clip(res.x, 0, None)
        w /= w.sum()
        return {t: round(float(w[i]), 4) for i, t in enumerate(tickers)}
    except Exception:
        return {t: round(1 / n, 4) for t in tickers}


def compute_profile_weights(
    returns_df: pd.DataFrame,
    profile: ProfileType,
    risk_free_rate: float = 0.045,
    target_return: float = 0.08,
    max_single_asset: float = 0.40,
) -> dict[str, float]:
    """Dispatcher: returns optimal weights for the selected profile."""
    if returns_df.empty or returns_df.shape[1] < 1:
        return {}

    tickers = list(returns_df.columns)
    mu = returns_df.mean().values * 252
    cov = returns_df.cov().values * 252

    if profile == "conservative":
        return optimize_max_sharpe(mu, cov, tickers, risk_free_rate, max_single_asset)
    elif profile == "base":
        return optimize_target_return(mu, cov, tickers, target_return, max_single_asset)
    else:  # aggressive
        return optimize_max_return(mu, cov, tickers, max_single_asset)


def compute_profile_metrics(
    returns_df: pd.DataFrame,
    weights: dict[str, float],
    risk_free_rate: float = 0.045,
) -> dict:
    """Compute ann_return, ann_vol, sharpe, max_drawdown for a given weight set."""
    if returns_df.empty or not weights:
        return {}

    tickers = [t for t in weights if t in returns_df.columns]
    if not tickers:
        return {}

    w = np.array([weights[t] for t in tickers])
    w = w / w.sum()

    sub = returns_df[tickers].dropna(how="all").ffill()
    port_returns = sub.values @ w

    mu = returns_df[tickers].mean().values * 252
    cov = returns_df[tickers].cov().values * 252
    ann_return = float(mu @ w)
    ann_vol = float(np.sqrt(w @ cov @ w))
    sharpe = (ann_return - risk_free_rate) / ann_vol if ann_vol > 0 else 0.0

    # Max drawdown on portfolio return series
    cum = np.cumprod(1 + port_returns)
    running_max = np.maximum.accumulate(cum)
    drawdowns = (cum - running_max) / running_max
    max_dd = float(drawdowns.min())

    return {
        "ann_return": round(ann_return * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(max_dd * 100, 2),
    }
