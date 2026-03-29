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


def _build_performance_vs_benchmark_pct_figure(ctx):
    portfolio_returns = ctx.get("portfolio_returns")
    benchmark_returns = ctx.get("benchmark_returns")

    if portfolio_returns is None or portfolio_returns.empty:
        return None

    fig = go.Figure()

    portfolio_cum = (1 + portfolio_returns).cumprod() - 1
    fig.add_scatter(
        x=portfolio_cum.index,
        y=portfolio_cum,
        name="Portfolio",
        mode="lines",
        hovertemplate="%{x|%Y-%m-%d}<br>Portfolio: %{y:.2%}<extra></extra>",
    )

    if benchmark_returns is not None and not benchmark_returns.empty:
        aligned = pd.concat(
            [portfolio_returns.rename("Portfolio"), benchmark_returns.rename("VOO")],
            axis=1,
        ).dropna()

        if not aligned.empty:
            voo_cum = (1 + aligned["VOO"]).cumprod() - 1
            fig.add_scatter(
                x=voo_cum.index,
                y=voo_cum,
                name="VOO",
                mode="lines",
                hovertemplate="%{x|%Y-%m-%d}<br>VOO: %{y:.2%}<extra></extra>",
            )

    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=420,
        margin=dict(t=20, b=20, l=20, r=20),
        yaxis_title="Return",
        xaxis_title="Date",
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

    fig_perf = _build_performance_vs_benchmark_pct_figure(ctx)
    if fig_perf is not None:
        info_section(
            "Performance vs Benchmark",
            "Portfolio cumulative return versus VOO, displayed in percentage terms.",
        )
        st.plotly_chart(fig_perf, use_container_width=True, key="dashboard_perf_pct_chart")