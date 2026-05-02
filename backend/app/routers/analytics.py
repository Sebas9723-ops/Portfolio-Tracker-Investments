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


@router.get("/health-score")
def health_score(
    period: str = Query(default="1y"),
    user_id: str = Depends(get_user_id),
):
    """
    Composite portfolio health score 0–100 with 4 equal components (25pts each):
      - Sharpe (0–2 mapped to 0–25)
      - Diversification via HHI (lower = better)
      - CVaR headroom vs profile limit
      - Drift from optimal weights
    Returns {score, grade, components: {sharpe, diversification, cvar, drift}}
    """
    import pandas as pd

    db = get_admin_client()
    settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    settings = settings_res.data or {}
    rfr = float(settings.get("risk_free_rate") or get_risk_free_rate())
    profile = settings.get("investor_profile", "base")
    threshold = float(settings.get("rebalancing_threshold", 0.05))

    tickers, weights = _get_positions_and_weights(user_id)
    if not tickers:
        return {"score": None, "grade": None, "components": {}}

    hist = get_historical_multi(tickers, period=period)
    port_returns = build_portfolio_returns(
        {t: hist[t] for t in tickers if t in hist}, weights
    )

    # Component 1: Sharpe (0-25 pts). Sharpe >=2 = 25pts, <=0 = 0pts
    bm_returns = pd.Series(dtype=float)
    ratios = compute_extended_ratios(port_returns, bm_returns, rfr)
    sharpe = float(ratios.get("sharpe") or 0)
    sharpe_score = round(min(25.0, max(0.0, sharpe / 2.0 * 25.0)), 1)

    # Component 2: Diversification via HHI (0-25 pts). HHI=1/n is perfect, HHI=1 is concentrated
    w_vals = list(weights.values())
    hhi = sum(w**2 for w in w_vals)  # 1/n (perfect) to 1 (all in one)
    hhi_min = 1.0 / len(w_vals) if w_vals else 1.0
    # Normalize: hhi=hhi_min → 25pts, hhi=1 → 0pts
    div_score = round(max(0.0, (1.0 - hhi) / (1.0 - hhi_min) * 25.0) if hhi_min < 1 else 0.0, 1)

    # Component 3: CVaR headroom vs profile CVaR limit (0-25 pts)
    # Profile CVaR daily limits: conservative=1%, base=1.5%, aggressive=2.5%
    cvar_limits = {"conservative": 0.010, "base": 0.015, "aggressive": 0.025}
    cvar_limit = cvar_limits.get(profile, 0.015)
    qr = load_latest_quant_result(user_id)
    cvar_actual = abs(float((qr or {}).get("cvar_95") or cvar_limit))
    # headroom: 0 CVaR → 25pts, at/beyond limit → 0pts
    cvar_score = round(max(0.0, min(25.0, (1.0 - cvar_actual / cvar_limit) * 25.0)) if cvar_actual < cvar_limit * 2 else 0.0, 1)

    # Component 4: Drift from optimal weights (0-25 pts)
    optimal = (qr or {}).get("optimal_weights") or {}
    total_drift = 0.0
    if optimal:
        total_drift = sum(abs(weights.get(t, 0) - float(optimal.get(t, 0))) for t in set(list(weights.keys()) + list(optimal.keys())))
        # Perfect drift=0 → 25pts, drift>=0.5 total → 0pts
        drift_score = round(max(0.0, (1.0 - total_drift / 0.5) * 25.0), 1)
    else:
        drift_score = 12.5  # neutral if no quant result yet

    total = round(sharpe_score + div_score + cvar_score + drift_score, 1)

    def _grade(s):
        if s >= 85: return "A"
        if s >= 70: return "B"
        if s >= 55: return "C"
        if s >= 40: return "D"
        return "F"

    return {
        "score": total,
        "grade": _grade(total),
        "components": {
            "sharpe":          {"score": sharpe_score, "label": "Sharpe Ratio",     "detail": f"Sharpe {sharpe:.2f}"},
            "diversification": {"score": div_score,    "label": "Diversification",  "detail": f"HHI {hhi:.3f}"},
            "cvar":            {"score": cvar_score,   "label": "CVaR Headroom",    "detail": f"CVaR {cvar_actual*100:.2f}% vs limit {cvar_limit*100:.1f}%"},
            "drift":           {"score": drift_score,  "label": "Drift from Target", "detail": f"Total drift {total_drift*100:.1f}%" if optimal else "No quant result yet"},
        },
        "profile": profile,
    }


@router.post("/kelly")
def kelly_sizing(
    body: dict,
    user_id: str = Depends(get_user_id),
):
    """
    Compute Kelly-optimal position size for a new or existing ticker.
    Input: {ticker, conviction_pct (0-100), expected_annual_return (%), win_rate (0-1, optional)}
    Output: {kelly_pct, half_kelly_pct, quarter_kelly_pct, recommended_amount, portfolio_value, rationale}
    """
    import numpy as np
    from fastapi import HTTPException

    ticker = str(body.get("ticker", "")).upper().strip()
    conviction = float(body.get("conviction_pct", 60)) / 100.0  # 0-1
    exp_ret = float(body.get("expected_annual_return", 10)) / 100.0
    win_rate = float(body.get("win_rate", conviction))  # default conviction as win rate proxy

    if not ticker:
        raise HTTPException(status_code=422, detail="ticker required")

    tickers, weights = _get_positions_and_weights(user_id)
    db = get_admin_client()
    settings_res = db.table("user_settings").select("base_currency,max_single_asset").eq("user_id", user_id).maybe_single().execute()
    settings = settings_res.data or {}
    max_single = float(settings.get("max_single_asset") or 0.40)

    # Fetch ticker historical returns for vol estimate
    try:
        hist = get_historical_multi([ticker], period="2y")
        df = hist.get(ticker)
        if df is not None and not df.empty:
            col = "Close" if "Close" in df.columns else df.columns[0]
            daily_rets = df[col].pct_change().dropna()
            ann_vol = float(daily_rets.std() * np.sqrt(252))
        else:
            ann_vol = 0.20  # default 20% vol
    except Exception:
        ann_vol = 0.20

    # Kelly formula: f* = (b*p - q) / b
    # where b = odds (exp_ret / ann_vol as proxy), p = win_rate, q = 1-p
    # Simplified continuous Kelly: f* = mu / sigma^2
    kelly_continuous = exp_ret / (ann_vol ** 2) if ann_vol > 0 else 0.0
    # Also classical discrete Kelly using win_rate
    b = max(exp_ret / ann_vol, 0.1)  # b = reward per unit risk
    kelly_discrete = max(0.0, (b * win_rate - (1 - win_rate)) / b)

    # Blend: 50% continuous + 50% discrete, scaled by conviction
    kelly_raw = (kelly_continuous * 0.5 + kelly_discrete * 0.5) * conviction
    kelly_pct = min(kelly_raw, max_single)  # never exceed max single asset
    half_kelly = kelly_pct * 0.5
    quarter_kelly = kelly_pct * 0.25

    # Get portfolio value
    pos_res = db.table("positions").select("ticker,shares").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    portfolio_value = 0.0
    try:
        all_t = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
        if all_t:
            quotes = get_quotes(all_t)
            portfolio_value = sum(
                float(p["shares"]) * float(quotes.get(p["ticker"], {}).get("price") or 0)
                for p in positions if float(p.get("shares", 0)) > 0
            )
    except Exception:
        pass

    return {
        "ticker": ticker,
        "kelly_pct": round(kelly_pct * 100, 2),
        "half_kelly_pct": round(half_kelly * 100, 2),
        "quarter_kelly_pct": round(quarter_kelly * 100, 2),
        "recommended_amount": round(portfolio_value * half_kelly, 2),  # ½ Kelly is standard
        "portfolio_value": round(portfolio_value, 2),
        "inputs": {
            "conviction_pct": round(conviction * 100, 1),
            "expected_return_pct": round(exp_ret * 100, 1),
            "estimated_ann_vol_pct": round(ann_vol * 100, 1),
            "win_rate": round(win_rate * 100, 1),
        },
        "rationale": f"Kelly sugiere {kelly_pct*100:.1f}% del portafolio. Se recomienda ½ Kelly ({half_kelly*100:.1f}%) para gestión conservadora del riesgo de ruina.",
    }


@router.post("/monte-carlo")
def monte_carlo_simulation(
    body: dict,
    user_id: str = Depends(get_user_id),
):
    """
    Monte Carlo simulation for financial goal planning.
    Input: {monthly_contribution, years, target_goal, n_sims (default 5000)}
    Uses portfolio's historical annualized return and volatility.
    Output: {probability_of_goal, median_outcome, p5, p25, p75, p95,
             current_value, series (sampled paths for chart), ann_return, ann_vol}
    """
    import numpy as np
    import pandas as pd
    from fastapi import HTTPException

    monthly = float(body.get("monthly_contribution", 500))
    years = int(body.get("years", 10))
    target = float(body.get("target_goal", 100000))
    n_sims = min(int(body.get("n_sims", 5000)), 10000)

    if years <= 0 or monthly < 0 or target <= 0:
        raise HTTPException(status_code=422, detail="Invalid inputs")

    tickers, weights = _get_positions_and_weights(user_id)

    # Get portfolio current value
    db = get_admin_client()
    settings_res = db.table("user_settings").select("base_currency").eq("user_id", user_id).maybe_single().execute()
    base_currency = (settings_res.data or {}).get("base_currency", "USD")

    current_value = 0.0
    if tickers:
        try:
            quotes = get_quotes(tickers)
            pos_res = db.table("positions").select("ticker,shares").eq("user_id", user_id).execute()
            for p in (pos_res.data or []):
                t = p["ticker"]
                shares = float(p.get("shares") or 0)
                price = float((quotes.get(t) or {}).get("price") or 0)
                current_value += shares * price
        except Exception:
            pass

    # Estimate portfolio return and vol from history
    ann_return = 0.10  # defaults
    ann_vol = 0.15

    if tickers:
        try:
            hist = get_historical_multi(tickers, period="2y")
            port_rets = build_portfolio_returns(
                {t: hist[t] for t in tickers if t in hist}, weights
            )
            if len(port_rets) > 50:
                ann_return = float((1 + port_rets.mean()) ** 252 - 1)
                ann_vol = float(port_rets.std() * np.sqrt(252))
        except Exception:
            pass

    # Monthly params
    months = years * 12
    mu_m = ann_return / 12
    sigma_m = ann_vol / np.sqrt(12)

    rng = np.random.default_rng(42)
    shocks = rng.normal(mu_m, sigma_m, (n_sims, months))

    # Simulate: each month compound existing wealth + add contribution
    wealth = np.full(n_sims, current_value)
    # Store 24 time points for chart (every year or every 6 months)
    n_checkpoints = min(years * 2, 24)
    checkpoint_months = [int(i * months / n_checkpoints) for i in range(1, n_checkpoints + 1)]
    checkpoint_months[-1] = months  # ensure last point is final

    paths_sample_idx = rng.choice(n_sims, size=min(20, n_sims), replace=False)
    paths: dict[int, list[float]] = {i: [current_value] for i in paths_sample_idx}
    checkpoint_data: list[dict] = [{"month": 0, "p5": current_value, "p25": current_value, "median": current_value, "p75": current_value, "p95": current_value}]

    cp_set = set(checkpoint_months)
    for m in range(months):
        growth = 1 + shocks[:, m]
        wealth = wealth * growth + monthly
        for i in paths_sample_idx:
            paths[i].append(float(wealth[i]))
        if m + 1 in cp_set:
            checkpoint_data.append({
                "month": m + 1,
                "year": round((m + 1) / 12, 1),
                "p5":     round(float(np.percentile(wealth, 5)), 0),
                "p25":    round(float(np.percentile(wealth, 25)), 0),
                "median": round(float(np.median(wealth)), 0),
                "p75":    round(float(np.percentile(wealth, 75)), 0),
                "p95":    round(float(np.percentile(wealth, 95)), 0),
            })

    final_wealth = wealth
    prob = float(np.mean(final_wealth >= target))

    # Sampled paths for chart (downsample to checkpoint months)
    chart_paths = []
    for i in paths_sample_idx[:10]:
        path = paths[i]
        sampled = [path[0]] + [path[cp] for cp in checkpoint_months if cp < len(path)]
        chart_paths.append(sampled)

    return {
        "probability_of_goal": round(prob * 100, 1),
        "median_outcome": round(float(np.median(final_wealth)), 0),
        "p5":  round(float(np.percentile(final_wealth, 5)), 0),
        "p25": round(float(np.percentile(final_wealth, 25)), 0),
        "p75": round(float(np.percentile(final_wealth, 75)), 0),
        "p95": round(float(np.percentile(final_wealth, 95)), 0),
        "current_value":        round(current_value, 0),
        "target_goal":          round(target, 0),
        "monthly_contribution": monthly,
        "years":                years,
        "ann_return_pct":       round(ann_return * 100, 2),
        "ann_vol_pct":          round(ann_vol * 100, 2),
        "n_sims":               n_sims,
        "base_currency":        base_currency,
        "fan_series":           checkpoint_data,
        "sample_paths":         chart_paths,
        "checkpoint_months":    [0] + checkpoint_months,
    }


@router.get("/attribution")
def return_attribution(
    user_id: str = Depends(get_user_id),
):
    """
    Decompose portfolio P&L into price return, FX return, and dividend return per position.
    Uses avg_cost vs current price, and tracks the FX rate at inception vs current.
    Returns {rows: [{ticker, price_return_pct, fx_return_pct, dividend_return_pct, total_return_pct, value_base}], totals}
    """
    import yfinance as yf
    import pandas as pd
    from app.services.fx_service import get_fx_rates
    from app.services.exchange_classifier import get_native_currency

    db = get_admin_client()
    settings_res = db.table("user_settings").select("base_currency").eq("user_id", user_id).maybe_single().execute()
    base_currency = (settings_res.data or {}).get("base_currency", "USD")

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    positions = [p for p in positions if float(p.get("shares") or 0) > 0]
    if not positions:
        return {"rows": [], "totals": {}, "base_currency": base_currency}

    tickers = [p["ticker"] for p in positions]

    quotes = get_quotes(tickers)

    # Get native currencies for each ticker
    native_currencies = {t: get_native_currency(t) for t in tickers}
    all_currencies = list(set(native_currencies.values()))
    fx_rates = get_fx_rates(all_currencies, base=base_currency)

    # Fetch dividends from yfinance (trailing 12 months)
    dividends: dict[str, float] = {}
    try:
        for t in tickers:
            try:
                tk = yf.Ticker(t)
                divs = tk.dividends
                if divs is not None and not divs.empty:
                    cutoff = pd.Timestamp.now() - pd.DateOffset(months=12)
                    recent = divs[divs.index >= cutoff]
                    dividends[t] = float(recent.sum()) if not recent.empty else 0.0
            except Exception:
                dividends[t] = 0.0
    except Exception:
        pass

    rows = []
    for p in positions:
        t = p["ticker"]
        shares = float(p.get("shares") or 0)
        avg_cost_native = float(p.get("avg_cost") or p.get("average_cost") or 0)
        pos_currency = p.get("currency") or native_currencies.get(t, "USD")

        current_price_native = float((quotes.get(t) or {}).get("price") or 0)
        if avg_cost_native <= 0 or current_price_native <= 0:
            continue

        # Price return (in native currency)
        price_return_pct = (current_price_native - avg_cost_native) / avg_cost_native * 100

        # FX return: compare current FX rate vs implied FX at purchase
        # We don't store historical FX, so we use cost_basis_usd if available
        # Approximation: if base=USD and pos_currency=EUR, FX return = (fx_now - fx_then)/fx_then
        # Use current FX rate; if position currency == base, FX return = 0
        fx_now = float(fx_rates.get(pos_currency, 1.0))
        fx_return_pct = 0.0
        if pos_currency != base_currency and pos_currency in fx_rates:
            # Rough FX attribution: total return in base - price return in native
            # We can't recover historical FX without more data, so report 0 with note
            fx_return_pct = 0.0  # would need historical FX snapshot to compute precisely

        # Dividend return (per share vs avg cost)
        div_per_share = dividends.get(t, 0.0)
        dividend_return_pct = (div_per_share / avg_cost_native * 100) if avg_cost_native > 0 else 0.0

        current_value_base = current_price_native * shares / fx_now if fx_now > 0 else 0.0
        cost_basis_base = avg_cost_native * shares / fx_now if fx_now > 0 else 0.0

        rows.append({
            "ticker": t,
            "shares": round(shares, 4),
            "currency": pos_currency,
            "avg_cost_native": round(avg_cost_native, 4),
            "current_price_native": round(current_price_native, 4),
            "price_return_pct": round(price_return_pct, 2),
            "fx_return_pct": round(fx_return_pct, 2),
            "dividend_return_pct": round(dividend_return_pct, 2),
            "total_return_pct": round(price_return_pct + fx_return_pct + dividend_return_pct, 2),
            "cost_basis_base": round(cost_basis_base, 2),
            "current_value_base": round(current_value_base, 2),
            "unrealized_pnl_base": round(current_value_base - cost_basis_base, 2),
        })

    rows.sort(key=lambda r: r["total_return_pct"], reverse=True)

    total_cost = sum(r["cost_basis_base"] for r in rows)
    total_value = sum(r["current_value_base"] for r in rows)
    total_return_pct = (total_value - total_cost) / total_cost * 100 if total_cost > 0 else 0

    return {
        "rows": rows,
        "totals": {
            "total_cost_base": round(total_cost, 2),
            "total_value_base": round(total_value, 2),
            "total_pnl_base": round(total_value - total_cost, 2),
            "total_return_pct": round(total_return_pct, 2),
        },
        "base_currency": base_currency,
    }


@router.get("/news")
def portfolio_news(
    user_id: str = Depends(get_user_id),
):
    """
    Aggregated news headlines for all portfolio tickers via yfinance.
    Returns {items: [{ticker, title, url, published, source}]} sorted by date desc.
    """
    import yfinance as yf
    from datetime import datetime

    tickers, _ = _get_positions_and_weights(user_id)
    if not tickers:
        return {"items": []}

    items = []
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            news = tk.news or []
            for n in news[:5]:  # max 5 per ticker
                # yfinance news format varies by version
                content = n.get("content") or {}
                title = content.get("title") or n.get("title") or ""
                if not title:
                    continue
                # URL
                click_url = (content.get("clickThroughUrl") or {}).get("url") or \
                            (content.get("canonicalUrl") or {}).get("url") or \
                            n.get("link") or n.get("url") or ""
                # Published
                pub_raw = content.get("pubDate") or n.get("providerPublishTime") or ""
                pub_str = ""
                if isinstance(pub_raw, (int, float)):
                    pub_str = datetime.utcfromtimestamp(pub_raw).strftime("%Y-%m-%d %H:%M")
                elif isinstance(pub_raw, str):
                    pub_str = pub_raw[:16]
                # Source
                provider = (content.get("provider") or {}).get("displayName") or \
                           n.get("publisher") or ""
                items.append({
                    "ticker": t,
                    "title": title[:200],
                    "url": click_url,
                    "published": pub_str,
                    "source": provider,
                })
        except Exception:
            continue

    # Sort by published desc (string sort works if format is consistent)
    items.sort(key=lambda x: x.get("published", ""), reverse=True)

    return {"items": items[:50]}  # cap at 50 total


# ── MWR (Money-Weighted Return / XIRR) ───────────────────────────────────────

def _compute_mwr(
    transactions: list[dict],
    current_value_base: float,
    fx_rates: dict,
    base_currency: str,
) -> float | None:
    """XIRR-based Money-Weighted Return from transaction history."""
    from datetime import date as _date

    cash_flows: list[tuple] = []

    for tx in sorted(transactions, key=lambda x: (x.get("date") or "")[:10]):
        action = (tx.get("action") or "").upper().strip()
        if action not in ("BUY", "SELL", "DIVIDEND"):
            continue
        date_str = (tx.get("date") or "")[:10]
        if not date_str:
            continue
        try:
            tx_date = _date.fromisoformat(date_str)
        except Exception:
            continue

        qty = float(tx.get("quantity") or 0)
        price = float(tx.get("price_native") or 0)
        fee = float(tx.get("fee_native") or 0)
        ccy = tx.get("currency") or base_currency
        fx = fx_rates.get(ccy, 1.0)

        if action == "BUY":
            amount = -(qty * price + fee) * fx   # money out
        elif action == "SELL":
            amount = (qty * price - fee) * fx    # money in
        else:  # DIVIDEND
            amount = qty * price * fx            # income received

        cash_flows.append((tx_date, amount))

    if not cash_flows:
        return None

    # Terminal cash flow = current portfolio value (what you'd receive if sold today)
    from datetime import date as _date2
    cash_flows.append((_date2.today(), current_value_base))
    cash_flows.sort(key=lambda x: x[0])

    if not any(a < 0 for a in [cf[1] for cf in cash_flows]):
        return None  # no investments recorded

    t0 = cash_flows[0][0]
    days = [(cf[0] - t0).days for cf in cash_flows]
    amounts = [cf[1] for cf in cash_flows]

    def _npv(r: float) -> float:
        if r <= -1.0:
            return float("inf")
        return sum(a / (1.0 + r) ** (d / 365.0) for a, d in zip(amounts, days))

    try:
        from scipy.optimize import brentq
        # Upper bound 10 000 (1 000 000 %) handles very short holding periods
        # where annualised XIRR can be extremely high
        rate = brentq(_npv, -0.999, 10_000.0, maxiter=2000, xtol=1e-8)
        return round(rate * 100, 2)
    except Exception:
        return None


@router.get("/mwr")
def mwr_return(user_id: str = Depends(get_user_id)):
    """Money-Weighted Return (XIRR) computed from all transactions."""
    from app.services.fx_service import get_fx_rates
    from app.services.exchange_classifier import get_native_currency

    db = get_admin_client()
    settings_res = (
        db.table("user_settings").select("base_currency").eq("user_id", user_id).maybe_single().execute()
    )
    base_currency = (settings_res.data or {}).get("base_currency", "USD")

    tx_res = (
        db.table("transactions").select("*").eq("user_id", user_id).order("date").execute()
    )
    transactions = tx_res.data or []

    pos_res = db.table("positions").select("ticker,shares").eq("user_id", user_id).execute()
    positions = [p for p in (pos_res.data or []) if float(p.get("shares", 0)) > 0]
    if not positions:
        return {"mwr": None, "n_transactions": 0}

    tickers = [p["ticker"] for p in positions]
    shares_map = {p["ticker"]: float(p["shares"]) for p in positions}

    quotes = get_quotes(tickers)
    exchange_currencies = [get_native_currency(t) for t in tickers]
    tx_ccys = list({tx.get("currency", base_currency) for tx in transactions if tx.get("currency")})
    all_ccys = list(set(exchange_currencies + tx_ccys))
    fx_rates = get_fx_rates(all_ccys, base=base_currency)

    current_value = 0.0
    for t in tickers:
        price = float((quotes.get(t) or {}).get("price") or 0)
        shares = shares_map.get(t, 0.0)
        ccy = get_native_currency(t)
        fx = fx_rates.get(ccy, 1.0)
        current_value += price * shares * fx

    if current_value <= 0:
        return {"mwr": None, "n_transactions": len(transactions)}

    mwr = _compute_mwr(transactions, current_value, fx_rates, base_currency)
    n_buy_sell = sum(1 for tx in transactions if tx.get("action") in ("BUY", "SELL"))

    return {"mwr": mwr, "n_transactions": n_buy_sell}


# ── Benchmark Overlay ─────────────────────────────────────────────────────────

@router.get("/benchmark-overlay")
def benchmark_overlay(
    period: str = Query(default="1y"),
    benchmarks: str = Query(default="VOO,QQQ,GLD,AGG"),
    user_id: str = Depends(get_user_id),
):
    """
    Portfolio vs multiple benchmarks, all normalized to 100 at inception.
    Uses portfolio_snapshots for portfolio; yfinance for benchmarks.
    Returns: {series: [{date, Portfolio, VOO, ...}], tickers, inception_date}
    """
    import pandas as pd
    from datetime import date, timedelta

    period_days = {"6m": 180, "1y": 365, "2y": 730, "3y": 1095, "all": 9999}
    days = period_days.get(period, 365)
    since = str(date.today() - timedelta(days=days))

    db = get_admin_client()
    res = (
        db.table("portfolio_snapshots")
        .select("snapshot_date,total_value_base")
        .eq("user_id", user_id)
        .gte("snapshot_date", since)
        .order("snapshot_date", desc=False)
        .execute()
    )
    rows = res.data or []
    if len(rows) < 2:
        return {"series": [], "tickers": [], "inception_date": None}

    inception_date = rows[0]["snapshot_date"]
    port_base = float(rows[0]["total_value_base"])
    if port_base <= 0:
        return {"series": [], "tickers": [], "inception_date": inception_date}

    port_vals = {
        r["snapshot_date"]: float(r["total_value_base"]) / port_base * 100.0
        for r in rows
    }

    bm_tickers = [t.strip().upper() for t in benchmarks.split(",") if t.strip()][:6]

    bm_series: dict[str, dict[str, float]] = {}
    if bm_tickers:
        bm_hist = get_historical_multi(bm_tickers, period=period)
        for bm in bm_tickers:
            df = bm_hist.get(bm)
            if df is None or df.empty:
                continue
            col = "Close" if "Close" in df.columns else df.columns[0]
            filtered = df[col].dropna()
            filtered = filtered[filtered.index >= pd.Timestamp(inception_date)]
            if filtered.empty:
                continue
            base_price = float(filtered.iloc[0])
            if base_price <= 0:
                continue
            bm_series[bm] = {
                str(ts.date()): round(float(v) / base_price * 100.0, 4)
                for ts, v in filtered.items()
            }

    all_dates = sorted(
        set(list(port_vals.keys())) | {d for s in bm_series.values() for d in s.keys()}
    )
    active_tickers = ["Portfolio"] + list(bm_series.keys())
    last_vals: dict[str, float | None] = {t: None for t in active_tickers}

    series = []
    for d in all_dates:
        if d < inception_date:
            continue
        if d in port_vals:
            last_vals["Portfolio"] = port_vals[d]
        for bm in bm_series:
            if d in bm_series[bm]:
                last_vals[bm] = bm_series[bm][d]

        if last_vals["Portfolio"] is None:
            continue

        row: dict = {"date": d, "Portfolio": round(last_vals["Portfolio"], 4)}
        for bm in bm_series:
            row[bm] = last_vals[bm]
        series.append(row)

    return {
        "series": series,
        "tickers": active_tickers,
        "inception_date": inception_date,
    }


# ── Fixed Income Analytics ────────────────────────────────────────────────────

_BOND_KEYWORDS = [
    "bond", "fixed income", "treasury", "gilt", "sovereign",
    "credit", "bund", "aggregate", "investment grade", "high yield",
    "btp", "oat", "coupon", "duration", "maturity",
]

_BOND_CATEGORIES = {
    "intermediate-term bond", "short-term bond", "long-term bond",
    "corporate bond", "government bond", "high yield bond",
    "multisector bond", "inflation-protected bond", "bond",
    "world bond", "emerging markets bond", "ultrashort bond",
}


def _is_fixed_income(ticker: str, info: dict) -> bool:
    qt = (info.get("quoteType") or "").lower()
    if qt in ("fixed_income", "bond"):
        return True
    cat = (info.get("category") or "").lower()
    if any(c in cat for c in _BOND_CATEGORIES) or "bond" in cat:
        return True
    name = (info.get("longName") or info.get("shortName") or "").lower()
    return any(kw in name for kw in _BOND_KEYWORDS)


@router.get("/fixed-income")
def fixed_income_analytics(user_id: str = Depends(get_user_id)):
    """
    Fixed income analytics: identify bond positions and compute duration,
    YTM, credit quality, and rate sensitivity.
    """
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor
    from app.services.fx_service import get_fx_rates
    from app.services.exchange_classifier import get_native_currency, yf_ticker

    _empty = {
        "has_fixed_income": False,
        "fixed_income_weight_pct": 0.0,
        "effective_duration": None,
        "portfolio_ytm_pct": None,
        "rate_sensitivity_1pct": None,
        "positions": [],
        "total_value_base": 0.0,
        "base_currency": "USD",
        "total_portfolio_value": 0.0,
    }

    db = get_admin_client()
    settings_res = (
        db.table("user_settings").select("base_currency").eq("user_id", user_id).maybe_single().execute()
    )
    base_currency = (settings_res.data or {}).get("base_currency", "USD")
    _empty["base_currency"] = base_currency

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = [p for p in (pos_res.data or []) if float(p.get("shares", 0)) > 0]
    if not positions:
        return _empty

    tickers = [p["ticker"] for p in positions]
    quotes = get_quotes(tickers)
    exchange_currencies = [get_native_currency(t) for t in tickers]
    pos_currencies = [p.get("currency") or get_native_currency(p["ticker"]) for p in positions]
    fx_rates = get_fx_rates(list(set(exchange_currencies + pos_currencies)), base=base_currency)

    value_map: dict[str, float] = {}
    for p in positions:
        ticker = p["ticker"]
        shares = float(p.get("shares") or 0)
        price = float((quotes.get(ticker) or {}).get("price") or 0)
        ccy = get_native_currency(ticker)
        fx = fx_rates.get(ccy, 1.0)
        value_map[ticker] = price * shares * fx

    total_value = sum(value_map.values())
    if total_value <= 0:
        return _empty

    def _fetch_info(ticker: str) -> tuple[str, dict]:
        try:
            info = yf.Ticker(yf_ticker(ticker)).info or {}
            return ticker, info
        except Exception:
            return ticker, {}

    with ThreadPoolExecutor(max_workers=8) as pool:
        infos = dict(pool.map(_fetch_info, tickers))

    fi_positions = []
    fi_total_value = 0.0
    weighted_duration = 0.0
    weighted_ytm = 0.0

    for ticker in tickers:
        info = infos.get(ticker, {})
        if not _is_fixed_income(ticker, info):
            continue

        val = value_map.get(ticker, 0.0)
        w = val / total_value

        duration = float(info.get("duration") or info.get("effectiveDuration") or 0)
        ytm_raw = float(
            info.get("yield") or info.get("trailingAnnualDividendYield") or 0
        )

        fi_positions.append({
            "ticker": ticker,
            "name": info.get("longName") or info.get("shortName") or ticker,
            "weight_pct": round(w * 100, 2),
            "value_base": round(val, 2),
            "duration": round(duration, 2) if duration > 0 else None,
            "ytm_pct": round(ytm_raw * 100, 3) if ytm_raw > 0 else None,
        })

        fi_total_value += val
        if duration > 0:
            weighted_duration += duration * w
        if ytm_raw > 0:
            weighted_ytm += ytm_raw * w

    fi_weight_pct = round(fi_total_value / total_value * 100, 2)
    eff_duration = round(weighted_duration, 2) if weighted_duration > 0 else None
    port_ytm = round(weighted_ytm * 100, 3) if weighted_ytm > 0 else None
    rate_sensitivity = round(-eff_duration, 2) if eff_duration else None

    return {
        "has_fixed_income": len(fi_positions) > 0,
        "fixed_income_weight_pct": fi_weight_pct,
        "effective_duration": eff_duration,
        "portfolio_ytm_pct": port_ytm,
        "rate_sensitivity_1pct": rate_sensitivity,
        "positions": fi_positions,
        "total_value_base": round(fi_total_value, 2),
        "total_portfolio_value": round(total_value, 2),
        "base_currency": base_currency,
    }
