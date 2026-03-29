import streamlit as st

from app_core import (
    build_recommended_shares_table,
    info_metric,
    info_section,
    render_page_title,
    weights_table,
)


def _annualized_voo_return(ctx):
    benchmark_returns = ctx.get("benchmark_returns")
    if benchmark_returns is None or benchmark_returns.empty:
        return None
    return float(benchmark_returns.mean() * 252)


def render_optimization_page(ctx):
    render_page_title("Optimization")

    if ctx.get("fig_frontier") is None or ctx.get("max_sharpe_row") is None or ctx.get("min_vol_row") is None:
        st.info("Not enough data to build the efficient frontier.")
        return

    voo_return = _annualized_voo_return(ctx)

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Current Return", f"{ctx['current_return']:.2%}", "Expected annualized return of the current portfolio.")
    info_metric(c2, "VOO Return", "-" if voo_return is None else f"{voo_return:.2%}", "Annualized VOO return over the same historical window.")
    info_metric(c3, "Current Volatility", f"{ctx['current_vol']:.2%}", "Expected annualized volatility of the current portfolio.")
    info_metric(c4, "Current Sharpe", f"{ctx['current_sharpe']:.2f}", "Sharpe ratio of the current portfolio.")

    info_section(
        "Efficient Frontier",
        "Simulated efficient frontier, current portfolio, max Sharpe portfolio, and minimum volatility portfolio.",
    )
    st.plotly_chart(ctx["fig_frontier"], use_container_width=True, key="optimization_frontier_chart_v2")

    usable = list(ctx["usable"])
    ms_weights = ctx["max_sharpe_row"]["Weights"]
    mv_weights = ctx["min_vol_row"]["Weights"]

    ms_table = weights_table(ms_weights, usable)
    mv_table = weights_table(mv_weights, usable)

    ms_rec = build_recommended_shares_table(ms_weights, usable, ctx["df"])
    mv_rec = build_recommended_shares_table(mv_weights, usable, ctx["df"])

    left, right = st.columns(2)

    with left:
        info_section("Max Sharpe Weights", "Recommended weights from the maximum Sharpe portfolio.")
        st.dataframe(ms_table, use_container_width=True, height=260)

        info_section("Max Sharpe Shares", "Recommended shares to move the current portfolio toward the maximum Sharpe allocation.")
        st.dataframe(ms_rec, use_container_width=True, height=300)

    with right:
        info_section("Min Volatility Weights", "Recommended weights from the minimum volatility portfolio.")
        st.dataframe(mv_table, use_container_width=True, height=260)

        info_section("Min Volatility Shares", "Recommended shares to move the current portfolio toward the minimum volatility allocation.")
        st.dataframe(mv_rec, use_container_width=True, height=300)