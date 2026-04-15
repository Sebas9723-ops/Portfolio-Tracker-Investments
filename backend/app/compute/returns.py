"""
Portfolio return series computation.
Ports of: build_portfolio_returns, compute_twr, compute_mwr, monthly_returns_calendar,
compute_drawdown_episodes from app_core.py.
"""
import numpy as np
import pandas as pd
from typing import Optional


def build_portfolio_returns(
    hist: dict[str, pd.DataFrame],
    weights: dict[str, float],
) -> pd.Series:
    """
    Build daily portfolio return series from historical price DataFrames.
    weights: {ticker: weight_fraction} (should sum to 1)
    """
    closes: dict[str, pd.Series] = {}
    for ticker, df in hist.items():
        if df.empty:
            continue
        col = "Close" if "Close" in df.columns else df.columns[0]
        closes[ticker] = df[col].dropna()

    if not closes:
        return pd.Series(dtype=float)

    # Align on common dates
    df_all = pd.DataFrame(closes).dropna(how="all").ffill()
    returns = df_all.pct_change().dropna()

    portfolio_returns = pd.Series(0.0, index=returns.index)
    for ticker, w in weights.items():
        if ticker in returns.columns:
            portfolio_returns += returns[ticker] * w

    return portfolio_returns


def compute_twr(portfolio_returns: pd.Series) -> float:
    """Time-Weighted Return (chain-linked)."""
    if portfolio_returns.empty:
        return 0.0
    return float((1 + portfolio_returns).prod() - 1)


def compute_mwr(
    snapshots: list[dict],
) -> Optional[float]:
    """
    Money-Weighted Return (XIRR approximation via numpy).
    snapshots: list of {date, total_value_base, cash_flow} dicts
    """
    if len(snapshots) < 2:
        return None
    try:
        from scipy.optimize import brentq
        dates = [pd.Timestamp(s["snapshot_date"]) for s in snapshots]
        values = [float(s["total_value_base"]) for s in snapshots]
        t0 = dates[0]
        days = [(d - t0).days / 365.25 for d in dates]

        def npv(r):
            return sum(v / (1 + r) ** t for v, t in zip(values, days))

        try:
            mwr = brentq(npv, -0.99, 10.0)
            return float(mwr)
        except ValueError:
            return None
    except Exception:
        return None


def compute_monthly_returns(
    portfolio_returns: pd.Series,
    benchmark_returns: Optional[pd.Series] = None,
) -> list[dict]:
    """Returns list of {year, month, portfolio_return, benchmark_return}."""
    if portfolio_returns.empty:
        return []
    monthly = portfolio_returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    result = []
    for dt, ret in monthly.items():
        bret = None
        if benchmark_returns is not None and not benchmark_returns.empty:
            bm = benchmark_returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)
            bret = float(bm.get(dt, np.nan))
            if np.isnan(bret):
                bret = None
        result.append({
            "year": dt.year,
            "month": dt.month,
            "portfolio_return": float(ret),
            "benchmark_return": bret,
        })
    return result


def compute_drawdown_series(portfolio_returns: pd.Series) -> pd.Series:
    """Underwater equity curve (drawdown at each point)."""
    if portfolio_returns.empty:
        return pd.Series(dtype=float)
    cum = (1 + portfolio_returns).cumprod()
    rolling_max = cum.cummax()
    return (cum / rolling_max) - 1


def compute_drawdown_episodes(portfolio_returns: pd.Series) -> list[dict]:
    """Find top-5 drawdown episodes."""
    dd = compute_drawdown_series(portfolio_returns)
    if dd.empty:
        return []

    episodes = []
    in_drawdown = False
    start = None
    trough_date = None
    trough_depth = 0.0

    for date, val in dd.items():
        if val < 0:
            if not in_drawdown:
                in_drawdown = True
                start = date
                trough_date = date
                trough_depth = val
            elif val < trough_depth:
                trough_depth = val
                trough_date = date
        else:
            if in_drawdown:
                episodes.append({
                    "start": str(start.date()),
                    "trough": str(trough_date.date()),
                    "end": str(date.date()),
                    "depth": round(trough_depth * 100, 2),
                    "duration_days": (date - start).days,
                    "recovery_days": (date - trough_date).days,
                })
                in_drawdown = False

    if in_drawdown and start:
        episodes.append({
            "start": str(start.date()),
            "trough": str(trough_date.date()),
            "end": None,
            "depth": round(trough_depth * 100, 2),
            "duration_days": (dd.index[-1] - start).days,
            "recovery_days": None,
        })

    episodes.sort(key=lambda e: e["depth"])
    return episodes[:10]


def cum_return_series(portfolio_returns: pd.Series, label: str = "Portfolio") -> list[dict]:
    """Cumulative return series for charting."""
    if portfolio_returns.empty:
        return []
    cum = (1 + portfolio_returns).cumprod() - 1
    return [{"date": str(d.date()), "value": round(float(v) * 100, 4), "label": label}
            for d, v in cum.items()]
