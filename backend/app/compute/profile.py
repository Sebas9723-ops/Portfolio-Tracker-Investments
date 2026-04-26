"""
Investor Profile Engine — Conservative (Max Sharpe), Base (Target Return), Aggressive (Max Return).
Supports BL-adjusted expected returns (mu_override) and parametric CVaR constraint.
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from typing import Literal, Optional

ProfileType = Literal["conservative", "base", "aggressive"]

# z-score for parametric CVaR(95%) under normality
_Z_95 = 1.645

# Per-profile daily CVaR limits (fraction of portfolio value, daily).
# Used when no quant-cache CVaR is available.
_CVAR_LIMIT_DEFAULT = {
    "conservative": 0.010,   # ~2.5% monthly max loss
    "base":         0.015,
    "aggressive":   0.022,
}


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


def _build_combination_scipy_constraints(tickers: list[str], combination_constraints: list[dict]) -> list[dict]:
    """min/max can be None (no bound on that side) or a fraction in [0, 1]."""
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


def _cvar_constraint(mu: np.ndarray, cov: np.ndarray, cvar_limit: float) -> dict:
    """
    Parametric CVaR(95%) constraint (daily, normal approximation):
        CVaR = -mu_daily @ w + z95 * sqrt(w @ cov_daily @ w) <= limit
    Expressed as ineq constraint: limit - CVaR >= 0.
    """
    mu_daily = mu / 252
    cov_daily = cov / 252

    def _fn(w):
        port_ret = mu_daily @ w
        port_vol = np.sqrt(max(float(w @ cov_daily @ w), 1e-12))
        cvar = -port_ret + _Z_95 * port_vol
        return float(cvar_limit - cvar)

    return {"type": "ineq", "fun": _fn}


def optimize_max_sharpe(
    mu: np.ndarray,
    cov: np.ndarray,
    tickers: list[str],
    risk_free_rate: float = 0.045,
    max_single_asset: float = 0.40,
    per_ticker_bounds: Optional[dict[str, tuple[float, float]]] = None,
    combination_constraints: Optional[list[dict]] = None,
    cvar_limit: Optional[float] = None,
) -> dict[str, float]:
    n = len(tickers)
    bounds = _build_bounds(tickers, max_single_asset, per_ticker_bounds)
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    w0 = np.clip(np.ones(n) / n, lo, hi)
    w0 = w0 / w0.sum() if w0.sum() > 0 else np.ones(n) / n
    combo = _build_combination_scipy_constraints(tickers, combination_constraints or [])
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}] + combo
    if cvar_limit is not None:
        constraints.append(_cvar_constraint(mu, cov, cvar_limit))

    def neg_sharpe(w):
        r = w @ mu
        v = np.sqrt(max(float(w @ cov @ w), 1e-12))
        return -(r - risk_free_rate) / v

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
    per_ticker_bounds: Optional[dict[str, tuple[float, float]]] = None,
    combination_constraints: Optional[list[dict]] = None,
    cvar_limit: Optional[float] = None,
) -> dict[str, float]:
    """Min variance with return >= target_return (annualized fraction, e.g. 0.10 = 10%)."""
    n = len(tickers)
    bounds = _build_bounds(tickers, max_single_asset, per_ticker_bounds)
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    w0 = np.clip(np.ones(n) / n, lo, hi)
    w0 = w0 / w0.sum() if w0.sum() > 0 else np.ones(n) / n
    combo = _build_combination_scipy_constraints(tickers, combination_constraints or [])
    constraints = [
        {"type": "eq", "fun": lambda w: np.sum(w) - 1},
        {"type": "ineq", "fun": lambda w: w @ mu - target_return},
    ] + combo
    if cvar_limit is not None:
        constraints.append(_cvar_constraint(mu, cov, cvar_limit))

    def portfolio_var(w):
        return float(w @ cov @ w)

    try:
        res = minimize(portfolio_var, w0, method="SLSQP", bounds=bounds, constraints=constraints,
                       options={"ftol": 1e-10, "maxiter": 1000})
        if res.success:
            w = np.clip(res.x, 0, None)
            w /= w.sum()
            return {t: round(float(w[i]), 4) for i, t in enumerate(tickers)}
        # fallback: relax return constraint
        constraints_relaxed = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}] + combo
        if cvar_limit is not None:
            constraints_relaxed.append(_cvar_constraint(mu, cov, cvar_limit))
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
    per_ticker_bounds: Optional[dict[str, tuple[float, float]]] = None,
    combination_constraints: Optional[list[dict]] = None,
    cvar_limit: Optional[float] = None,
) -> dict[str, float]:
    """Maximize μᵀw subject to CVaR constraint (when provided)."""
    n = len(tickers)
    bounds = _build_bounds(tickers, max_single_asset, per_ticker_bounds)
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    w0 = np.clip(np.ones(n) / n, lo, hi)
    w0 = w0 / w0.sum() if w0.sum() > 0 else np.ones(n) / n
    combo = _build_combination_scipy_constraints(tickers, combination_constraints or [])
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}] + combo
    if cvar_limit is not None:
        constraints.append(_cvar_constraint(mu, cov, cvar_limit))

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
    per_ticker_bounds: Optional[dict[str, tuple[float, float]]] = None,
    combination_constraints: Optional[list[dict]] = None,
    mu_override: Optional[np.ndarray] = None,
    cvar_limit: Optional[float] = None,
) -> dict[str, float]:
    """
    Dispatcher: returns optimal weights for the selected profile.

    mu_override: BL-adjusted expected returns (annualized). When provided,
                 used instead of the historical mean.
    cvar_limit:  Daily CVaR(95%) limit. When provided, added as a constraint
                 to the optimizer. If None, falls back to _CVAR_LIMIT_DEFAULT.
    """
    if returns_df.empty or returns_df.shape[1] < 1:
        return {}

    tickers = list(returns_df.columns)
    mu = mu_override if mu_override is not None else returns_df.mean().values * 252
    cov = returns_df.cov().values * 252

    # Use provided CVaR limit or profile default
    effective_cvar = cvar_limit if cvar_limit is not None else _CVAR_LIMIT_DEFAULT[profile]

    if profile == "conservative":
        return optimize_max_sharpe(
            mu, cov, tickers, risk_free_rate, max_single_asset,
            per_ticker_bounds, combination_constraints, cvar_limit=effective_cvar,
        )
    elif profile == "base":
        return optimize_target_return(
            mu, cov, tickers, target_return, max_single_asset,
            per_ticker_bounds, combination_constraints, cvar_limit=effective_cvar,
        )
    else:  # aggressive
        return optimize_max_return(
            mu, cov, tickers, max_single_asset,
            per_ticker_bounds, combination_constraints, cvar_limit=effective_cvar,
        )


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
