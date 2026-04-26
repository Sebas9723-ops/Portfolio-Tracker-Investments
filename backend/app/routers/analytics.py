from fastapi import APIRouter, Depends, Query
from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client
from app.services.market_data import get_historical_multi, get_risk_free_rate, get_quotes
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
from app.db.quant_results import load_latest_quant_result

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


@router.get("/equity-curve")
def equity_curve(
    period: str = Query(default="1y"),
    user_id: str = Depends(get_user_id),
):
    """
    Returns daily portfolio value history from portfolio_snapshots.
    Used for the equity curve chart on the analytics page.
    """
    import pandas as pd
    from datetime import date, timedelta

    period_days = {"6m": 180, "1y": 365, "2y": 730, "3y": 1095, "all": 9999}
    days = period_days.get(period, 365)
    since = str(date.today() - timedelta(days=days))

    db = get_admin_client()
    res = (
        db.table("portfolio_snapshots")
        .select("snapshot_date,total_value_base,invested_base,base_currency")
        .eq("user_id", user_id)
        .gte("snapshot_date", since)
        .order("snapshot_date", desc=False)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return {"series": [], "base_currency": "USD"}

    base_currency = rows[0].get("base_currency", "USD")
    series = []
    for r in rows:
        val = float(r.get("total_value_base") or 0)
        inv = float(r.get("invested_base") or 0)
        pnl = val - inv if inv > 0 else None
        pnl_pct = (pnl / inv * 100) if inv > 0 and pnl is not None else None
        series.append({
            "date": r["snapshot_date"],
            "value": round(val, 2),
            "invested": round(inv, 2) if inv > 0 else None,
            "pnl": round(pnl, 2) if pnl is not None else None,
            "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        })

    return {"series": series, "base_currency": base_currency}


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


@router.get("/tax-loss")
def tax_loss_harvesting(
    loss_threshold_pct: float = Query(default=5.0),
    user_id: str = Depends(get_user_id),
):
    """
    Returns positions with unrealized losses exceeding loss_threshold_pct.
    Flags wash-sale risk if a similar asset was bought within 30 days.
    """
    import pandas as pd
    from datetime import date, timedelta

    db = get_admin_client()

    # Load positions with avg cost and current price
    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    settings_res = db.table("user_settings").select("base_currency").eq("user_id", user_id).maybe_single().execute()
    base_currency = (settings_res.data or {}).get("base_currency", "USD")

    if not positions:
        return {"candidates": [], "base_currency": base_currency}

    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
    if not tickers:
        return {"candidates": [], "base_currency": base_currency}

    quotes = get_quotes(tickers)

    # Load recent transactions to check wash-sale window (30 days)
    cutoff = str(date.today() - timedelta(days=30))
    tx_res = (
        db.table("transactions")
        .select("ticker,type,date")
        .eq("user_id", user_id)
        .gte("date", cutoff)
        .execute()
    )
    recent_buys: set[str] = {
        tx["ticker"] for tx in (tx_res.data or [])
        if tx.get("type") in ("buy", "BUY")
    }

    candidates = []
    for p in positions:
        ticker = p["ticker"]
        shares = float(p.get("shares") or 0)
        avg_cost = float(p.get("avg_cost") or p.get("average_cost") or 0)
        if shares <= 0 or avg_cost <= 0:
            continue

        current_price = float(quotes.get(ticker, {}).get("price") or 0)
        if current_price <= 0:
            continue

        cost_basis = avg_cost * shares
        current_value = current_price * shares
        unrealized_pnl = current_value - cost_basis
        unrealized_pct = (unrealized_pnl / cost_basis) * 100 if cost_basis > 0 else 0

        if unrealized_pct < -loss_threshold_pct:
            wash_sale_risk = ticker in recent_buys
            candidates.append({
                "ticker": ticker,
                "shares": round(shares, 4),
                "avg_cost": round(avg_cost, 4),
                "current_price": round(current_price, 4),
                "cost_basis": round(cost_basis, 2),
                "current_value": round(current_value, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "unrealized_pct": round(unrealized_pct, 2),
                "wash_sale_risk": wash_sale_risk,
                "wash_sale_note": "Bought within 30 days — IRS wash-sale rule may apply" if wash_sale_risk else None,
                "action": "Consider harvesting loss to offset capital gains" if not wash_sale_risk else "Wait 31+ days from last buy before harvesting",
            })

    candidates.sort(key=lambda c: c["unrealized_pct"])
    return {"candidates": candidates, "base_currency": base_currency}


@router.get("/vs-benchmark")
def vs_benchmark(
    period: str = Query(default="1y"),
    benchmark: str = Query(default="VOO"),
    user_id: str = Depends(get_user_id),
):
    """
    Portfolio equity curve vs benchmark, both normalized to 100 at portfolio inception.
    Uses portfolio_snapshots for portfolio values; fetches benchmark via yfinance.
    Returns: {series: [{date, portfolio, benchmark, alpha}], inception_date, base_currency, benchmark_ticker, alpha_total}
    """
    import pandas as pd
    from datetime import date, timedelta

    period_days = {"6m": 180, "1y": 365, "2y": 730, "3y": 1095, "all": 9999}
    days = period_days.get(period, 365)
    since = str(date.today() - timedelta(days=days))

    db = get_admin_client()
    res = (
        db.table("portfolio_snapshots")
        .select("snapshot_date,total_value_base,base_currency")
        .eq("user_id", user_id)
        .gte("snapshot_date", since)
        .order("snapshot_date", desc=False)
        .execute()
    )
    rows = res.data or []
    if len(rows) < 2:
        return {"series": [], "inception_date": None, "base_currency": "USD", "benchmark_ticker": benchmark, "alpha_total": 0.0}

    base_currency = rows[0].get("base_currency", "USD")
    inception_date = rows[0]["snapshot_date"]

    # Portfolio normalized series
    port_vals = {r["snapshot_date"]: float(r["total_value_base"]) for r in rows}
    port_base = port_vals[inception_date]

    # Fetch benchmark prices for same period
    bm_hist = get_historical_multi([benchmark], period=period)
    bm_df = bm_hist.get(benchmark)
    bm_series: dict[str, float] = {}
    if bm_df is not None and not bm_df.empty:
        col = "Close" if "Close" in bm_df.columns else bm_df.columns[0]
        # Filter to dates >= inception_date
        bm_filtered = bm_df[col].dropna()
        bm_filtered = bm_filtered[bm_filtered.index >= pd.Timestamp(inception_date)]
        if not bm_filtered.empty:
            bm_base = float(bm_filtered.iloc[0])
            for ts, v in bm_filtered.items():
                bm_series[str(ts.date())] = float(v) / bm_base * 100.0

    # Merge and build output
    all_dates = sorted(set(list(port_vals.keys()) + list(bm_series.keys())))
    series = []
    last_port = None
    last_bm = None
    for d in all_dates:
        if d < inception_date:
            continue
        port_norm = (port_vals[d] / port_base * 100.0) if d in port_vals else last_port
        bm_norm = bm_series.get(d, last_bm)
        if port_norm is not None:
            last_port = port_norm
        if bm_norm is not None:
            last_bm = bm_norm
        if port_norm is None and bm_norm is None:
            continue
        alpha = round(float(port_norm or 100) - float(bm_norm or 100), 4) if (port_norm and bm_norm) else None
        series.append({
            "date": d,
            "portfolio": round(float(port_norm), 4) if port_norm is not None else None,
            "benchmark": round(float(bm_norm), 4) if bm_norm is not None else None,
            "alpha": alpha,
        })

    # Only keep dates where we have at least portfolio data
    series = [s for s in series if s["portfolio"] is not None]
    alpha_total = None
    if series and series[-1]["benchmark"] is not None:
        alpha_total = round(series[-1]["portfolio"] - series[-1]["benchmark"], 4)

    return {
        "series": series,
        "inception_date": inception_date,
        "base_currency": base_currency,
        "benchmark_ticker": benchmark,
        "alpha_total": alpha_total,
    }


@router.get("/recommendations")
def recommendations(
    user_id: str = Depends(get_user_id),
):
    """
    Returns actionable recommendation cards based on latest quant result + portfolio state.
    Each card has: type, title, body, severity ("info"|"warning"|"action"), ticker (optional)
    """
    import pandas as pd

    cards = []
    db = get_admin_client()

    # Load settings
    settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    settings = settings_res.data or {}
    threshold = float(settings.get("rebalancing_threshold", 0.05))
    profile = settings.get("investor_profile", "base")

    # Load current portfolio
    tickers, weights = _get_positions_and_weights(user_id)
    if not tickers:
        return {"cards": [], "generated_at": None}

    # Load quant result
    qr = load_latest_quant_result(user_id)
    regime = None
    optimal_weights: dict[str, float] = {}
    corr_alerts = []
    if qr:
        regime = qr.get("regime")
        optimal_weights = qr.get("optimal_weights") or {}
        corr_alerts = qr.get("correlation_alerts") or []
        generated_at = qr.get("timestamp")

        # Regime card
        regime_labels = {
            "bull_strong": ("Bull Market — Strong", "info"),
            "bull_weak":   ("Bull Market — Weak",   "info"),
            "bear_mild":   ("Bear Market",           "warning"),
            "crisis":      ("Crisis Regime Detected","warning"),
        }
        label, sev = regime_labels.get(regime, (regime or "Unknown", "info"))
        conf = float(qr.get("regime_confidence") or 0) * 100
        cards.append({
            "type": "regime",
            "title": f"Market Regime: {label}",
            "body": f"HMM model confidence: {conf:.0f}%. Expected Sharpe: {float(qr.get('expected_sharpe') or 0):.2f}. Profile: {profile}.",
            "severity": sev,
            "ticker": None,
        })

        # Correlation alert cards
        for alert in corr_alerts[:3]:
            ta = alert.get("ticker_a", "")
            tb = alert.get("ticker_b", "")
            corr = float(alert.get("correlation") or 0)
            cards.append({
                "type": "correlation",
                "title": f"High Correlation: {ta} \u2194 {tb}",
                "body": f"Correlation {corr:.2f} \u2014 consider reducing one to improve diversification.",
                "severity": "warning",
                "ticker": ta,
            })
    else:
        generated_at = None

    # Drift cards — compare current vs optimal
    if optimal_weights:
        all_t = set(list(weights.keys()) + list(optimal_weights.keys()))
        for t in all_t:
            cw = weights.get(t, 0.0)
            ow = optimal_weights.get(t, 0.0)
            drift = ow - cw
            if abs(drift) > threshold:
                direction = "underweight" if drift > 0 else "overweight"
                sev = "action" if abs(drift) > threshold * 2 else "warning"
                cards.append({
                    "type": "drift",
                    "title": f"{t} \u2014 {direction.capitalize()} by {abs(drift)*100:.1f}%",
                    "body": f"Current: {cw*100:.1f}% | Target: {ow*100:.1f}%. Consider {'buying' if drift > 0 else 'trimming'} {t}.",
                    "severity": sev,
                    "ticker": t,
                })

    # Sort: action > warning > info
    _sev_order = {"action": 0, "warning": 1, "info": 2}
    cards.sort(key=lambda c: _sev_order.get(c["severity"], 3))

    return {"cards": cards[:10], "generated_at": generated_at}
