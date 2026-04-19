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
    if len(r) < 30:
        return VaRResult(
            confidence=confidence,
            var_historical=0, var_parametric=0,
            cvar_historical=0, cvar_parametric=0,
            period_days=1,
        )
    alpha = 1 - confidence

    # Historical
    var_threshold = float(np.percentile(r, alpha * 100))  # e.g. -0.018 at 95%
    var_h = -var_threshold * portfolio_value
    losses = r[r < var_threshold]
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
        below = window_ret[window_ret < rfr_daily]
        downside = float(below.std()) * np.sqrt(252) if len(below) > 1 else 0.0
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
    below_rfr = p[p < rfr_daily]
    downside = float(below_rfr.std()) * np.sqrt(252) if len(below_rfr) > 1 else 0.0
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
        # Build a proper identity matrix — do NOT use [[...]] * n (shared reference).
        n = len(tickers)
        identity = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        return CorrelationMatrix(tickers=tickers, matrix=identity)

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


def compute_extended_ratios_full(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_rate: float = 0.045,
) -> dict:
    """Extended set of performance ratios beyond compute_extended_ratios."""
    from scipy import stats as sp_stats

    if portfolio_returns.empty:
        return {}
    p = portfolio_returns.dropna()
    b = benchmark_returns.dropna().reindex(p.index).dropna()
    p = p.reindex(b.index)
    if len(p) < 20:
        return {}

    rfr_daily = risk_free_rate / 252
    mu_p = p.mean() * 252
    sigma_p = p.std() * np.sqrt(252)

    cov = np.cov(p.values, b.values)
    beta = cov[0, 1] / cov[1, 1] if cov[1, 1] > 0 else 0
    mu_b = b.mean() * 252

    # Treynor ratio
    treynor = (mu_p - risk_free_rate) / beta if beta != 0 else None

    # Omega ratio
    gains = (p[p > rfr_daily] - rfr_daily).sum()
    losses = (rfr_daily - p[p <= rfr_daily]).sum()
    omega = gains / losses if losses > 0 else None

    # Tail ratio: 95th / |5th| percentile
    p95 = float(np.percentile(p.values, 95))
    p05 = float(np.percentile(p.values, 5))
    tail_ratio = p95 / abs(p05) if p05 != 0 else None

    # Higher moments
    skewness = float(sp_stats.skew(p.values))
    kurtosis_excess = float(sp_stats.kurtosis(p.values))

    # Win-rate vs benchmark
    win_rate = float((p > b).mean() * 100)

    # Tracking error + IR
    active = p - b
    te = float(active.std() * np.sqrt(252) * 100)
    ir = (active.mean() * 252) / (active.std() * np.sqrt(252)) if active.std() > 0 else 0

    # Ulcer index
    cum = (1 + p).cumprod()
    dd_pct = (cum / cum.cummax() - 1) * 100
    ulcer = float(np.sqrt((dd_pct ** 2).mean()))

    # Martin ratio
    martin = (mu_p - risk_free_rate) / (ulcer / 100) if ulcer > 0 else None

    # % positive days
    pct_positive_days = float((p > 0).mean() * 100)

    return {
        "treynor": round(float(treynor), 4) if treynor is not None else None,
        "omega": round(float(omega), 4) if omega is not None else None,
        "tail_ratio": round(float(tail_ratio), 4) if tail_ratio is not None else None,
        "skewness": round(skewness, 4),
        "kurtosis": round(kurtosis_excess, 4),
        "pct_positive_days": round(pct_positive_days, 2),
        "tracking_error": round(te, 3),
        "information_ratio": round(float(ir), 3),
        "ulcer_index": round(ulcer, 4),
        "martin_ratio": round(float(martin), 4) if martin is not None else None,
        "win_rate_vs_benchmark": round(win_rate, 2),
        "beta": round(float(beta), 3),
        "ann_return": round(float(mu_p * 100), 2),
        "ann_vol": round(float(sigma_p * 100), 2),
    }


def compute_fama_french(
    portfolio_returns: pd.Series,
    hist: dict[str, pd.DataFrame],
    risk_free_rate: float = 0.045,
) -> dict:
    """
    Fama-French 3-factor regression using ETF proxies:
      Market factor (Mkt-RF): SPY excess return
      Size factor (SMB):      IWM - SPY (small-cap minus large-cap)
      Value factor (HML):     IVE - IVW (value minus growth)
    """
    def _get_ret(ticker: str) -> pd.Series:
        df = hist.get(ticker, pd.DataFrame())
        if df.empty:
            return pd.Series(dtype=float)
        col = "Close" if "Close" in df.columns else df.columns[0]
        return df[col].pct_change().dropna()

    spy = _get_ret("SPY")
    iwm = _get_ret("IWM")
    ive = _get_ret("IVE")
    ivw = _get_ret("IVW")

    rfr_daily = risk_free_rate / 252
    p = portfolio_returns.dropna()

    # Intersect all indices
    common_idx = p.index
    for s in [spy, iwm, ive, ivw]:
        if not s.empty:
            common_idx = common_idx.intersection(s.index)

    if len(common_idx) < 50:
        return {}

    p_exc = p.reindex(common_idx) - rfr_daily
    mkt_rf = spy.reindex(common_idx) - rfr_daily
    smb = iwm.reindex(common_idx) - spy.reindex(common_idx)
    hml = ive.reindex(common_idx) - ivw.reindex(common_idx)

    X = np.column_stack([np.ones(len(common_idx)), mkt_rf.values, smb.values, hml.values])
    y = p_exc.values

    try:
        coeffs, residuals, rank, _ = np.linalg.lstsq(X, y, rcond=None)
        y_pred = X @ coeffs
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r_sq = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        n, k = len(y), 4
        mse = ss_res / max(n - k, 1)
        cov_mat = mse * np.linalg.pinv(X.T @ X)
        se = np.sqrt(np.diag(cov_mat))
        t_stats = coeffs / (se + 1e-12)

        return {
            "alpha_annual": round(float(coeffs[0] * 252 * 100), 3),
            "beta_mkt": round(float(coeffs[1]), 3),
            "beta_smb": round(float(coeffs[2]), 3),
            "beta_hml": round(float(coeffs[3]), 3),
            "r_squared": round(float(r_sq), 4),
            "t_alpha": round(float(t_stats[0]), 3),
            "t_mkt": round(float(t_stats[1]), 3),
            "t_smb": round(float(t_stats[2]), 3),
            "t_hml": round(float(t_stats[3]), 3),
            "n_obs": int(len(common_idx)),
        }
    except Exception:
        return {}


def compute_per_ticker_sharpe(
    hist: dict[str, pd.DataFrame],
    tickers: list[str],
    risk_free_rate: float = 0.045,
) -> dict[str, dict]:
    """Individual Sharpe ratio, annualized return, and vol for each ticker."""
    result = {}
    for ticker in tickers:
        df = hist.get(ticker, pd.DataFrame())
        if df.empty:
            continue
        col = "Close" if "Close" in df.columns else df.columns[0]
        prices = df[col].dropna()
        if len(prices) < 20:
            continue
        r = prices.pct_change().dropna()
        ann_ret = float(r.mean() * 252)
        ann_vol = float(r.std() * np.sqrt(252))
        sharpe = (ann_ret - risk_free_rate) / ann_vol if ann_vol > 0 else 0
        result[ticker] = {
            "ann_return": round(ann_ret * 100, 2),
            "ann_vol": round(ann_vol * 100, 2),
            "sharpe": round(sharpe, 3),
        }
    return result


def compute_vol_regime(
    portfolio_returns: pd.Series,
    window: int = 21,
) -> dict:
    """Rolling volatility with Low / Medium / High regime classification."""
    if portfolio_returns.empty or len(portfolio_returns) < window + 5:
        return {"series": [], "low_threshold": 0, "high_threshold": 0}

    roll_vol = portfolio_returns.rolling(window).std() * np.sqrt(252) * 100
    roll_vol = roll_vol.dropna()

    p33 = float(roll_vol.quantile(0.33))
    p67 = float(roll_vol.quantile(0.67))

    series = []
    for dt, vol in roll_vol.items():
        v = float(vol)
        regime = "low" if v < p33 else ("medium" if v < p67 else "high")
        series.append({"date": str(dt.date()), "vol": round(v, 3), "regime": regime})

    return {"series": series, "low_threshold": round(p33, 3), "high_threshold": round(p67, 3)}


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
