import streamlit as st

from app_core import render_page_title, info_section, build_rebalancing_table


def render_rebalancing_page(ctx):
    render_page_title("Rebalancing")

    target_weight_map = ctx["df"].set_index("Ticker")["Target Weight"].to_dict()
    rebalance_df = build_rebalancing_table(
        df_current=ctx["df"],
        target_weight_map=target_weight_map,
        base_currency=ctx["base_currency"],
        tc_model=ctx["tc_model"],
        tc_params=ctx["tc_params"],
    )

    info_section("Rebalancing Plan", "Suggested buys and sells to return the portfolio to target weights.")
    st.dataframe(rebalance_df, use_container_width=True, height=420)

    total_cost = float(rebalance_df["Estimated Cost"].sum()) if not rebalance_df.empty else 0.0
    total_net_cash = float(rebalance_df["Net Cash Flow"].sum()) if not rebalance_df.empty else 0.0

    c1, c2 = st.columns(2)
    c1.metric("Estimated Total Cost", f"{ctx['base_currency']} {total_cost:,.2f}")
    c2.metric("Net Cash Flow", f"{ctx['base_currency']} {total_net_cash:,.2f}")