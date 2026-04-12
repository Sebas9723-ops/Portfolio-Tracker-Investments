import datetime
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils_aggrid import show_aggrid

from app_core import (
    build_blended_benchmark_returns,
    build_multi_benchmark_comparison,
    compute_brinson_attribution,
    compute_extended_ratios,
    compute_ff3_exposure,
    compute_return_attribution,
    compute_rolling_metrics,
    compute_rolling_pair_correlations,
    compute_twr,
    compute_volatility_regime,
    info_metric,
    info_section,
    render_page_title,
)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_rolling(portfolio_returns: pd.Series, benchmark_returns: pd.Series, rfr: float, window: int):
    return compute_rolling_metrics(portfolio_returns, benchmark_returns, rfr, window)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_extended(portfolio_returns: pd.Series, benchmark_returns: pd.Series, rfr: float, max_dd: float):
    return compute_extended_ratios(portfolio_returns, benchmark_returns, rfr, max_dd)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_brinson(df: pd.DataFrame, asset_returns: pd.DataFrame, policy_json: str, benchmark_returns: pd.Series):
    policy_map = json.loads(policy_json)
    return compute_brinson_attribution(df, asset_returns, policy_map, benchmark_returns)


@st.cache_data(ttl=86400, show_spinner=False)
def _cached_ff3(portfolio_returns: pd.Series, rfr: float):
    return compute_ff3_exposure(portfolio_returns, rfr)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_vol_regime(portfolio_returns: pd.Series):
    return compute_volatility_regime(portfolio_returns)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_multi_benchmark(portfolio_returns: pd.Series, base_currency: str, _fx_hist: pd.DataFrame, rfr: float):
    return build_multi_benchmark_comparison(portfolio_returns, base_currency, _fx_hist, rfr)


def _compute_relative_metrics(ctx):
    portfolio_returns = ctx.get("portfolio_returns")
    benchmark_returns = ctx.get("resolved_benchmark_returns")

    if portfolio_returns is None or portfolio_returns.empty or benchmark_returns is None or benchmark_returns.empty:
        return None

    aligned = (
        portfolio_returns.rename("Portfolio")
        .to_frame()
        .join(benchmark_returns.rename("VOO"), how="inner")
        .dropna()
    )

    if aligned.empty:
        return None

    bench_var = aligned["VOO"].var()
    beta = None
    alpha = None
    tracking_error = None
    information_ratio = None

    if bench_var > 0:
        beta = float(aligned.cov().loc["Portfolio", "VOO"] / bench_var)

    p_mean = float(aligned["Portfolio"].mean() * 252)
    b_mean = float(aligned["VOO"].mean() * 252)

    if beta is not None:
        alpha = float(p_mean - beta * b_mean)

    excess = aligned["Portfolio"] - aligned["VOO"]
    tracking_error = float(excess.std() * 252**0.5) if not excess.empty else None

    if tracking_error and tracking_error > 0:
        information_ratio = float((excess.mean() * 252) / tracking_error)

    return {
        "alpha": alpha,
        "beta": beta,
        "tracking_error": tracking_error,
        "information_ratio": information_ratio,
        "aligned": aligned,
    }


def _build_performance_chart_pct(ctx):
    portfolio_returns = ctx.get("portfolio_returns")
    benchmark_returns = ctx.get("resolved_benchmark_returns")

    if portfolio_returns is None or portfolio_returns.empty:
        return None

    fig = go.Figure()

    portfolio_cum = (1 + portfolio_returns).cumprod() - 1
    fig.add_scatter(
        x=portfolio_cum.index,
        y=portfolio_cum,
        mode="lines",
        name=f"Portfolio ({portfolio_cum.iloc[-1]:.2%})",
        hovertemplate="%{x|%Y-%m-%d}<br>Portfolio: %{y:.2%}<extra></extra>",
    )

    if benchmark_returns is not None and not benchmark_returns.empty:
        aligned = (
            portfolio_returns.rename("Portfolio")
            .to_frame()
            .join(benchmark_returns.rename("VOO"), how="inner")
            .dropna()
        )
        if not aligned.empty:
            voo_cum = (1 + aligned["VOO"]).cumprod() - 1
            fig.add_scatter(
                x=voo_cum.index,
                y=voo_cum,
                mode="lines",
                name=f"VOO ({voo_cum.iloc[-1]:.2%})",
                hovertemplate="%{x|%Y-%m-%d}<br>VOO: %{y:.2%}<extra></extra>",
            )

    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=430,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Date",
        yaxis_title="Return",
        yaxis=dict(tickformat=".0%"),
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


def _build_rolling_metrics_chart(rolling_df):
    if rolling_df is None or rolling_df.empty:
        return None

    fig = go.Figure()

    if "Rolling Volatility" in rolling_df.columns:
        fig.add_scatter(
            x=rolling_df.index,
            y=rolling_df["Rolling Volatility"],
            mode="lines",
            name="Rolling Volatility",
            hovertemplate="%{x|%Y-%m-%d}<br>Rolling Volatility: %{y:.2%}<extra></extra>",
        )

    if "Rolling Sharpe" in rolling_df.columns:
        fig.add_scatter(
            x=rolling_df.index,
            y=rolling_df["Rolling Sharpe"],
            mode="lines",
            name="Rolling Sharpe",
            hovertemplate="%{x|%Y-%m-%d}<br>Rolling Sharpe: %{y:.2f}<extra></extra>",
        )

    if "Rolling Beta" in rolling_df.columns:
        fig.add_scatter(
            x=rolling_df.index,
            y=rolling_df["Rolling Beta"],
            mode="lines",
            name="Rolling Beta",
            hovertemplate="%{x|%Y-%m-%d}<br>Rolling Beta: %{y:.2f}<extra></extra>",
        )

    if "Rolling Drawdown" in rolling_df.columns:
        fig.add_scatter(
            x=rolling_df.index,
            y=rolling_df["Rolling Drawdown"],
            mode="lines",
            name="Rolling Drawdown",
            hovertemplate="%{x|%Y-%m-%d}<br>Rolling Drawdown: %{y:.2%}<extra></extra>",
        )

    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=380,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Date",
        yaxis_title="Metric",
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


def _fmt(v, fmt=".2%", fallback="—") -> str:
    try:
        return format(float(v), fmt)
    except Exception:
        return fallback


def _render_extended_ratios(er):
    if not er:
        return
    info_section(
        "Extended Ratios",
        "Sortino penalizes only downside volatility. Calmar = return / max drawdown. "
        "Upside/Downside Capture vs VOO. Omega = gain potential / loss potential.",
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    info_metric(c1, "Sortino", _fmt(er.get("sortino"), ".2f"), "Return per unit of downside risk.")
    info_metric(c2, "Calmar", _fmt(er.get("calmar"), ".2f"), "Annualized return / |max drawdown|.")
    info_metric(c3, "Upside Capture", _fmt(er.get("upside_capture"), ".1f") + "%" if er.get("upside_capture") is not None else "—", "% of benchmark upside captured.")
    info_metric(c4, "Downside Capture", _fmt(er.get("downside_capture"), ".1f") + "%" if er.get("downside_capture") is not None else "—", "% of benchmark downside suffered.")
    info_metric(c5, "Omega", _fmt(er.get("omega"), ".2f"), "Gain potential over loss potential above risk-free rate.")


def _render_returns_comparison(ctx):
    mwr = ctx.get("mwr_result", {})
    twr_result: dict = {}

    # TWR — computed lazily from snapshots
    try:
        from pages_app.portfolio_history import load_portfolio_snapshots, filter_snapshots_for_context
        snaps = load_portfolio_snapshots()
        if not snaps.empty:
            filtered = filter_snapshots_for_context(snaps, ctx.get("mode"), ctx.get("base_currency"))
            twr_result = compute_twr(filtered, ctx.get("transactions_df"))
    except Exception:
        pass

    twr_val = twr_result.get("twr")
    mwr_val = mwr.get("mwr")
    n_periods = twr_result.get("n_periods", 0)
    n_tx = mwr.get("n_transactions", 0)
    start = twr_result.get("start_date", "—")
    end = twr_result.get("end_date", "—")

    invested = float(ctx.get("invested_capital", 0.0))
    unrealized = float(ctx.get("unrealized_pnl", 0.0))
    realized = float(ctx.get("realized_pnl", 0.0))
    total_pnl = unrealized + realized
    simple_return = total_pnl / invested if invested > 0 else None
    ccy = ctx.get("base_currency", "")

    info_section(
        "Return Measures",
        "TWR (Time-Weighted) is the institutional standard — eliminates the effect of cash flow timing. "
        "MWR (Money-Weighted / IRR) reflects your actual investor experience including when you deployed capital. "
        "Simple Return is the direct total gain vs your cost basis, not annualized.",
    )

    r1c1, r1c2, r1c3 = st.columns(3)
    simple_str = _fmt(simple_return) if simple_return is not None else "—"
    pnl_str = f"{ccy} {total_pnl:+,.2f}" if invested > 0 else "—"
    invested_str = f"{ccy} {invested:,.2f}" if invested > 0 else "—"
    info_metric(r1c1, "Simple Return", simple_str, "Total gain vs cost basis (unrealized + realized). Not annualized.")
    info_metric(r1c2, "Total P&L", pnl_str, "Unrealized + realized gain/loss in base currency.")
    info_metric(r1c3, "Invested Capital", invested_str, "Sum of cost basis across all open positions.")

    twr_tooltip = (
        f"Chain-linked over {n_periods} snapshots ({start} → {end})."
        if twr_val is not None
        else "No snapshots saved yet. Use Save Portfolio Snapshot from the Dashboard to enable TWR."
    )
    mwr_tooltip = (
        f"Annualized IRR from {n_tx} transactions."
        if mwr_val is not None
        else "Need ≥2 transactions with dates to compute IRR."
    )
    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "TWR", _fmt(twr_val) if twr_val is not None else "—", twr_tooltip)
    info_metric(c2, "MWR (IRR)", _fmt(mwr_val) if mwr_val is not None else "—", mwr_tooltip)
    info_metric(c3, "Historical Return", _fmt(ctx.get("total_return")), "Cumulative return from price history.")
    excess = (twr_val or 0.0) - (mwr_val or 0.0) if twr_val is not None and mwr_val is not None else None
    info_metric(c4, "TWR − MWR", _fmt(excess) if excess is not None else "—", "Positive = timing helped; Negative = timing hurt.")


def _render_brinson(brinson_df):
    if brinson_df is None or brinson_df.empty:
        return

    info_section(
        "Brinson-Hood-Beebower Attribution",
        "Decomposes active return vs VOO benchmark per asset. "
        "Allocation = effect of over/underweighting. Selection = effect of asset return vs benchmark. "
        "Interaction = combined weight × return divergence.",
    )
    show_aggrid(brinson_df, height=300, key="aggrid_analytics_brinson")

    fig = go.Figure()
    fig.add_bar(x=brinson_df["Ticker"], y=brinson_df["Allocation Effect"], name="Allocation")
    fig.add_bar(x=brinson_df["Ticker"], y=brinson_df["Selection Effect"], name="Selection")
    fig.add_bar(x=brinson_df["Ticker"], y=brinson_df["Interaction Effect"], name="Interaction")
    fig.update_layout(
        barmode="stack",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=360,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Ticker",
        yaxis_title="Attribution (%)",
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    st.plotly_chart(fig, use_container_width=True, key="analytics_brinson_chart")


def _render_ff3(ff3):
    if not ff3:
        return

    info_section(
        "Fama-French 3-Factor Exposure",
        "OLS regression of portfolio excess returns on Market (Mkt-RF), Size (SMB), and Value (HML) factors. "
        "Factors are proxied by IVV / IWM / IVE / IVW ETFs. t-stats shown as tooltip.",
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    alpha_ann = float(ff3.get("alpha", 0))
    info_metric(c1, "FF3 Alpha (ann.)", _fmt(alpha_ann), f"t = {ff3.get('alpha_tstat', 0):.2f}")
    info_metric(c2, "Market β", _fmt(ff3.get("mkt_beta"), ".2f"), f"t = {ff3.get('mkt_tstat', 0):.2f}")
    info_metric(c3, "SMB β (Size)", _fmt(ff3.get("smb_beta"), ".2f"), f"t = {ff3.get('smb_tstat', 0):.2f}  (+) = small-cap tilt")
    info_metric(c4, "HML β (Value)", _fmt(ff3.get("hml_beta"), ".2f"), f"t = {ff3.get('hml_tstat', 0):.2f}  (+) = value tilt")
    info_metric(c5, "R²", _fmt(ff3.get("r_squared"), ".2%"), f"{ff3.get('n_obs', 0)} observations")
    st.caption(f"Factor proxy source: {ff3.get('source', 'ETF Proxy')}")


def _render_volatility_regime(vr):
    if not vr or vr.get("ewma_vol_series") is None or vr["ewma_vol_series"].empty:
        return

    regime = vr.get("current_regime", "UNKNOWN")
    current_ewma = vr.get("current_ewma_vol", float("nan"))
    ewma_series = vr["ewma_vol_series"]
    rolling_21 = vr.get("rolling_21d")
    rolling_63 = vr.get("rolling_63d")

    regime_colors = {"LOW": "#00e676", "NORMAL": "#f3a712", "HIGH": "#ff7043", "CRISIS": "#ff1744", "UNKNOWN": "#888"}
    badge_color = regime_colors.get(regime, "#888")

    info_section(
        "Volatility Regime",
        "EWMA volatility (RiskMetrics λ=0.94) annualized. Regimes: LOW (<10%), NORMAL (10–20%), HIGH (20–35%), CRISIS (>35%).",
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(
        f"<div style='text-align:center;padding:12px 8px;border-radius:6px;background:#1a1f2e;border:2px solid {badge_color}'>"
        f"<div style='color:{badge_color};font-size:20px;font-weight:bold'>{regime}</div>"
        f"<div style='color:#888;font-size:12px;margin-top:4px'>Current Regime</div></div>",
        unsafe_allow_html=True,
    )
    info_metric(c2, "EWMA Vol (Ann.)", f"{current_ewma:.2%}" if not np.isnan(current_ewma) else "—", "Current annualized EWMA volatility.")
    if rolling_21 is not None and not rolling_21.empty:
        info_metric(c3, "21-day Hist. Vol", f"{rolling_21.iloc[-1]:.2%}" if not np.isnan(rolling_21.iloc[-1]) else "—", "Rolling 21-day historical volatility.")
    if rolling_63 is not None and not rolling_63.empty:
        info_metric(c4, "63-day Hist. Vol", f"{rolling_63.iloc[-1]:.2%}" if not np.isnan(rolling_63.iloc[-1]) else "—", "Rolling 63-day historical volatility.")

    # Background band shading by regime thresholds
    fig = go.Figure()
    for threshold, color, label in [
        (0.10, "rgba(0,230,118,0.08)", "LOW <10%"),
        (0.20, "rgba(243,167,18,0.08)", "NORMAL 10-20%"),
        (0.35, "rgba(255,112,67,0.08)", "HIGH 20-35%"),
    ]:
        fig.add_hrect(
            y0=0, y1=threshold,
            fillcolor=color, line_width=0,
            annotation_text=label, annotation_position="right",
            annotation=dict(font=dict(color="#888", size=10)),
        )
    fig.add_hrect(y0=0.35, y1=1.0, fillcolor="rgba(255,23,68,0.06)", line_width=0,
                  annotation_text="CRISIS >35%", annotation_position="right",
                  annotation=dict(font=dict(color="#888", size=10)))

    fig.add_scatter(x=ewma_series.index, y=ewma_series, mode="lines", name="EWMA Vol",
                    line=dict(color="#f3a712", width=2),
                    hovertemplate="%{x|%Y-%m-%d}<br>EWMA Vol: %{y:.2%}<extra></extra>")
    if rolling_21 is not None and not rolling_21.empty:
        fig.add_scatter(x=rolling_21.index, y=rolling_21, mode="lines", name="21-day Rolling",
                        line=dict(color="#00c8ff", width=1, dash="dot"),
                        hovertemplate="%{x|%Y-%m-%d}<br>21d Vol: %{y:.2%}<extra></extra>")
    if rolling_63 is not None and not rolling_63.empty:
        fig.add_scatter(x=rolling_63.index, y=rolling_63, mode="lines", name="63-day Rolling",
                        line=dict(color="#ce93d8", width=1, dash="dash"),
                        hovertemplate="%{x|%Y-%m-%d}<br>63d Vol: %{y:.2%}<extra></extra>")

    fig.update_layout(
        paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"), height=380,
        margin=dict(t=20, b=20, l=20, r=80),
        xaxis_title="Date", yaxis_title="Annualized Volatility",
        yaxis=dict(tickformat=".0%"),
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    st.plotly_chart(fig, use_container_width=True, key="analytics_vol_regime_chart")


def _render_contribution_growth(ctx):
    transactions_df = ctx.get("transactions_df")
    portfolio_returns = ctx.get("portfolio_returns", pd.Series(dtype=float))
    holdings_value = float(ctx.get("holdings_value", 0.0))
    ccy = ctx.get("base_currency", "USD")

    if transactions_df is None or transactions_df.empty:
        return
    if portfolio_returns.empty or holdings_value <= 0:
        return

    # Reconstruct portfolio value from price history scaled to today's holdings value
    cum = (1 + portfolio_returns).cumprod()
    portfolio_value_series = (cum / float(cum.iloc[-1])) * holdings_value

    # Cumulative net contributions from transaction log (prices in native currency, approximate)
    tx = transactions_df.copy()
    tx["date"] = pd.to_datetime(tx["date"], errors="coerce")
    tx["shares"] = pd.to_numeric(tx["shares"], errors="coerce").fillna(0.0)
    tx["price"] = pd.to_numeric(tx["price"], errors="coerce").fillna(0.0)
    tx["fees"] = pd.to_numeric(tx["fees"], errors="coerce").fillna(0.0)
    tx = tx.dropna(subset=["date"])

    tx["gross"] = tx["shares"] * tx["price"] + tx["fees"]
    tx["net"] = tx.apply(
        lambda r: r["gross"] if str(r.get("type", "")).upper() == "BUY" else -r["gross"],
        axis=1,
    )

    contributions = tx.groupby("date")["net"].sum().sort_index().cumsum()
    if contributions.empty:
        return

    # Any capital deployed before the first recorded transaction (e.g. positions
    # set up in the base portfolio file without a matching transaction) shows up as
    # a gap between invested_capital and the transaction sum.  Treat that gap as an
    # initial seed injected at the very start of the price-history window.
    invested_capital = float(ctx.get("invested_capital", 0.0))
    tx_total = float(contributions.iloc[-1])
    initial_seed = max(0.0, invested_capital - tx_total)

    # Align contributions to the price history index, forward-filling gaps
    full_idx = portfolio_value_series.index
    contributions_aligned = contributions.reindex(full_idx).ffill()
    first_tx = contributions.index[0]
    contributions_aligned.loc[contributions_aligned.index < first_tx] = 0.0
    contributions_aligned = contributions_aligned.fillna(0.0)

    # Add the seed uniformly to the entire series so the line starts at seed and
    # ends at seed + recorded transactions
    contributions_aligned = contributions_aligned + initial_seed

    info_section(
        "Contribution vs Growth",
        "Capital invested over time versus estimated portfolio market value. "
        "The gap above the blue line represents cumulative market gains. "
        "Contributions shown in transaction prices (approximate for multi-currency portfolios).",
    )

    fig = go.Figure()
    fig.add_scatter(
        x=contributions_aligned.index,
        y=contributions_aligned.values,
        name="Invested Capital",
        fill="tozeroy",
        fillcolor="rgba(77, 184, 255, 0.15)",
        line=dict(color="#4db8ff", width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>Invested: " + ccy + " %{y:,.0f}<extra></extra>",
    )
    fig.add_scatter(
        x=portfolio_value_series.index,
        y=portfolio_value_series.values,
        name="Portfolio Value",
        fill="tonexty",
        fillcolor="rgba(243, 167, 18, 0.12)",
        line=dict(color="#f3a712", width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>Value: " + ccy + " %{y:,.0f}<extra></extra>",
    )
    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=400,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Date",
        yaxis_title=f"Value ({ccy})",
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    st.plotly_chart(fig, use_container_width=True, key="analytics_contribution_growth_chart")


def _render_correlation_heatmap(ctx):
    asset_returns = ctx.get("asset_returns")
    if asset_returns is None or asset_returns.empty or asset_returns.shape[1] < 2:
        return

    corr = asset_returns.corr()
    tickers = corr.columns.tolist()
    z = corr.values.tolist()
    text = [[f"{v:.2f}" for v in row] for row in corr.values]

    info_section(
        "Correlation Matrix",
        "Pairwise return correlation between holdings over the available history. "
        "1 = move in lockstep · 0 = uncorrelated · −1 = move in opposite directions. "
        "High correlation between positions means less real diversification.",
    )

    fig = go.Figure(go.Heatmap(
        z=z,
        x=tickers,
        y=tickers,
        colorscale="RdBu_r",
        zmin=-1,
        zmax=1,
        text=text,
        texttemplate="%{text}",
        textfont=dict(size=12, color="#e6e6e6"),
        colorbar=dict(title="r"),
    ))
    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=max(320, len(tickers) * 65),
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis=dict(tickfont=dict(color="#f3a712")),
        yaxis=dict(tickfont=dict(color="#f3a712")),
    )
    st.plotly_chart(fig, use_container_width=True, key="analytics_correlation_heatmap")


def _render_multi_benchmark(mb):
    if not mb:
        return
    fig = mb.get("fig")
    summary_df = mb.get("summary_df")

    info_section(
        "Multi-Benchmark Comparison",
        "Portfolio vs S&P 500 (SPY), MSCI World (ACWI), Bonds (BND), and blended 60/40 since inception.",
    )
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True, key="analytics_multi_benchmark_chart")
    if summary_df is not None and not summary_df.empty:
        show_aggrid(summary_df, height=400, key="aggrid_analytics_multi_benchmark")


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_return_attribution(asset_returns, historical_base, df_json, period):
    import io
    df = pd.read_json(io.StringIO(df_json), orient="records")
    return compute_return_attribution(asset_returns, historical_base, df, period)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_rolling_corr(asset_returns):
    return compute_rolling_pair_correlations(asset_returns, windows=(126, 252))


def _render_return_attribution(ctx):
    asset_returns = ctx.get("asset_returns")
    historical_base = ctx.get("historical_base")
    df = ctx.get("df", pd.DataFrame())
    if asset_returns is None or asset_returns.empty or df.empty:
        return

    info_section(
        "Return Attribution by ETF",
        "Each ETF's contribution to total portfolio return = average weight × ETF return in the period.",
    )
    period = st.selectbox("Period", ["1M", "3M", "6M", "YTD", "1Y"], key="attr_period_sel")
    attr_df = _cached_return_attribution(asset_returns, historical_base, df.to_json(orient="records"), period)
    if attr_df is None or attr_df.empty:
        st.info("Not enough data for the selected period.")
        return

    total_contrib = float(attr_df["Contribution"].sum())
    c1, c2 = st.columns(2)
    c1.metric("Total Attributed Return", f"{total_contrib:.2%}")
    c2.metric("Period", period)

    attr_df["ETF Return"] = attr_df["ETF Return"].map(lambda x: f"{x:.2%}")
    attr_df["Avg Weight"] = attr_df["Avg Weight"].map(lambda x: f"{x:.1%}")
    attr_df["Contribution"] = attr_df["Contribution"].map(lambda x: f"{x:+.2%}")
    show_aggrid(attr_df[["Ticker", "Name", "Avg Weight", "ETF Return", "Contribution"]],
               height=400, key="aggrid_analytics_attribution")

    raw_attr = compute_return_attribution(
        ctx.get("asset_returns"), ctx.get("historical_base"), ctx.get("df", pd.DataFrame()), period
    )
    if raw_attr is not None and not raw_attr.empty:
        colors = ["#26a69a" if v >= 0 else "#ef5350" for v in raw_attr["Contribution"]]
        fig = go.Figure(go.Bar(
            x=raw_attr["Ticker"],
            y=raw_attr["Contribution"],
            marker_color=colors,
            text=[f"{v:+.2%}" for v in raw_attr["Contribution"]],
            textposition="outside",
        ))
        fig.update_layout(
            paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"), height=320,
            margin=dict(t=20, b=20, l=20, r=20),
            yaxis=dict(tickformat=".1%", zeroline=True, zerolinecolor="#555"),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, key="analytics_attribution_bar")


def _render_rolling_correlation(ctx):
    asset_returns = ctx.get("asset_returns")
    if asset_returns is None or asset_returns.empty or asset_returns.shape[1] < 2:
        return

    info_section(
        "Rolling Correlation",
        "Pairwise rolling Pearson correlation between ETFs. 6M = 126 trading days · 12M = 252 trading days.",
    )
    corr_data = _cached_rolling_corr(asset_returns)
    if not corr_data:
        st.info("Not enough history for rolling correlation.")
        return

    tickers = asset_returns.columns.tolist()
    pairs = [f"{t1}/{t2}" for i, t1 in enumerate(tickers) for t2 in tickers[i + 1:]]

    mode = st.radio("View", ["All pairs", "Single pair"], horizontal=True, key="rc_mode")
    fig = go.Figure()

    if mode == "All pairs":
        window = st.selectbox("Window", [126, 252], format_func=lambda w: "6M" if w == 126 else "12M", key="rc_win")
        df_corr = corr_data.get(window, pd.DataFrame())
        for col in df_corr.columns:
            fig.add_scatter(x=df_corr.index, y=df_corr[col], mode="lines", name=col,
                            hovertemplate="%{x|%Y-%m-%d}<br>" + col + ": %{y:.2f}<extra></extra>")
    else:
        pair = st.selectbox("ETF Pair", pairs, key="rc_pair")
        for w, label in [(126, "6M"), (252, "12M")]:
            s = corr_data.get(w, pd.DataFrame()).get(pair, pd.Series(dtype=float))
            fig.add_scatter(x=s.index, y=s, mode="lines", name=label,
                            hovertemplate="%{x|%Y-%m-%d}<br>" + label + ": %{y:.2f}<extra></extra>")

    fig.add_hline(y=0, line_dash="dot", line_color="#555")
    fig.update_layout(
        paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"), height=400,
        margin=dict(t=20, b=20, l=20, r=20),
        yaxis=dict(range=[-1.05, 1.05], tickformat=".2f", title="Correlation"),
        xaxis_title="Date",
        legend=dict(orientation="h", y=1.08),
    )
    st.plotly_chart(fig, use_container_width=True, key="analytics_rolling_corr_chart")


def render_analytics_page(ctx):
    render_page_title("Analytics")

    # ── Sidebar controls (must be outside fragment in Streamlit 1.41+) ───────────
    with st.sidebar.expander("Analytics Settings", expanded=False):
        st.slider("Rolling Window (days)", 21, 252, 63, 21, key="ana_roll_win")
        st.number_input("Risk-free rate", 0.00, 0.20, 0.02, 0.005, format="%.3f", key="ana_rfr")
        st.slider("Blended benchmark VOO %", 0, 100, 60, 5, key="ana_voo_w")

    @st.fragment(run_every=900)
    def _live():
        st.caption(f"Last refreshed: {datetime.datetime.now().strftime('%H:%M:%S')}")

        portfolio_returns = ctx.get("portfolio_returns", pd.Series(dtype=float))
        benchmark_returns = ctx.get("resolved_benchmark_returns", pd.Series(dtype=float))
        asset_returns = ctx.get("asset_returns")
        df = ctx.get("df", pd.DataFrame())
        base_currency = ctx.get("base_currency", "USD")
        fx_hist = ctx.get("fx_hist")
        max_dd = float(ctx.get("max_drawdown", 0.0))
        policy_map = ctx.get("policy_target_map", {})

        rolling_window = st.session_state.get("ana_roll_win", 63)
        rfr            = st.session_state.get("ana_rfr", 0.02)
        voo_w          = st.session_state.get("ana_voo_w", 60) / 100.0

        # ── Compute (all cached) ──────────────────────────────────────────────────
        rolling_df = pd.DataFrame()
        extended = {}
        brinson_df = None
        ff3 = None
        vr = None
        mb = None

        if not portfolio_returns.empty and not benchmark_returns.empty:
            rolling_df = _cached_rolling(portfolio_returns, benchmark_returns, rfr, rolling_window)
            extended = _cached_extended(portfolio_returns, benchmark_returns, rfr, max_dd) or {}

        if not df.empty and asset_returns is not None and not asset_returns.empty and policy_map:
            policy_json = json.dumps({k: float(v) for k, v in policy_map.items()})
            brinson_df = _cached_brinson(df, asset_returns, policy_json, benchmark_returns)

        if not portfolio_returns.empty and len(portfolio_returns) >= 60:
            ff3 = _cached_ff3(portfolio_returns, rfr)

        if not portfolio_returns.empty:
            vr = _cached_vol_regime(portfolio_returns)
            if fx_hist is not None:
                mb = _cached_multi_benchmark(portfolio_returns, base_currency, fx_hist, rfr)

        # ── Header metrics ────────────────────────────────────────────────────────
        rel = _compute_relative_metrics(ctx)
        alpha_txt = "—" if rel is None or rel["alpha"] is None else f"{rel['alpha']:.2%}"
        beta_txt  = "—" if rel is None or rel["beta"] is None else f"{rel['beta']:.2f}"
        te_txt    = "—" if rel is None or rel["tracking_error"] is None else f"{rel['tracking_error']:.2%}"
        ir_txt    = "—" if rel is None or rel["information_ratio"] is None else f"{rel['information_ratio']:.2f}"

        c1, c2, c3, c4 = st.columns(4)
        info_metric(c1, "Alpha", alpha_txt, "Annualized alpha versus VOO.")
        info_metric(c2, "Beta", beta_txt, "Portfolio beta versus VOO.")
        info_metric(c3, "Tracking Error", te_txt, "Annualized tracking error versus VOO.")
        info_metric(c4, "Information Ratio", ir_txt, "Information ratio versus VOO.")

        perf_fig = _build_performance_chart_pct(ctx)
        if perf_fig is not None:
            info_section("Performance", "Portfolio and VOO cumulative performance in percentage terms.")
            st.plotly_chart(perf_fig, use_container_width=True, key="analytics_performance_pct_chart_fixed_v2")

        _render_extended_ratios(extended)
        _render_returns_comparison(ctx)
        _render_brinson(brinson_df)
        _render_ff3(ff3)

        rolling_fig = _build_rolling_metrics_chart(rolling_df if not rolling_df.empty else None)
        if rolling_fig is not None:
            info_section("Rolling Metrics", "Rolling volatility, Sharpe, beta, and drawdown over time.")
            st.plotly_chart(rolling_fig, use_container_width=True, key="analytics_rolling_metrics_chart_fixed_v2")

        _render_volatility_regime(vr)
        _render_multi_benchmark(mb)
        _render_contribution_growth(ctx)
        _render_correlation_heatmap(ctx)
        _render_rolling_correlation(ctx)
        _render_return_attribution(ctx)
    _live()
