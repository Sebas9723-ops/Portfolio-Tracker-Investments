import plotly.graph_objects as go
import streamlit as st

from app_core import render_page_title, info_section, info_metric


def render_risk_page(ctx):
    render_page_title("Risk")

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Volatility", f"{ctx['volatility']:.2%}", "Annualized volatility.")
    info_metric(c2, "Max Drawdown", f"{ctx['max_drawdown']:.2%}", "Maximum drawdown over the sample.")
    info_metric(c3, "Stress PnL", f"{ctx['base_currency']} {ctx['stress_pnl']:,.2f}", "PnL under the configured stress scenario.")
    info_metric(c4, "Stress Return", f"{ctx['stress_return']:.2%}", "Return under the configured stress scenario.")

    info_section("Stress Test", "Current value versus stressed value under the selected shocks.")
    st.plotly_chart(ctx["fig_stress"], use_container_width=True)

    info_section("Stress Table", "Per-position stress-test detail.")
    st.dataframe(ctx["stress_df"], use_container_width=True, height=360)

    if not ctx["rolling_df"].empty and "Rolling Drawdown" in ctx["rolling_df"].columns:
        info_section("Rolling Drawdown", "Rolling drawdown history of the portfolio.")
        dd_fig = go.Figure()
        dd_fig.add_scatter(x=ctx["rolling_df"].index, y=ctx["rolling_df"]["Rolling Drawdown"], name="Rolling Drawdown")
        dd_fig.update_layout(
            paper_bgcolor="#0b0f14",
            plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"),
            height=320,
            margin=dict(t=20, b=20, l=20, r=20),
        )
        st.plotly_chart(dd_fig, use_container_width=True)