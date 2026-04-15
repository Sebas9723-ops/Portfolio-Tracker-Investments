"""
Risk metrics: VaR, CVaR, rolling metrics, Sharpe, Sortino, stress tests, correlation.
Ports of compute_var_cvar, compute_rolling_metrics, etc. from app_core.py.
"""
import numpy as np
import pandas as pd
from typing import Optional

from app.models.analytics import VaRResult, StressTestRow, CorrelationMatrix


STRESS_SCENARIOS = {
    "2020 COVID Crash": {"equity": -0.34, "bonds": 0.03, "gold": 0.03},
    "2022 Rate Hike": {"equity": -0.19, "bonds": -0.15, "gold": -0.02},
    "2008 GFC": {"equity": -0.55, "bonds": 0.06, "gold": 0.05},
    "Dot-com 2000": {"equity": -0.49, "bonds": 0.08, "gold": 0.01},
    "+20% Gold Rally": {"equity": -0.05, "bonds": 0.00, "gold": 0.20},
}

ASSET_CLASS_MAP = {
    "VOO": "equity", "QQQM": "equity", "VWCE.DE": "equity",
    "IWDA.AS": "equity", "8RMY.DE": "equity", "EIMI.UK": "equity",
    "GLD": "gold", "IGLN.L": "gold",
}


def compute_var_cvar(
    returns: pd.Series,
    confidence: float = 0.95,
    portfolio_value: float = 100_000,
) -> VaRResult:
    if returns.empty or len(returns) < 20:
        return VaRResult(
            confidence=confidence,
            var_historical=0, var_parametric=0,
            cvar_historical=0, cvar_parametric=0,
            period_days=1,
        )
    r = returns.dropna().values
    alpha = 1 - confidence

    # Historical
    var_h = float(-np.percentile(r, alpha * 100)) * portfolio_value
    losses = r[r < -np.percentile(r, alpha * 100)]
    cvar_h = float(-losses.mean()) * portfolio_value if len(losses) > 0 else var_h

    # Parametric
    mu, sigma = float(r.mean()), float(r.std())
    from scipy.stats import norm
    z = norm.ppf(alpha)
    var_p = float(-(mu + z * sigma)) * portfolio_value
    cvar_p = float(-(mu - sigma * norm.pdf(z) / alpha)) * portfolio_value

    return VaRResult(
        confidence=confidence,
        var_historical=round(var_h, 2),
        var_parametric=round(var_p, 2),
        cvar_historical=round(cvar_h, 2),
        cvar_parametric=round(cvar_p, 2),
        period_days=1,
    )


def compute_rolling_metrics(
    returns: pd.Series,
    window: int = 63,
    risk_free_rate: float = 0.045,
) -> list[dict]:
    if returns.empty or len(returns) < window:
        return []
    rfr_daily = risk_free_rate / 252
    result = []
    for i in range(window, len(returns)):
        window_ret = returns.iloc[i - window:i]
        mu = window_ret.mean()
        sigma = window_ret.std()
        ann_ret = mu * 252
        ann_vol = sigma * np.sqrt(252)
        sharpe = (ann_ret - risk_free_rate) / ann_vol if ann_vol > 0 else 0
        downside = window_ret[window_ret < rfr_daily].std() * np.sqrt(252)
        sortino = (ann_ret - risk_free_rate) / downside if downside > 0 else 0
        cum = (1 + window_ret).cumprod()
        dd = float((cum / cum.cummax() - 1).min())
        result.append({
            "date": str(returns.index[i].date()),
            "sharpe": round(sharpe, 3),
            "sortino": round(sortino, 3),
            "volatility": round(ann_vol * 100, 3),
            "drawdown": round(dd * 100, 3),
        })
    return result


def compute_extended_ratios(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_rate: float = 0.045,
) -> dict:
    if portfolio_returns.empty:
        return {}
    p = portfolio_returns.dropna()
    b = benchmark_returns.dropna().reindex(p.index).dropna()
    p = p.reindex(b.index)

    mu_p = p.mean() * 252
    mu_b = b.mean() * 252
    sigma_p = p.std() * np.sqrt(252)
    rfr_daily = risk_free_rate / 252

    # Beta, Alpha (CAPM)
    cov = np.cov(p.values, b.values)
    beta = cov[0, 1] / cov[1, 1] if cov[1, 1] > 0 else 0
    alpha = mu_p - beta * mu_b

    # Sharpe, Sortino
    sharpe = (mu_p - risk_free_rate) / sigma_p if sigma_p > 0 else 0
    downside = p[p < rfr_daily].std() * np.sqrt(252)
    sortino = (mu_p - risk_free_rate) / downside if downside > 0 else 0

    # Max drawdown
    cum = (1 + p).cumprod()
    max_dd = float((cum / cum.cummax() - 1).min())

    # Calmar
    calmar = -mu_p / max_dd if max_dd < 0 else 0

    # Information ratio
    active = p - b
    te = active.std() * np.sqrt(252)
    ir = (active.mean() * 252) / te if te > 0 else 0

    return {
        "annualized_return": round(mu_p * 100, 2),
        "annualized_vol": round(sigma_p * 100, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_drawdown": round(max_dd * 100, 2),
        "calmar": round(calmar, 3),
        "alpha": round(alpha * 100, 2),
        "beta": round(beta, 3),
        "information_ratio": round(ir, 3),
    }


def compute_stress_tests(
    weights: dict[str, float],
    total_value: float,
) -> list[StressTestRow]:
    results = []
    for scenario, shocks in STRESS_SCENARIOS.items():
        impact = 0.0
        details: dict[str, float] = {}
        for ticker, w in weights.items():
            asset_class = ASSET_CLASS_MAP.get(ticker, "equity")
            shock = shocks.get(asset_class, 0.0)
            ticker_impact = w * shock * total_value
            impact += ticker_impact
            details[ticker] = round(ticker_impact, 2)
        results.append(StressTestRow(
            scenario=scenario,
            portfolio_impact_pct=round(impact / total_value * 100 if total_value else 0, 2),
            portfolio_impact_base=round(impact, 2),
            details=details,
        ))
    return results


def compute_correlation_matrix(
    hist: dict[str, pd.DataFrame],
    tickers: list[str],
) -> CorrelationMatrix:
    closes: dict[str, pd.Series] = {}
    for t in tickers:
        df = hist.get(t, pd.DataFrame())
        if not df.empty:
            col = "Close" if "Close" in df.columns else df.columns[0]
            closes[t] = df[col].dropna()

    if len(closes) < 2:
        return CorrelationMatrix(tickers=tickers, matrix=[[1.0] * len(tickers)] * len(tickers))

    df_all = pd.DataFrame(closes).dropna(how="all").ffill().pct_change().dropna()
    corr = df_all.corr()
    valid_tickers = list(corr.columns)
    matrix = corr.values.tolist()
    return CorrelationMatrix(tickers=valid_tickers, matrix=matrix)


def compute_risk_budget(
    returns: dict[str, pd.Series],
    weights: dict[str, float],
) -> dict[str, float]:
    """Marginal risk contribution per asset."""
    tickers = [t for t in weights if t in returns]
    if not tickers:
        return {}
    df = pd.DataFrame({t: returns[t] for t in tickers}).dropna()
    w = np.array([weights[t] for t in tickers])
    cov = df.cov().values * 252
    port_var = w @ cov @ w
    mrc = cov @ w
    rc = w * mrc / port_var if port_var > 0 else w
    return {t: round(float(rc[i]) * 100, 2) for i, t in enumerate(tickers)}


def compute_fx_exposure(
    portfolio_rows: list[dict],
    base_currency: str = "USD",
) -> dict[str, float]:
    """FX exposure as % of total portfolio value."""
    total = sum(r.get("value_base", 0) for r in portfolio_rows)
    exposure: dict[str, float] = {}
    for row in portfolio_rows:
        ccy = row.get("currency", "USD")
        if ccy == base_currency:
            continue
        exposure[ccy] = exposure.get(ccy, 0) + row.get("value_base", 0)
    return {c: round(v / total * 100, 2) for c, v in exposure.items()} if total else {}
