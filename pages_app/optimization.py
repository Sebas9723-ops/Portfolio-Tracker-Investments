import streamlit as st

from app_core import (
    render_page_title,
    render_status_bar,
    info_section,
    info_metric,
    build_recommended_shares_table,
    weights_table,
)


def render_optimization_page(ctx):
    render_page_title("Optimization")

    render_status_bar(
        mode=ctx["mode"],
        base_currency=ctx["base_currency"],
        profile=ctx["profile"],
        tc_model=ctx["tc_model"],
        sheets_ok=(ctx["positions_sheet_available"] if ctx["mode"] == "Private" else True),
    )

    info_section("Efficient Frontier", "Simulated portfolios showing the trade-off between expected return and volatility under the selected constraints.")

    if ctx["frontier"].empty or ctx["fig_frontier"] is None:
        st.info("No feasible frontier was found. Try relaxing the constraints or checking historical data availability.")
        return

    st.plotly_chart(ctx["fig_frontier"], use_container_width=True)

    f1, f2, f3 = st.columns(3)
    info_metric(f1, "Current Expected Return / Volatility", f"{ctx['current_return']:.2%} / {ctx['current_vol']:.2%}", "Expected annual return and annualized volatility of the current portfolio.")
    info_metric(f2, "Max Sharpe Return / Volatility", f"{ctx['max_sharpe_row']['Return']:.2%} / {ctx['max_sharpe_row']['Volatility']:.2%}", "Expected annual return and volatility of the highest-Sharpe simulated portfolio.")
    info_metric(f3, "Min Vol Return / Volatility", f"{ctx['min_vol_row']['Return']:.2%} / {ctx['min_vol_row']['Volatility']:.2%}", "Expected annual return and volatility of the minimum-volatility portfolio.")

    f4, f5, f6 = st.columns(3)
    info_metric(f4, "Current Sharpe Ratio", f"{ctx['current_sharpe']:.2f}", "Risk-adjusted return of the current portfolio using the selected risk-free rate.")
    info_metric(f5, "Max Sharpe Ratio", f"{ctx['max_sharpe_row']['Sharpe']:.2f}", "Highest Sharpe ratio among the feasible simulated portfolios.")
    info_metric(f6, "Min Vol Sharpe Ratio", f"{ctx['min_vol_row']['Sharpe']:.2f}", "Sharpe ratio of the minimum-volatility feasible portfolio.")

    action_col1, action_col2, _ = st.columns([1, 1, 2])

    with action_col1:
        if st.button("Estimate Max Sharpe Shares", help="Estimate how many shares each ETF should have to match the maximum-Sharpe portfolio, without modifying your current holdings."):
            st.session_state[f"show_max_sharpe_targets_{ctx['prefix']}"] = True

    with action_col2:
        if st.button("Estimate Min Vol Shares", help="Estimate how many shares each ETF should have to match the minimum-volatility portfolio, without modifying your current holdings."):
            st.session_state[f"show_min_vol_targets_{ctx['prefix']}"] = True

    if st.session_state.get(f"show_max_sharpe_targets_{ctx['prefix']}", False):
        info_section("Recommended Shares for Max Sharpe", "Estimated share quantities required to reach the maximum-Sharpe allocation, based on current total portfolio value and current prices.")
        rec_df_max = build_recommended_shares_table(ctx["max_sharpe_row"]["Weights"], ctx["usable"], ctx["df"])
        st.dataframe(rec_df_max, use_container_width=True)

    if st.session_state.get(f"show_min_vol_targets_{ctx['prefix']}", False):
        info_section("Recommended Shares for Minimum Volatility", "Estimated share quantities required to reach the minimum-volatility allocation, based on current total portfolio value and current prices.")
        rec_df_min = build_recommended_shares_table(ctx["min_vol_row"]["Weights"], ctx["usable"], ctx["df"])
        st.dataframe(rec_df_min, use_container_width=True)

    info_section("Optimization Weights", "Weight breakdown for the optimal simulated portfolios.")
    opt1, opt2 = st.columns(2)

    with opt1:
        st.write("Max Sharpe Portfolio")
        st.dataframe(weights_table(ctx["max_sharpe_row"]["Weights"], ctx["usable"]), use_container_width=True)

    with opt2:
        st.write("Minimum Volatility Portfolio")
        st.dataframe(weights_table(ctx["min_vol_row"]["Weights"], ctx["usable"]), use_container_width=True)