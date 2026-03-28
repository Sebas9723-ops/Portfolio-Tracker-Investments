import streamlit as st

from app_core import (
    render_page_title,
    info_section,
    info_metric,
    weights_table,
    build_recommended_shares_table,
)


def render_optimization_page(ctx):
    render_page_title("Optimization")

    if ctx["fig_frontier"] is None or ctx["max_sharpe_row"] is None or ctx["min_vol_row"] is None:
        st.info("Not enough data to build the efficient frontier.")
        return

    c1, c2, c3 = st.columns(3)
    info_metric(c1, "Current Return", f"{ctx['current_return']:.2%}", "Expected annual return of the current portfolio.")
    info_metric(c2, "Current Volatility", f"{ctx['current_vol']:.2%}", "Expected annual volatility of the current portfolio.")
    info_metric(c3, "Current Sharpe", f"{ctx['current_sharpe']:.2f}", "Expected Sharpe ratio of the current portfolio.")

    info_section("Efficient Frontier", "Simulated constrained portfolios under the selected risk settings.")
    st.plotly_chart(ctx["fig_frontier"], use_container_width=True)

    ms_weights = ctx["max_sharpe_row"]["Weights"]
    mv_weights = ctx["min_vol_row"]["Weights"]

    ms_table = weights_table(ms_weights, ctx["usable"])
    mv_table = weights_table(mv_weights, ctx["usable"])

    ms_rec = build_recommended_shares_table(ms_weights, ctx["usable"], ctx["df"])
    mv_rec = build_recommended_shares_table(mv_weights, ctx["usable"], ctx["df"])

    c1, c2 = st.columns(2)

    with c1:
        info_section("Max Sharpe Weights", "Target weights for the maximum Sharpe portfolio.")
        st.dataframe(ms_table, use_container_width=True, height=260)

        info_section("Max Sharpe Shares", "Recommended shares if you want to move toward the maximum Sharpe portfolio.")
        st.dataframe(ms_rec, use_container_width=True, height=320)

    with c2:
        info_section("Min Volatility Weights", "Target weights for the minimum volatility portfolio.")
        st.dataframe(mv_table, use_container_width=True, height=260)

        info_section("Min Volatility Shares", "Recommended shares if you want to move toward the minimum volatility portfolio.")
        st.dataframe(mv_rec, use_container_width=True, height=320)