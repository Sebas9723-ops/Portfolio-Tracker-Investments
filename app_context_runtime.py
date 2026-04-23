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
    NON_PORTFOLIO_CASH_HEADERS,
    USER_SETTINGS_HEADERS,
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
    asset_currency,
    get_default_constraints,
    get_fx_rate_current,
    get_mode_prefix,
    get_risk_free_rate,
    init_mode_state,
    load_cash_balances_from_sheets,
    load_dividends_from_sheets,
    load_non_portfolio_cash_from_sheets,
    load_user_settings_from_sheets,
    load_market_data_with_proxies,
    load_private_portfolio,
    load_private_positions_from_sheets,
    load_transactions_from_sheets,
    merge_private_portfolios,
    optimize_max_sharpe,
    optimize_min_vol,
    optimize_min_cvar,
    compute_hrp_weights,
    compute_risk_parity_weights,
    reset_mode_state,
    simulate_constrained_efficient_frontier,
    # ── Quant Engine v2 ──────────────────────────────────────────────────────
    compute_rebalancing_bands,
    compute_net_alpha_after_costs,
    compute_after_tax_drag,
    compute_liquidity_score,
    compute_model_agreement_score,
    compute_expected_return_bands,
    explain_bl_posterior,
    compute_tracking_error_budget,
    compute_walk_forward_metrics,
    compute_regime_probabilities,
    compute_dynamic_weight_caps,
    compute_expected_drawdown_profile,
    compute_model_drift_score,
    benchmark_naive_portfolios,
    compute_factor_risk_decomposition,
    compute_black_litterman,
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
        # Record successful Sheets connection timestamp
        st.session_state["_sheets_last_ok"] = datetime.now(_COLOMBIA_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception as e:
        positions_sheet_available = False
        positions_sheet_error = str(e)
        private_sheet_positions = {}

    transactions_loaded = True
    try:
        transactions_df = load_transactions_from_sheets()
    except Exception:
        transactions_loaded = False
        transactions_df = pd.DataFrame(columns=TRANSACTIONS_HEADERS)

    cash_loaded = True
    try:
        cash_balances_df = load_cash_balances_from_sheets()
    except Exception:
        cash_loaded = False
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

    non_portfolio_cash_loaded = True
    try:
        non_portfolio_cash_df = load_non_portfolio_cash_from_sheets()
    except Exception:
        non_portfolio_cash_loaded = False
        non_portfolio_cash_df = pd.DataFrame(columns=NON_PORTFOLIO_CASH_HEADERS)

    try:
        user_settings = load_user_settings_from_sheets()
    except Exception:
        user_settings = {}

    snapshot_private = merge_private_portfolios(base_private_portfolio, private_sheet_positions)
    name_map = {t: meta["name"] for t, meta in snapshot_private.items()}
    base_shares_map = {t: meta.get("base_shares", meta["shares"]) for t, meta in snapshot_private.items()}

    _, tx_stats_map = build_transaction_positions(transactions_df, name_map, base_shares_map)
    private_portfolio = {ticker: dict(meta) for ticker, meta in snapshot_private.items()}

    return {
        "positions_sheet_available": positions_sheet_available,
        "positions_sheet_error": positions_sheet_error,
        "transactions_loaded": transactions_loaded,
        "cash_loaded": cash_loaded,
        "non_portfolio_cash_loaded": non_portfolio_cash_loaded,
        "private_portfolio": private_portfolio,
        "transactions_df": transactions_df,
        "cash_balances_df": cash_balances_df,
        "dividends_df": dividends_df,
        "non_portfolio_cash_df": non_portfolio_cash_df,
        "user_settings": user_settings,
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
        non_portfolio_cash_df = pd.DataFrame(columns=NON_PORTFOLIO_CASH_HEADERS)
        user_settings = {}
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
        non_portfolio_cash_df = private_state["non_portfolio_cash_df"]
        user_settings = private_state.get("user_settings", {})
        tx_stats_map = private_state["tx_stats_map"]

        # Load persisted ticker weight rules into session_state (only on fresh session)
        if "ticker_weight_rules" not in st.session_state:
            import json as _json
            _raw_rules = user_settings.get("ticker_weight_rules", "")
            if _raw_rules:
                try:
                    st.session_state["ticker_weight_rules"] = _json.loads(_raw_rules)
                except Exception:
                    st.session_state["ticker_weight_rules"] = {}

        # ── Sheets availability banner ────────────────────────────────────────
        if not positions_sheet_available:
            last_ok = st.session_state.get("_sheets_last_ok", "unknown")
            st.error(
                f"🔴 **Google Sheets unavailable** — showing last known portfolio data "
                f"(synced: {last_ok}). Live changes are NOT being saved. "
                f"Error: {positions_sheet_error}"
            )
        elif not private_state.get("transactions_loaded", True):
            st.warning("⚠️ Transaction history unavailable. Cost basis and PnL may be inaccurate.")
        elif not private_state.get("cash_loaded", True):
            st.warning("⚠️ Cash balances unavailable from Sheets. Showing zeros.")

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

    alpaca_available = False
    if app_scope == "private":
        from data_providers import load_market_data_private, data_source_labels, check_alpaca_status
        live_prices_native, asset_hist_native = load_market_data_private(tickers=tickers, period="2y")
        data_source_info = data_source_labels(tickers)
        alpaca_available, _ = check_alpaca_status()
    else:
        live_prices_native, asset_hist_native = load_market_data_with_proxies(tickers=tickers, period="2y")
        data_source_info = {}

    if asset_hist_native is None or asset_hist_native.empty or asset_hist_native.dropna(how="all").empty:
        st.error("Could not load historical data.")
        st.stop()

    fx_prices, fx_hist, _ = build_fx_data(tickers, base_currency, period="2y", extra_currencies=tuple(SUPPORTED_BASE_CCY))
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

    # ── FX rate last-known cache (Fix 1) ──────────────────────────────────────
    # Persist fresh FX rates to session state so they can serve as fallback
    # if the live feed is temporarily unavailable on a subsequent load.
    _fx_cache: dict = st.session_state.get("_fx_rate_cache", {})
    all_ccy = set(asset_currency(t) for t in tickers) | set(SUPPORTED_BASE_CCY)
    for ccy in all_ccy:
        if ccy == base_currency:
            continue
        rate = get_fx_rate_current(ccy, base_currency, fx_prices, fx_hist)
        if rate is not None and not pd.isna(rate) and rate > 0:
            _fx_cache[f"{ccy}_{base_currency}"] = float(rate)
    st.session_state["_fx_rate_cache"] = _fx_cache

    df, total_value, pnl_totals = build_portfolio_df(
        updated_portfolio=updated_portfolio,
        live_prices_native=live_prices_native,
        asset_hist_native=asset_hist_native,
        fx_prices=fx_prices,
        fx_hist=fx_hist,
        base_currency=base_currency,
        tx_stats_map=tx_stats_map,
        fx_fallback=_fx_cache,
    )

    df["Price Source"] = df["Ticker"].map(lambda t: data_source_info.get(t, ""))

    cash_display_df, cash_total_value = build_cash_display_df(
        cash_balances_df,
        base_currency,
        fx_prices,
        fx_hist,
    )
    total_portfolio_value = pnl_totals["holdings_value"] + cash_total_value

    non_portfolio_cash_value = 0.0
    if not non_portfolio_cash_df.empty:
        for _, row in non_portfolio_cash_df.iterrows():
            ccy = str(row.get("currency", "USD")).upper().strip()
            amt = float(row.get("amount", 0.0))
            if amt <= 0:
                continue
            rate = get_fx_rate_current(ccy, base_currency, fx_prices, fx_hist)
            if rate is None or pd.isna(rate):
                rate = _fx_cache.get(f"{ccy}_{base_currency}", 0.0)
            non_portfolio_cash_value += amt * (rate or 0.0)

    investments_net_worth = total_portfolio_value + non_portfolio_cash_value
    monthly_contribution = float(user_settings.get("monthly_contribution", 0.0))
    semi_annual_contribution = float(user_settings.get("semi_annual_contribution", 0.0))

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

    # ── Efficient frontier (Max Sharpe / Min Vol / Min CVaR / HRP / ERC) ────────
    max_sharpe_row = None
    min_vol_row = None
    min_cvar_row = None
    hrp_result = None
    erc_result = None
    usable = []
    if asset_returns is not None and not asset_returns.empty and asset_returns.shape[1] >= 2:
        _constraints  = get_default_constraints(profile)
        _asset_names  = asset_returns.columns.tolist()

        # Apply per-ticker weight rules from session_state
        _ticker_rules = st.session_state.get("ticker_weight_rules", {})
        if _ticker_rules:
            _ptb = {}
            for _ticker, _rule in _ticker_rules.items():
                if _ticker in _asset_names and _rule.get("mode") == "fixed":
                    _w = float(_rule.get("weight", 0.0))
                    _ptb[_ticker] = (_w, _w)
            if _ptb:
                _constraints["per_ticker_bounds"] = _ptb

        # Exact optima via scipy SLSQP (primary)
        max_sharpe_row = optimize_max_sharpe(asset_returns, _asset_names, _constraints, risk_free_rate)
        min_vol_row    = optimize_min_vol(asset_returns, _asset_names, _constraints, risk_free_rate)

        # Min-CVaR portfolio (Rockafellar-Uryasev LP) — coherent tail-risk optimum
        min_cvar_row = optimize_min_cvar(asset_returns, _asset_names, _constraints,
                                         confidence_level=0.95, risk_free_rate=risk_free_rate)

        # Clustering-based allocations (no matrix inversion)
        hrp_result = compute_hrp_weights(asset_returns[_asset_names])
        erc_result = compute_risk_parity_weights(asset_returns[_asset_names])

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

    # ── Quant Engine v2 computations ──────────────────────────────────────────
    # All wrapped in try/except so a failure in any module never breaks the app.

    # Shared derived inputs
    _current_weights_series = pd.Series(dtype=float)
    _position_values_map: dict = {}
    _current_prices_map: dict = {}
    if not df.empty and "Ticker" in df.columns:
        _vals = df.set_index("Ticker")["Value"].apply(pd.to_numeric, errors="coerce").fillna(0)
        _pos_total = float(_vals.sum())
        _current_weights_series = (_vals / _pos_total) if _pos_total > 0 else _vals * 0
        _position_values_map = _vals.to_dict()
        if "Price" in df.columns:
            _current_prices_map = df.set_index("Ticker")["Price"].apply(pd.to_numeric, errors="coerce").fillna(0).to_dict()

    # 1. Rebalancing bands
    rebalancing_bands = {}
    try:
        if not df.empty and policy_target_map and total_value > 0:
            rebalancing_bands = compute_rebalancing_bands(
                df=df,
                target_weights=policy_target_map,
                total_value=total_value,
            )
    except Exception:
        pass

    # 2. Net alpha after costs
    net_alpha_df = pd.DataFrame()
    try:
        if asset_returns is not None and not asset_returns.empty and not _current_weights_series.empty:
            _exp_ret = (asset_returns.mean() * 252).rename(lambda t: t)
            _tgt_w = pd.Series(policy_target_map).reindex(_exp_ret.index).fillna(0)
            net_alpha_df = compute_net_alpha_after_costs(
                expected_returns=_exp_ret,
                current_weights=_current_weights_series.reindex(_exp_ret.index).fillna(0),
                target_weights=_tgt_w,
                total_value=total_value,
            )
    except Exception:
        pass

    # 3. After-tax drag
    after_tax_drag = {}
    try:
        if not portfolio_returns.empty and not transactions_df.empty and _current_prices_map:
            after_tax_drag = compute_after_tax_drag(
                portfolio_returns=portfolio_returns,
                transactions_df=transactions_df,
                current_prices=_current_prices_map,
            )
    except Exception:
        pass

    # 4. Liquidity score
    liquidity_df = pd.DataFrame()
    try:
        if tickers:
            liquidity_df = compute_liquidity_score(
                tickers=tickers,
                position_values=_position_values_map,
            )
    except Exception:
        pass

    # 5. Model agreement score
    model_agreement = {}
    try:
        if asset_returns is not None and not asset_returns.empty:
            _opt_weights: dict = {}
            if max_sharpe_row is not None and "Weights" in max_sharpe_row.index:
                _opt_weights["Max Sharpe"] = max_sharpe_row["Weights"]
            if min_vol_row is not None and "Weights" in min_vol_row.index:
                _opt_weights["Min Vol"] = min_vol_row["Weights"]
            if min_cvar_row is not None and "Weights" in min_cvar_row.index:
                _opt_weights["Min CVaR"] = min_cvar_row["Weights"]
            if hrp_result and "weights" in hrp_result:
                _opt_weights["HRP"] = hrp_result["weights"]
            if erc_result and "weights" in erc_result:
                _opt_weights["ERC"] = erc_result["weights"]
            if len(_opt_weights) >= 2:
                model_agreement = compute_model_agreement_score(
                    optimizer_weights=_opt_weights,
                    asset_returns=asset_returns,
                    risk_free_rate=risk_free_rate,
                )
    except Exception:
        pass

    # 6. Expected return confidence bands
    expected_return_bands = pd.DataFrame()
    try:
        if asset_returns is not None and not asset_returns.empty:
            expected_return_bands = compute_expected_return_bands(asset_returns)
    except Exception:
        pass

    # 7. Black-Litterman explainability (requires BL result from session views)
    bl_explanation = pd.DataFrame()
    try:
        if asset_returns is not None and not asset_returns.empty and not _current_weights_series.empty:
            _bl_tickers = [t for t in _current_weights_series.index if t in asset_returns.columns]
            _bl_w = _current_weights_series.reindex(_bl_tickers).fillna(0).values
            _bl_views = st.session_state.get("bl_views", [])
            _bl_result = compute_black_litterman(
                asset_returns=asset_returns,
                current_weights=_bl_w,
                tickers=_bl_tickers,
                views=_bl_views,
                risk_free_rate=risk_free_rate,
            )
            if _bl_result:
                bl_explanation = explain_bl_posterior(bl_result=_bl_result, views=_bl_views)
    except Exception:
        pass

    # 8. Tracking error budget
    tracking_error_budget = {}
    try:
        if asset_returns is not None and not asset_returns.empty and not _current_weights_series.empty:
            tracking_error_budget = compute_tracking_error_budget(
                asset_returns=asset_returns,
                portfolio_weights=_current_weights_series,
                benchmark_returns=resolved_benchmark_returns,
            )
    except Exception:
        pass

    # 9. Walk-forward validation
    walk_forward_metrics = {}
    try:
        if not portfolio_returns.empty:
            walk_forward_metrics = compute_walk_forward_metrics(
                portfolio_returns=portfolio_returns,
                benchmark_returns=resolved_benchmark_returns if not resolved_benchmark_returns.empty else None,
                risk_free_rate=risk_free_rate,
            )
    except Exception:
        pass

    # 10. Regime probabilities
    regime_probabilities = {}
    try:
        if not portfolio_returns.empty:
            regime_probabilities = compute_regime_probabilities(portfolio_returns)
    except Exception:
        pass

    # 11. Dynamic weight caps
    dynamic_weight_caps = {}
    try:
        if asset_returns is not None and not asset_returns.empty and not _current_weights_series.empty:
            dynamic_weight_caps = compute_dynamic_weight_caps(
                asset_returns=asset_returns,
                current_weights=_current_weights_series,
            )
    except Exception:
        pass

    # 12. Expected drawdown profile
    expected_drawdown_profile = {}
    try:
        if not portfolio_returns.empty and total_portfolio_value > 0:
            expected_drawdown_profile = compute_expected_drawdown_profile(
                portfolio_returns=portfolio_returns,
                current_value=total_portfolio_value,
            )
    except Exception:
        pass

    # 13. Model drift score
    model_drift = {}
    try:
        if asset_returns is not None and not asset_returns.empty:
            model_drift = compute_model_drift_score(
                asset_returns=asset_returns,
                risk_free_rate=risk_free_rate,
            )
    except Exception:
        pass

    # 14. Naive portfolio benchmarking
    naive_benchmark_df = pd.DataFrame()
    try:
        if asset_returns is not None and not asset_returns.empty and not portfolio_returns.empty:
            naive_benchmark_df = benchmark_naive_portfolios(
                asset_returns=asset_returns,
                portfolio_returns=portfolio_returns,
                benchmark_returns=resolved_benchmark_returns if not resolved_benchmark_returns.empty else None,
                risk_free_rate=risk_free_rate,
            )
    except Exception:
        pass

    # 15. Factor risk decomposition
    factor_risk_decomposition = {}
    try:
        if asset_returns is not None and not asset_returns.empty and not _current_weights_series.empty:
            factor_risk_decomposition = compute_factor_risk_decomposition(
                asset_returns=asset_returns,
                portfolio_weights=_current_weights_series,
                risk_free_rate=risk_free_rate,
            )
    except Exception:
        pass

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
        "non_portfolio_cash_df": non_portfolio_cash_df,
        "non_portfolio_cash_value": non_portfolio_cash_value,
        "investments_net_worth": investments_net_worth,
        "user_settings": user_settings,
        "monthly_contribution": monthly_contribution,
        "semi_annual_contribution": semi_annual_contribution,
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
        "min_cvar_row": min_cvar_row,
        "hrp_result": hrp_result,
        "erc_result": erc_result,
        "usable": usable,
        "fx_rate_cache": _fx_cache,
        "alpaca_available": alpaca_available,
        # ── Quant Engine v2 ──────────────────────────────────────────────────
        "rebalancing_bands": rebalancing_bands,
        "net_alpha_df": net_alpha_df,
        "after_tax_drag": after_tax_drag,
        "liquidity_df": liquidity_df,
        "model_agreement": model_agreement,
        "expected_return_bands": expected_return_bands,
        "bl_explanation": bl_explanation,
        "tracking_error_budget": tracking_error_budget,
        "walk_forward_metrics": walk_forward_metrics,
        "regime_probabilities": regime_probabilities,
        "dynamic_weight_caps": dynamic_weight_caps,
        "expected_drawdown_profile": expected_drawdown_profile,
        "model_drift": model_drift,
        "naive_benchmark_df": naive_benchmark_df,
        "factor_risk_decomposition": factor_risk_decomposition,
    }

    if _should_auto_snapshot(ctx):
        try:
            from pages_app.portfolio_history import save_portfolio_snapshot
            save_portfolio_snapshot(ctx, notes="Auto snapshot — market close 6pm Colombia")
            st.session_state["last_auto_snapshot_date"] = str(datetime.now(_COLOMBIA_TZ).date())
        except Exception as e:
            st.warning(f"⚠️ Auto snapshot failed: {e}")

    try:
        from email_report import should_send_monthly_report, send_monthly_report
        ok, month_str = should_send_monthly_report(ctx)
        if ok:
            send_monthly_report(ctx, month_str)
    except Exception as e:
        st.warning(f"⚠️ Monthly report failed: {e}")

    try:
        from alerts import check_alert_conditions, should_send_alerts, send_alert_telegram
        active_alerts = check_alert_conditions(ctx)
        ctx["active_alerts"] = active_alerts
        if should_send_alerts(ctx, active_alerts):
            send_alert_telegram(active_alerts, ctx)
    except Exception:
        ctx["active_alerts"] = []

    return ctx
