from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pytz
import streamlit as st

from portfolio import public_portfolio
from app_core import (
    CASH_BALANCES_HEADERS,
    DEFAULT_RISK_FREE_RATE,
    DIVIDENDS_HEADERS,
    N_SIMULATIONS,
    PUBLIC_DEFAULTS_VERSION,
    SUPPORTED_BASE_CCY,
    TRANSACTIONS_HEADERS,
    backfill_missing_proxy_history,
    build_benchmark_returns,
    build_cash_display_df,
    build_current_portfolio,
    build_dividend_insights,
    build_fx_data,
    build_portfolio_df,
    build_portfolio_returns,
    build_stress_test_table,
    build_transaction_positions,
    compute_mwr,
    compute_var_cvar,
    convert_historical_to_base,
    get_default_constraints,
    get_mode_prefix,
    get_risk_free_rate,
    init_mode_state,
    load_cash_balances_from_sheets,
    load_dividends_from_sheets,
    load_market_data_with_proxies,
    load_private_portfolio,
    load_private_positions_from_sheets,
    load_transactions_from_sheets,
    merge_private_portfolios,
    optimize_max_sharpe,
    optimize_min_vol,
    reset_mode_state,
    simulate_constrained_efficient_frontier,
)


_COLOMBIA_TZ = pytz.timezone("America/Bogota")
_SNAPSHOT_TRIGGER_HOUR = 18  # 6pm Colombia


def _should_auto_snapshot(ctx: dict) -> bool:
    """True if it's past 6pm Colombia today and no snapshot has been saved yet today."""
    if ctx.get("app_scope") != "private" or not ctx.get("authenticated"):
        return False

    now_col = datetime.now(_COLOMBIA_TZ)
    if now_col.hour < _SNAPSHOT_TRIGGER_HOUR:
        return False

    today_col = now_col.date()

    # Avoid saving more than once per session per day
    last_auto = st.session_state.get("last_auto_snapshot_date")
    if last_auto == str(today_col):
        return False

    # Check sheets for an existing snapshot today
    try:
        from pages_app.portfolio_history import load_portfolio_snapshots, filter_snapshots_for_context
        snaps = load_portfolio_snapshots()
        if not snaps.empty:
            filtered = filter_snapshots_for_context(snaps, ctx.get("mode"), ctx.get("base_currency"))
            if not filtered.empty:
                last_ts = pd.to_datetime(filtered["timestamp"].iloc[-1], errors="coerce")
                if pd.notna(last_ts):
                    last_date = last_ts.astimezone(_COLOMBIA_TZ).date() if last_ts.tzinfo else last_ts.date()
                    if last_date >= today_col:
                        st.session_state["last_auto_snapshot_date"] = str(today_col)
                        return False
    except Exception:
        pass

    return True


def _normalize_weight_map(weight_map: dict, tickers: list[str]) -> dict[str, float]:
    clean = {t: max(float(weight_map.get(t, 0.0)), 0.0) for t in tickers}
    total = float(sum(clean.values()))
    if total <= 0:
        equal = 1.0 / len(tickers) if tickers else 0.0
        return {t: equal for t in tickers}
    return {t: v / total for t, v in clean.items()}


def _build_policy_target_map(portfolio_data: dict, df: pd.DataFrame) -> dict[str, float]:
    if df is None or df.empty:
        return {}

    tickers = df["Ticker"].astype(str).tolist()

    explicit = {}
    explicit_total = 0.0
    for ticker in tickers:
        meta = portfolio_data.get(ticker, {})
        try:
            tw = float(meta.get("target_weight"))
        except Exception:
            tw = np.nan

        explicit[ticker] = tw
        if np.isfinite(tw) and tw > 0:
            explicit_total += tw

    if explicit_total > 0:
        raw = {t: (explicit[t] if np.isfinite(explicit[t]) else 0.0) for t in tickers}
        return _normalize_weight_map(raw, tickers)

    # Only use base_shares fallback when at least one ticker has base_shares
    # meaningfully different from current shares — otherwise base_shares * price
    # equals current value, making Policy Target identical to Current Weight.
    any_base_shares_differ = False
    price_map = df.set_index("Ticker")["Price"].to_dict()
    raw = {}
    for ticker in tickers:
        meta = portfolio_data.get(ticker, {})
        try:
            base_shares = float(meta.get("base_shares", meta.get("shares", 0.0)))
            current_shares = float(meta.get("shares", 0.0))
        except Exception:
            base_shares = 0.0
            current_shares = 0.0
        if abs(base_shares - current_shares) > 1e-9:
            any_base_shares_differ = True
        raw[ticker] = base_shares * float(price_map.get(ticker, 0.0))

    if any_base_shares_differ and sum(raw.values()) > 0:
        return _normalize_weight_map(raw, tickers)

    if "Target Weight" in df.columns:
        raw_df = df.set_index("Ticker")["Target Weight"].to_dict()
        return _normalize_weight_map(raw_df, tickers)

    # Last resort: use current portfolio value weights (tickers with 0 value get 0 target).
    # This is more meaningful than equal-weighting tickers that have no position.
    if "Value" in df.columns:
        raw_val = df.set_index("Ticker")["Value"].to_dict()
        if sum(v for v in raw_val.values() if v > 0) > 0:
            return _normalize_weight_map(raw_val, tickers)

    return _normalize_weight_map({t: 1.0 for t in tickers}, tickers)


def _resolve_benchmark_returns(
    benchmark_returns: pd.Series | None,
    asset_returns: pd.DataFrame | None,
) -> pd.Series:
    if isinstance(benchmark_returns, pd.Series):
        bench = pd.to_numeric(benchmark_returns, errors="coerce").dropna()
        if not bench.empty:
            return bench

    if isinstance(asset_returns, pd.DataFrame) and "VOO" in asset_returns.columns:
        bench = pd.to_numeric(asset_returns["VOO"], errors="coerce").dropna()
        if not bench.empty:
            return bench

    return pd.Series(dtype=float)


def _load_private_runtime_state():
    positions_sheet_available = True
    positions_sheet_error = ""
    private_portfolio = {}
    transactions_df = pd.DataFrame(columns=TRANSACTIONS_HEADERS)
    cash_balances_df = pd.DataFrame(columns=CASH_BALANCES_HEADERS)
    dividends_df = pd.DataFrame(columns=DIVIDENDS_HEADERS)
    tx_stats_map = {}

    try:
        base_private_portfolio = load_private_portfolio()
    except Exception as e:
        st.error(f"Private portfolio not available: {e}")
        st.stop()

    try:
        private_sheet_positions = load_private_positions_from_sheets()
    except Exception as e:
        positions_sheet_available = False
        positions_sheet_error = str(e)
        private_sheet_positions = {}

    try:
        transactions_df = load_transactions_from_sheets()
    except Exception:
        transactions_df = pd.DataFrame(columns=TRANSACTIONS_HEADERS)

    try:
        cash_balances_df = load_cash_balances_from_sheets()
    except Exception:
        cash_balances_df = pd.DataFrame(
            {"currency": SUPPORTED_BASE_CCY, "amount": [0.0] * len(SUPPORTED_BASE_CCY)}
        )

    # Apply cash overrides from Private Manager — persists for the whole browser session
    # so navigating between pages always reflects the last saved value, regardless of
    # Sheets cache lag. Cleared only when a new save overwrites the same currency.
    for ccy, amt in st.session_state.get("pm_cash_override", {}).items():
        mask = cash_balances_df["currency"] == ccy
        if mask.any():
            cash_balances_df.loc[mask, "amount"] = float(amt)
        else:
            cash_balances_df = pd.concat(
                [cash_balances_df, pd.DataFrame({"currency": [ccy], "amount": [float(amt)]})],
                ignore_index=True,
            )

    try:
        dividends_df = load_dividends_from_sheets()
    except Exception:
        dividends_df = pd.DataFrame(columns=DIVIDENDS_HEADERS)

    snapshot_private = merge_private_portfolios(base_private_portfolio, private_sheet_positions)
    name_map = {t: meta["name"] for t, meta in snapshot_private.items()}
    base_shares_map = {t: meta.get("base_shares", meta["shares"]) for t, meta in snapshot_private.items()}

    _, tx_stats_map = build_transaction_positions(transactions_df, name_map, base_shares_map)
    private_portfolio = {ticker: dict(meta) for ticker, meta in snapshot_private.items()}

    return {
        "positions_sheet_available": positions_sheet_available,
        "positions_sheet_error": positions_sheet_error,
        "private_portfolio": private_portfolio,
        "transactions_df": transactions_df,
        "cash_balances_df": cash_balances_df,
        "dividends_df": dividends_df,
        "tx_stats_map": tx_stats_map,
    }


def build_app_context_runtime(app_scope: str):
    if app_scope not in {"public", "private"}:
        raise ValueError("app_scope must be 'public' or 'private'")

    if app_scope == "public":
        mode = "Public"
        authenticated = False
        positions_sheet_available = False
        positions_sheet_error = ""
        private_portfolio = {}
        transactions_df = pd.DataFrame(columns=TRANSACTIONS_HEADERS)
        cash_balances_df = pd.DataFrame(columns=CASH_BALANCES_HEADERS)
        dividends_df = pd.DataFrame(columns=DIVIDENDS_HEADERS)
        tx_stats_map = {}
    else:
        mode = "Private"
        # Authentication is handled by the login page in private_app.py.
        # By the time we reach here the session state flag is already set.
        authenticated = bool(st.session_state.get("private_authenticated", False))
        if not authenticated:
            st.stop()
        private_state = _load_private_runtime_state()
        positions_sheet_available = private_state["positions_sheet_available"]
        positions_sheet_error = private_state["positions_sheet_error"]
        private_portfolio = private_state["private_portfolio"]
        transactions_df = private_state["transactions_df"]
        cash_balances_df = private_state["cash_balances_df"]
        dividends_df = private_state["dividends_df"]
        tx_stats_map = private_state["tx_stats_map"]

    base_currency = st.sidebar.selectbox("Base Currency", SUPPORTED_BASE_CCY, index=0)

    if mode == "Private" and authenticated:
        portfolio_data = private_portfolio
    else:
        portfolio_data = public_portfolio

    prefix = get_mode_prefix(mode)

    init_mode_state(portfolio_data, prefix)

    if mode == "Public" and st.session_state.get("public_defaults_version") != PUBLIC_DEFAULTS_VERSION:
        reset_mode_state(portfolio_data, prefix)
        st.session_state["public_defaults_version"] = PUBLIC_DEFAULTS_VERSION

    if st.sidebar.button("Reset Portfolio"):
        reset_mode_state(portfolio_data, prefix)
        st.rerun()

    if mode == "Private" and authenticated:
        updated_portfolio = {
            ticker: {
                "name": meta["name"],
                "shares": float(meta["shares"]),
                "base_shares": float(meta.get("base_shares", meta["shares"])),
                "target_weight": meta.get("target_weight"),
                "avg_cost": meta.get("avg_cost"),
            }
            for ticker, meta in portfolio_data.items()
        }

    else:
        st.sidebar.header("Portfolio Inputs")
        updated_portfolio = build_current_portfolio(
            portfolio_data=portfolio_data,
            prefix=prefix,
            mode=mode,
            disable_inputs=False,
        )

    profile = st.sidebar.selectbox("Investor Profile", ["Aggressive", "Balanced", "Conservative"])
    risk_free_rate = get_risk_free_rate()

    tickers = list(updated_portfolio.keys())

    if app_scope == "private":
        from data_providers import load_market_data_private, data_source_labels
        live_prices_native, asset_hist_native = load_market_data_private(tickers=tickers, period="2y")
        data_source_info = data_source_labels(tickers)
    else:
        live_prices_native, asset_hist_native = load_market_data_with_proxies(tickers=tickers, period="2y")
        data_source_info = {}

    if asset_hist_native is None or asset_hist_native.empty or asset_hist_native.dropna(how="all").empty:
        st.error("Could not load historical data.")
        st.stop()

    fx_prices, fx_hist, _ = build_fx_data(tickers, base_currency, period="2y")
    historical_base, missing_fx = convert_historical_to_base(asset_hist_native, tickers, base_currency, fx_hist)
    historical_base = backfill_missing_proxy_history(
        historical_base,
        tickers,
        base_currency,
        fx_hist,
        period="2y",
    )

    if historical_base.empty or historical_base.dropna(how="all").empty:
        st.error("Could not build base-currency historical series.")
        st.stop()

    missing_hist = []
    for ticker in tickers:
        if ticker not in historical_base.columns:
            missing_hist.append(ticker)
        else:
            s = pd.to_numeric(historical_base[ticker], errors="coerce").dropna()
            if s.empty:
                missing_hist.append(ticker)

    if missing_hist and app_scope == "private":
        st.warning(f"No converted historical data for: {', '.join(missing_hist)}")

    if missing_fx and app_scope == "private":
        st.warning(f"Missing FX history for: {', '.join(missing_fx)}")

    df, total_value, pnl_totals = build_portfolio_df(
        updated_portfolio=updated_portfolio,
        live_prices_native=live_prices_native,
        asset_hist_native=asset_hist_native,
        fx_prices=fx_prices,
        fx_hist=fx_hist,
        base_currency=base_currency,
        tx_stats_map=tx_stats_map,
    )

    df["Price Source"] = df["Ticker"].map(lambda t: data_source_info.get(t, ""))

    cash_display_df, cash_total_value = build_cash_display_df(
        cash_balances_df,
        base_currency,
        fx_prices,
        fx_hist,
    )
    total_portfolio_value = pnl_totals["holdings_value"] + cash_total_value

    display_df = df[
        [
            "Ticker",
            "Name",
            "Price Source",
            "Source",
            "Market",
            "Native Currency",
            "Shares",
            "Avg Cost",
            "Price",
            "Invested Capital",
            "Value",
            "Unrealized PnL",
            "Unrealized PnL %",
            "Weight %",
            "Target %",
            "Deviation %",
        ]
    ].copy()

    alloc_df = df[df["Value"] > 0][["Name", "Value"]].copy()
    if cash_total_value > 0:
        alloc_df = pd.concat(
            [alloc_df, pd.DataFrame([{"Name": "Cash", "Value": cash_total_value}])],
            ignore_index=True,
        )

    if not alloc_df.empty:
        fig_pie = px.pie(alloc_df, names="Name", values="Value", hole=0.45)
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
    else:
        fig_pie = go.Figure()
        fig_pie.add_annotation(text="No portfolio value to display", x=0.5, y=0.5, showarrow=False)

    fig_pie.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=360,
        margin=dict(t=20, b=20, l=20, r=20),
        legend=dict(orientation="h", y=-0.08),
    )

    fig_bar = go.Figure()
    fig_bar.add_bar(x=df["Ticker"], y=df["Weight %"], name="Actual %")
    fig_bar.add_bar(x=df["Ticker"], y=df["Target %"], name="Target %")
    fig_bar.update_layout(
        barmode="group",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=360,
        margin=dict(t=20, b=20, l=20, r=20),
    )

    portfolio_returns, asset_returns = build_portfolio_returns(df, historical_base)
    benchmark_returns = build_benchmark_returns(base_currency, fx_hist)
    resolved_benchmark_returns = _resolve_benchmark_returns(benchmark_returns, asset_returns)
    policy_target_map = _build_policy_target_map(portfolio_data, df)

    total_return = 0.0
    volatility = 0.0
    sharpe = 0.0
    max_drawdown = 0.0
    alpha = 0.0
    beta = 0.0
    tracking_error = 0.0
    information_ratio = 0.0

    portfolio_cum = pd.Series(dtype=float)
    benchmark_cum = pd.Series(dtype=float)

    if not portfolio_returns.empty:
        portfolio_cum = (1 + portfolio_returns).cumprod()
        total_return = float(portfolio_cum.iloc[-1] - 1)
        volatility = float(portfolio_returns.std() * np.sqrt(252))
        if volatility > 0:
            sharpe = float((portfolio_returns.mean() * 252 - risk_free_rate) / volatility)

        rolling_max = portfolio_cum.cummax()
        drawdown = portfolio_cum / rolling_max - 1
        max_drawdown = float(drawdown.min())

    if not portfolio_returns.empty and not resolved_benchmark_returns.empty:
        aligned = pd.concat(
            [portfolio_returns.rename("Portfolio"), resolved_benchmark_returns.rename("Benchmark")],
            axis=1,
        ).dropna()

        if not aligned.empty:
            benchmark_cum = (1 + aligned["Benchmark"]).cumprod()
            bench_var = aligned["Benchmark"].var()
            if bench_var > 0:
                beta = float(aligned.cov().loc["Portfolio", "Benchmark"] / bench_var)

            p_mean = float(aligned["Portfolio"].mean() * 252)
            b_mean = float(aligned["Benchmark"].mean() * 252)
            alpha = float(p_mean - beta * b_mean)

            excess = aligned["Portfolio"] - aligned["Benchmark"]
            tracking_error = float(excess.std() * np.sqrt(252))
            if tracking_error > 0:
                information_ratio = float((excess.mean() * 252) / tracking_error)

    fig_perf = None
    portfolio_cum_return = None
    benchmark_cum_return = None
    excess_vs_benchmark = None

    if not portfolio_cum.empty:
        fig_perf = go.Figure()
        fig_perf.add_scatter(x=portfolio_cum.index, y=portfolio_cum, name="Portfolio")
        portfolio_cum_return = float(portfolio_cum.iloc[-1] - 1)

        if not benchmark_cum.empty:
            fig_perf.add_scatter(x=benchmark_cum.index, y=benchmark_cum, name="VOO")
            benchmark_cum_return = float(benchmark_cum.iloc[-1] - 1)
            excess_vs_benchmark = float(portfolio_cum_return - benchmark_cum_return)

        fig_perf.update_layout(
            paper_bgcolor="#0b0f14",
            plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"),
            height=400,
            margin=dict(t=20, b=20, l=20, r=20),
        )

    # ── Stress PnL with default shocks ────────────────────────────────────────
    default_shocks = {"Equities": -0.10, "Bonds": -0.03, "Gold": 0.05}
    _stress_df, current_total_value, stressed_total_value = build_stress_test_table(df, default_shocks)
    stress_pnl = stressed_total_value - current_total_value
    stress_return = (stressed_total_value / current_total_value - 1) if current_total_value > 0 else 0.0

    var_cvar = compute_var_cvar(portfolio_returns)
    mwr_result = compute_mwr(transactions_df, total_portfolio_value)

    # ── Efficient frontier (Max Sharpe / Min Vol) ─────────────────────────────
    max_sharpe_row = None
    min_vol_row = None
    usable = []
    if asset_returns is not None and not asset_returns.empty and asset_returns.shape[1] >= 2:
        _constraints  = get_default_constraints(profile)
        _asset_names  = asset_returns.columns.tolist()

        # Exact optima via scipy SLSQP (primary)
        max_sharpe_row = optimize_max_sharpe(asset_returns, _asset_names, _constraints, risk_free_rate)
        min_vol_row    = optimize_min_vol(asset_returns, _asset_names, _constraints, risk_free_rate)

        # Monte Carlo frontier as fallback if scipy fails
        if max_sharpe_row is None or min_vol_row is None:
            _frontier = simulate_constrained_efficient_frontier(
                asset_returns=asset_returns,
                asset_names=_asset_names,
                constraints=_constraints,
                risk_free_rate=risk_free_rate,
                n_portfolios=N_SIMULATIONS,
            )
            if not _frontier.empty:
                if max_sharpe_row is None:
                    max_sharpe_row = _frontier.loc[_frontier["Sharpe"].idxmax()]
                if min_vol_row is None:
                    min_vol_row = _frontier.loc[_frontier["Volatility"].idxmin()]

        if max_sharpe_row is not None or min_vol_row is not None:
            usable = _asset_names

    annual_dividend_df, dividend_calendar_df, collected_dividends_df, estimated_annual_dividends, dividends_ytd, dividends_total = build_dividend_insights(
        df=df,
        dividends_df=dividends_df,
        base_currency=base_currency,
        fx_prices=fx_prices,
        fx_hist=fx_hist,
    )

    ctx = {
        "app_scope": app_scope,
        "mode": mode,
        "data_source_info": data_source_info,
        "tx_stats_map": tx_stats_map,
        "authenticated": authenticated,
        "base_currency": base_currency,
        "profile": profile,
        "risk_free_rate": risk_free_rate,
        "positions_sheet_available": positions_sheet_available,
        "positions_sheet_error": positions_sheet_error,
        "portfolio_data": portfolio_data,
        "private_portfolio": private_portfolio,
        "updated_portfolio": updated_portfolio,
        "prefix": prefix,
        "df": df,
        "asset_hist_native": asset_hist_native,
        "historical_base": historical_base,
        "display_df": display_df,
        "transactions_df": transactions_df,
        "cash_balances_df": cash_balances_df,
        "cash_display_df": cash_display_df,
        "dividends_df": dividends_df,
        "collected_dividends_df": collected_dividends_df,
        "annual_dividend_df": annual_dividend_df,
        "dividend_calendar_df": dividend_calendar_df,
        "estimated_annual_dividends": estimated_annual_dividends,
        "dividends_ytd": dividends_ytd,
        "dividends_total": dividends_total,
        "holdings_value": pnl_totals["holdings_value"],
        "cash_total_value": cash_total_value,
        "total_portfolio_value": total_portfolio_value,
        "invested_capital": pnl_totals["invested_capital"],
        "unrealized_pnl": pnl_totals["unrealized_pnl"],
        "realized_pnl": pnl_totals["realized_pnl"],
        "total_value": total_value,
        "fig_pie": fig_pie,
        "fig_bar": fig_bar,
        "portfolio_returns": portfolio_returns,
        "asset_returns": asset_returns,
        "benchmark_returns": benchmark_returns,
        "resolved_benchmark_returns": resolved_benchmark_returns,
        "policy_target_map": policy_target_map,
        "total_return": total_return,
        "volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "alpha": alpha,
        "beta": beta,
        "tracking_error": tracking_error,
        "information_ratio": information_ratio,
        "fig_perf": fig_perf,
        "portfolio_cum_return": portfolio_cum_return,
        "benchmark_cum_return": benchmark_cum_return,
        "excess_vs_benchmark": excess_vs_benchmark,
        "stress_pnl": stress_pnl,
        "stress_return": stress_return,
        "fx_prices": fx_prices,
        "fx_hist": fx_hist,
        "var_cvar": var_cvar,
        "mwr_result": mwr_result,
        "max_sharpe_row": max_sharpe_row,
        "min_vol_row": min_vol_row,
        "usable": usable,
    }

    if _should_auto_snapshot(ctx):
        try:
            from pages_app.portfolio_history import save_portfolio_snapshot
            save_portfolio_snapshot(ctx, notes="Auto snapshot — market close 6pm Colombia")
            st.session_state["last_auto_snapshot_date"] = str(datetime.now(_COLOMBIA_TZ).date())
        except Exception:
            pass

    try:
        from email_report import should_send_monthly_report, send_monthly_report
        ok, month_str = should_send_monthly_report(ctx)
        if ok:
            send_monthly_report(ctx, month_str)
    except Exception:
        pass

    try:
        from alerts import check_alert_conditions, should_send_alerts, send_alert_telegram
        active_alerts = check_alert_conditions(ctx)
        ctx["active_alerts"] = active_alerts
        if should_send_alerts(ctx, active_alerts):
            send_alert_telegram(active_alerts, ctx)
    except Exception:
        ctx["active_alerts"] = []

    return ctx
