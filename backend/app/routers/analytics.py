from fastapi import APIRouter, Depends, Query
from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client
from app.services.market_data import get_historical_multi, get_risk_free_rate
from app.compute.returns import (
    build_portfolio_returns, compute_twr, compute_monthly_returns,
    compute_drawdown_episodes, cum_return_series,
)
from app.compute.risk import (
    compute_extended_ratios, compute_rolling_metrics,
    compute_extended_ratios_full, compute_fama_french,
    compute_per_ticker_sharpe, compute_vol_regime,
)
from app.models.analytics import AnalyticsResponse, PerformanceMetrics

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _get_positions_and_weights(user_id: str) -> tuple[list[str], dict[str, float]]:
    db = get_admin_client()
    pos_res = db.table("positions").select("ticker,shares").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
    shares = {p["ticker"]: float(p["shares"]) for p in positions}
    total_shares = sum(shares.values())
    weights = {t: shares[t] / total_shares for t in tickers} if total_shares > 0 else {}
    return tickers, weights


@router.get("/performance", response_model=AnalyticsResponse)
def performance(
    period: str = Query(default="2y"),
    benchmark: str = Query(default="VOO"),
    user_id: str = Depends(get_user_id),
):
    db = get_admin_client()
    settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    settings = settings_res.data or {}
    rfr = settings.get("risk_free_rate", get_risk_free_rate())
    rolling_window = int(settings.get("rolling_window", 63))
    bm_ticker = settings.get("preferred_benchmark", benchmark)

    tickers, weights = _get_positions_and_weights(user_id)
    all_tickers = list(set(tickers + [bm_ticker]))

    hist = get_historical_multi(all_tickers, period=period)

    portfolio_returns = build_portfolio_returns(
        {t: hist[t] for t in tickers if t in hist},
        {t: weights.get(t, 0) for t in tickers},
    )
    bm_hist = hist.get(bm_ticker)
    if bm_hist is not None and not bm_hist.empty:
        col = "Close" if "Close" in bm_hist.columns else bm_hist.columns[0]
        bm_returns = bm_hist[col].pct_change().dropna()
    else:
        import pandas as pd
        bm_returns = pd.Series(dtype=float)

    ratios = compute_extended_ratios(portfolio_returns, bm_returns, rfr)
    rolling = compute_rolling_metrics(portfolio_returns, window=rolling_window, risk_free_rate=rfr)

    twr = compute_twr(portfolio_returns)
    monthly = compute_monthly_returns(portfolio_returns, bm_returns)
    drawdowns = compute_drawdown_episodes(portfolio_returns)
    portfolio_series = cum_return_series(portfolio_returns, "Portfolio")
    benchmark_series = cum_return_series(bm_returns, bm_ticker)

    metrics = PerformanceMetrics(
        twr=round(twr * 100, 2),
        mwr=None,
        annualized_return=ratios.get("annualized_return"),
        annualized_vol=ratios.get("annualized_vol"),
        sharpe=ratios.get("sharpe"),
        sortino=ratios.get("sortino"),
        max_drawdown=ratios.get("max_drawdown"),
        calmar=ratios.get("calmar"),
        alpha=ratios.get("alpha"),
        beta=ratios.get("beta"),
        information_ratio=ratios.get("information_ratio"),
        benchmark_ticker=bm_ticker,
        period=period,
    )

    return AnalyticsResponse(
        metrics=metrics,
        rolling=rolling,
        monthly_returns=monthly,
        drawdown_episodes=drawdowns,
        portfolio_series=portfolio_series,
        benchmark_series=benchmark_series,
    )


@router.get("/extended")
def extended_analytics(
    period: str = Query(default="2y"),
    user_id: str = Depends(get_user_id),
):
    """Extended ratios, Fama-French 3-factor, and per-ticker Sharpe."""
    import pandas as pd

    db = get_admin_client()
    settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    settings = settings_res.data or {}
    rfr = float(settings.get("risk_free_rate", get_risk_free_rate()))
    bm_ticker = settings.get("preferred_benchmark", "VOO")

    tickers, weights = _get_positions_and_weights(user_id)
    ff_proxies = ["SPY", "IWM", "IVE", "IVW"]
    all_tickers = list(set(tickers + [bm_ticker] + ff_proxies))

    hist = get_historical_multi(all_tickers, period=period)

    from app.compute.returns import build_portfolio_returns
    portfolio_returns = build_portfolio_returns(
        {t: hist[t] for t in tickers if t in hist},
        {t: weights.get(t, 0) for t in tickers},
    )

    bm_hist = hist.get(bm_ticker)
    if bm_hist is not None and not bm_hist.empty:
        col = "Close" if "Close" in bm_hist.columns else bm_hist.columns[0]
        bm_returns = bm_hist[col].pct_change().dropna()
    else:
        bm_returns = pd.Series(dtype=float)

    extended = compute_extended_ratios_full(portfolio_returns, bm_returns, rfr)
    ff = compute_fama_french(portfolio_returns, hist, rfr)
    per_ticker = compute_per_ticker_sharpe(hist, tickers, rfr)

    return {
        "extended_ratios": extended,
        "fama_french": ff,
        "per_ticker_sharpe": per_ticker,
        "benchmark_ticker": bm_ticker,
    }


@router.get("/vol-regime")
def vol_regime_endpoint(
    period: str = Query(default="2y"),
    window: int = Query(default=21),
    user_id: str = Depends(get_user_id),
):
    """Rolling volatility with Low/Medium/High regime classification."""
    from app.compute.returns import build_portfolio_returns

    tickers, weights = _get_positions_and_weights(user_id)
    hist = get_historical_multi(tickers, period=period)
    portfolio_returns = build_portfolio_returns(
        {t: hist[t] for t in tickers if t in hist},
        {t: weights.get(t, 0) for t in tickers},
    )
    return compute_vol_regime(portfolio_returns, window=window)


@router.post("/backtest-weights")
def backtest_weights(
    body: dict,
    user_id: str = Depends(get_user_id),
):
    """Backtest a set of weights vs the current portfolio over a given period."""
    weights: dict = body.get("weights", {})
    period: str = body.get("period", "1y")

    if not weights:
        return {"optimal_series": [], "current_series": []}

    tickers = list(weights.keys())
    current_tickers, current_weights = _get_positions_and_weights(user_id)
    all_tickers = list(set(tickers + current_tickers))

    hist = get_historical_multi(all_tickers, period=period)

    optimal_returns = build_portfolio_returns(
        {t: hist[t] for t in tickers if t in hist},
        weights,
    )
    current_returns = build_portfolio_returns(
        {t: hist[t] for t in current_tickers if t in hist},
        {t: current_weights.get(t, 0) for t in current_tickers},
    )

    return {
        "optimal_series": cum_return_series(optimal_returns, "Optimal"),
        "current_series": cum_return_series(current_returns, "Current"),
    }
