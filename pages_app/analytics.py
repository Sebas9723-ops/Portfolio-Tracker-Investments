import plotly.graph_objects as go
import streamlit as st

from app_core import render_page_title, info_section, info_metric


def render_analytics_page(ctx):
    render_page_title("Analytics")

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Alpha", f"{ctx['alpha']:.2%}", "Annualized alpha versus benchmark.")
    info_metric(c2, "Beta", f"{ctx['beta']:.2f}", "Sensitivity to benchmark returns.")
    info_metric(c3, "Tracking Error", f"{ctx['tracking_error']:.2%}", "Annualized tracking error versus benchmark.")
    info_metric(c4, "Information Ratio", f"{ctx['information_ratio']:.2f}", "Annualized information ratio versus benchmark.")

    if ctx["fig_perf"] is not None:
        info_section("Performance", "Portfolio performance compared with the benchmark.")
        st.plotly_chart(ctx["fig_perf"], use_container_width=True)

    if not ctx["rolling_df"].empty:
        info_section("Rolling Metrics", "Rolling portfolio risk and performance metrics.")

        fig = go.Figure()
        if "Rolling Volatility" in ctx["rolling_df"].columns:
            fig.add_scatter(x=ctx["rolling_df"].index, y=ctx["rolling_df"]["Rolling Volatility"], name="Rolling Volatility")
        if "Rolling Sharpe" in ctx["rolling_df"].columns:
            fig.add_scatter(x=ctx["rolling_df"].index, y=ctx["rolling_df"]["Rolling Sharpe"], name="Rolling Sharpe")
        if "Rolling Beta" in ctx["rolling_df"].columns:
            fig.add_scatter(x=ctx["rolling_df"].index, y=ctx["rolling_df"]["Rolling Beta"], name="Rolling Beta")
        fig.update_layout(
            paper_bgcolor="#0b0f14",
            plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"),
            height=420,
            margin=dict(t=20, b=20, l=20, r=20),
        )
        st.plotly_chart(fig, use_container_width=True)

        dd_fig = go.Figure()
        if "Rolling Drawdown" in ctx["rolling_df"].columns:
            dd_fig.add_scatter(x=ctx["rolling_df"].index, y=ctx["rolling_df"]["Rolling Drawdown"], name="Rolling Drawdown")
        dd_fig.update_layout(
            paper_bgcolor="#0b0f14",
            plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"),
            height=320,
            margin=dict(t=20, b=20, l=20, r=20),
        )
        st.plotly_chart(dd_fig, use_container_width=True)