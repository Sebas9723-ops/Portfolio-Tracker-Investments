import streamlit as st
import plotly.graph_objects as go

from app_core import render_page_title, render_status_bar, info_section, info_metric


def render_analytics_page(ctx):
    render_page_title("Analytics")

    render_status_bar(
        mode=ctx["mode"],
        base_currency=ctx["base_currency"],
        profile=ctx["profile"],
        tc_model=ctx["tc_model"],
        sheets_ok=(ctx["positions_sheet_available"] if ctx["mode"] == "Private" else True),
    )

    info_section("Performance Metrics", f"Return and risk indicators in base currency ({ctx['base_currency']}) derived from historical daily returns.")

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Return", f"{ctx['total_return']:.2%}", "Cumulative portfolio return over the historical sample.")
    info_metric(c2, "Volatility", f"{ctx['volatility']:.2%}", "Annualized standard deviation of portfolio returns.")
    info_metric(c3, "Sharpe Ratio", f"{ctx['sharpe']:.2f}", "Risk-adjusted return using the selected risk-free rate.")
    info_metric(c4, "Max Drawdown", f"{ctx['max_drawdown']:.2%}", "Largest peak-to-trough decline over the sample.")

    c5, c6, c7, c8 = st.columns(4)
    info_metric(c5, "Alpha", f"{ctx['alpha']:.2%}", "Return unexplained by benchmark beta exposure.")
    info_metric(c6, "Beta", f"{ctx['beta']:.2f}", "Sensitivity of portfolio returns to benchmark returns.")
    info_metric(c7, "Tracking Error", f"{ctx['tracking_error']:.2%}", "Annualized volatility of active returns versus the benchmark.")
    info_metric(c8, "Information Ratio", f"{ctx['information_ratio']:.2f}", "Active return divided by tracking error.")

    if ctx["fig_perf"] is not None:
        info_section("Performance vs Benchmark", "Cumulative growth of the portfolio compared with the benchmark (VOO).")
        st.plotly_chart(ctx["fig_perf"], use_container_width=True)

        p1, p2, p3 = st.columns(3)
        info_metric(p1, "Portfolio Cumulative Return", f"{ctx['portfolio_cum_return']:.2%}", "End-to-end cumulative return of the portfolio.")
        if ctx["benchmark_cum_return"] is not None:
            info_metric(p2, "Benchmark Cumulative Return", f"{ctx['benchmark_cum_return']:.2%}", "End-to-end cumulative return of the benchmark.")
            info_metric(p3, "Excess Return vs Benchmark", f"{ctx['excess_vs_benchmark']:.2%}", "Portfolio cumulative return minus benchmark cumulative return.")
        else:
            info_metric(p2, "Benchmark Cumulative Return", "N/A", "Benchmark data is not available.")
            info_metric(p3, "Excess Return vs Benchmark", "N/A", "Benchmark data is not available.")

    info_section("Rolling Metrics", "Time-varying view of portfolio risk and risk-adjusted performance using a rolling historical window.")

    if ctx["rolling_df"].empty:
        st.info("Rolling metrics are not available for the current data window.")
    else:
        rolling_metric = st.selectbox(
            "Rolling Metric",
            ["Rolling Volatility", "Rolling Sharpe", "Rolling Beta", "Rolling Drawdown"],
            help="Select the rolling indicator to display."
        )

        available_metric = rolling_metric
        if available_metric not in ctx["rolling_df"].columns:
            available_metric = ctx["rolling_df"].columns[0]

        fig_roll = go.Figure()
        fig_roll.add_scatter(
            x=ctx["rolling_df"].index,
            y=ctx["rolling_df"][available_metric],
            name=available_metric,
        )
        fig_roll.update_layout(
            paper_bgcolor="#0b0f14",
            plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"),
            xaxis_title="Date",
            yaxis_title=available_metric,
        )
        st.plotly_chart(fig_roll, use_container_width=True)