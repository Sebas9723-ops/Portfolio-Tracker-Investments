import streamlit as st

from app_core import (
    render_page_title,
    render_status_bar,
    info_section,
    info_metric,
    build_rebalancing_table,
)


def render_rebalancing_page(ctx):
    render_page_title("Rebalancing")

    render_status_bar(
        mode=ctx["mode"],
        base_currency=ctx["base_currency"],
        profile=ctx["profile"],
        tc_model=ctx["tc_model"],
        sheets_ok=(ctx["positions_sheet_available"] if ctx["mode"] == "Private" else True),
    )

    info_section(
        "Rebalancing Engine",
        "Trade list showing the required buy and sell adjustments to move from the current allocation to a selected target allocation, including estimated transaction costs."
    )

    target_options = ["Base Target"]
    if ctx["max_sharpe_row"] is not None:
        target_options.append("Max Sharpe")
    if ctx["min_vol_row"] is not None:
        target_options.append("Minimum Volatility")

    rebal_target = st.selectbox(
        "Rebalancing Target",
        target_options,
        help="Choose the target allocation used to generate the trade list."
    )

    if rebal_target == "Base Target":
        target_weight_map = ctx["df"].set_index("Ticker")["Target Weight"].to_dict()
    elif rebal_target == "Max Sharpe" and ctx["max_sharpe_row"] is not None:
        target_weight_map = dict(zip(ctx["usable"], ctx["max_sharpe_row"]["Weights"]))
    else:
        target_weight_map = dict(zip(ctx["usable"], ctx["min_vol_row"]["Weights"]))

    rebal_df = build_rebalancing_table(
        df_current=ctx["df"],
        target_weight_map=target_weight_map,
        base_currency=ctx["base_currency"],
        tc_model=ctx["tc_model"],
        tc_params=ctx["tc_params"],
    )

    buy_value = rebal_df.loc[rebal_df["Action"] == "Buy", "Value Delta"].sum()
    sell_value = -rebal_df.loc[rebal_df["Action"] == "Sell", "Value Delta"].sum()
    total_estimated_cost = rebal_df["Estimated Cost"].sum()
    net_cash_after_costs = rebal_df["Net Cash Flow"].sum()

    r1, r2, r3, r4 = st.columns(4)
    info_metric(r1, "Total Buy Value", f"{ctx['base_currency']} {buy_value:,.2f}", "Total gross capital required for buy trades.")
    info_metric(r2, "Total Sell Value", f"{ctx['base_currency']} {sell_value:,.2f}", "Total gross capital released by sell trades.")
    info_metric(r3, "Estimated Transaction Costs", f"{ctx['base_currency']} {total_estimated_cost:,.2f}", "Estimated total trading costs under the selected transaction cost model.")
    info_metric(r4, "Net Cash Impact After Costs", f"{ctx['base_currency']} {net_cash_after_costs:,.2f}", "Positive means net cash released. Negative means additional cash required.")

    st.dataframe(rebal_df, use_container_width=True)