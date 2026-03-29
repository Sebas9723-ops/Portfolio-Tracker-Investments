import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import (
    info_metric,
    info_section,
    render_market_clocks,
    render_page_title,
    render_private_dashboard_logo,
    render_status_bar,
)


def _render_control_buttons(ctx):
    c1, c2, c3 = st.columns(3)

    if c1.button("Refresh Market Data", use_container_width=True):
        st.rerun()

    if c2.button("Recalculate Portfolio", use_container_width=True):
        st.rerun()

    if c3.button("Sync Private Data", use_container_width=True):
        if ctx["mode"] == "Private" and ctx["authenticated"]:
            st.cache_data.clear()
            st.rerun()
        else:
            st.info("Private sync is only available in Private mode.")


def _get_max_sharpe_target_map(ctx, df):
    tickers = df["Ticker"].tolist()

    if ctx.get("max_sharpe_row") is None or not ctx.get("usable"):
        raw = df.set_index("Ticker")["Target Weight"].to_dict()
    else:
        usable = list(ctx["usable"])
        arr = np.array(ctx["max_sharpe_row"]["Weights"], dtype=float)
        raw = {ticker: 0.0 for ticker in tickers}
        if len(arr) == len(usable):
            for ticker, weight in zip(usable, arr):
                raw[ticker] = float(weight)

    total = float(sum(max(float(v), 0.0) for v in raw.values()))
    if total <= 0:
        equal = 1.0 / len(tickers) if tickers else 0.0
        return {t: equal for t in tickers}

    return {t: max(float(raw.get(t, 0.0)), 0.0) / total for t in tickers}


def _build_top_actions_table(ctx):
    df = ctx["df"].copy()
    if df.empty:
        return pd.DataFrame()

    target_map = _get_max_sharpe_target_map(ctx, df)
    holdings_total = float(df["Value"].sum())

    df["Recommended Weight %"] = df["Ticker"].map(lambda t: float(target_map.get(t, 0.0)) * 100.0)
    df["Gap %"] = df["Weight %"] - df["Recommended Weight %"]

    if holdings_total > 0:
        df[f"Trade To Max Sharpe ({ctx['base_currency']})"] = (
            (df["Recommended Weight %"] - df["Weight %"]) / 100.0 * holdings_total
        )
    else:
        df[f"Trade To Max Sharpe ({ctx['base_currency']})"] = 0.0

    df["Action"] = np.where(
        df["Gap %"] > 0,
        "Trim / Sell",
        np.where(df["Gap %"] < 0, "Buy / Add", "Hold"),
    )

    out = df[
        [
            "Ticker",
            "Name",
            "Action",
            "Weight %",
            "Recommended Weight %",
            "Gap %",
            f"Trade To Max Sharpe ({ctx['base_currency']})",
        ]
    ].copy()

    out = out[out["Action"] != "Hold"].copy()
    out = out.sort_values("Gap %", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
    return out.head(5)


def _build_performance_vs_benchmark_pct_chart(ctx):
    portfolio_returns = ctx.get("portfolio_returns")
    benchmark_returns = ctx.get("benchmark_returns")

    if portfolio_returns is None or portfolio_returns.empty:
        return None

    fig = go.Figure()

    portfolio_cum = (1 + portfolio_returns).cumprod() - 1
    portfolio_last = float(portfolio_cum.iloc[-1]) if not portfolio_cum.empty else 0.0
    portfolio_name = f"Portfolio ({portfolio_last:.2%})"

    fig.add_scatter(
        x=portfolio_cum.index,
        y=portfolio_cum,
        mode="lines",
        name=portfolio_name,
        hovertemplate="%{x|%Y-%m-%d}<br>Portfolio: %{y:.2%}<extra></extra>",
    )

    if benchmark_returns is not None and not benchmark_returns.empty:
        aligned = pd.concat(
            [portfolio_returns.rename("Portfolio"), benchmark_returns.rename("VOO")],
            axis=1,
        ).dropna()

        if not aligned.empty:
            voo_cum = (1 + aligned["VOO"]).cumprod() - 1
            voo_last = float(voo_cum.iloc[-1]) if not voo_cum.empty else 0.0
            voo_name = f"VOO ({voo_last:.2%})"

            fig.add_scatter(
                x=voo_cum.index,
                y=voo_cum,
                mode="lines",
                name=voo_name,
                hovertemplate="%{x|%Y-%m-%d}<br>VOO: %{y:.2%}<extra></extra>",
            )

    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=420,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Date",
        yaxis_title="Return",
        yaxis=dict(tickformat=".0%"),
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


def render_dashboard(ctx):
    render_page_title("Dashboard")

    render_private_dashboard_logo(
        mode=ctx["mode"],
        authenticated=ctx["authenticated"],
    )

    render_status_bar(
        mode=ctx["mode"],
        base_currency=ctx["base_currency"],
        profile=ctx["profile"],
        tc_model=ctx["tc_model"],
        sheets_ok=ctx["positions_sheet_available"],
    )

    _render_control_buttons(ctx)
    render_market_clocks()

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Total Portfolio", f"{ctx['base_currency']} {ctx['total_portfolio_value']:,.2f}", "Holdings plus cash.")
    info_metric(c2, "Invested Assets", f"{ctx['base_currency']} {ctx['holdings_value']:,.2f}", "Market value of invested holdings.")
    info_metric(c3, "Cash", f"{ctx['base_currency']} {ctx['cash_total_value']:,.2f}", "Cash balances converted to base currency.")
    info_metric(c4, "Unrealized PnL", f"{ctx['base_currency']} {ctx['unrealized_pnl']:,.2f}", "Open profit and loss.")

    c5, c6, c7, c8 = st.columns(4)
    info_metric(c5, "Return", f"{ctx['total_return']:.2%}", "Cumulative return over the available history.")
    info_metric(c6, "Volatility", f"{ctx['volatility']:.2%}", "Annualized portfolio volatility.")
    info_metric(c7, "Sharpe Ratio", f"{ctx['sharpe']:.2f}", "Portfolio Sharpe ratio.")
    info_metric(c8, "Realized PnL", f"{ctx['base_currency']} {ctx['realized_pnl']:,.2f}", "Closed profit and loss.")

    actions_df = _build_top_actions_table(ctx)
    info_section(
        "Top Actions",
        "Largest drifts versus the Max Sharpe allocation. Review these first.",
    )
    if actions_df.empty:
        st.success("No material drifts detected versus the current recommendation.")
    else:
        st.dataframe(actions_df, use_container_width=True, height=260)

    perf_fig = _build_performance_vs_benchmark_pct_chart(ctx)
    if perf_fig is not None:
        info_section(
            "Performance vs Benchmark",
            "Portfolio cumulative return versus VOO, displayed in percentage terms.",
        )
        st.plotly_chart(
            perf_fig,
            use_container_width=True,
            key="dashboard_performance_pct_chart_phase4a",
        )