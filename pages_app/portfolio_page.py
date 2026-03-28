import streamlit as st

from app_core import render_page_title, info_section, info_metric


def render_portfolio_page(ctx):
    render_page_title("Portfolio")

    m1, m2, m3, m4 = st.columns(4)
    info_metric(
        m1,
        "Total Portfolio",
        f"{ctx['base_currency']} {ctx['total_portfolio_value']:,.2f}",
        "Total value of invested assets plus cash."
    )
    info_metric(
        m2,
        "Invested Capital",
        f"{ctx['base_currency']} {ctx['invested_capital']:,.2f}",
        "Estimated capital currently invested in open positions."
    )
    info_metric(
        m3,
        "Unrealized P&L",
        f"{ctx['base_currency']} {ctx['unrealized_pnl']:,.2f}",
        "Profit or loss on open positions."
    )
    info_metric(
        m4,
        "Realized P&L",
        f"{ctx['base_currency']} {ctx['realized_pnl']:,.2f}",
        "Profit or loss already realized through sell transactions."
    )

    info_section("Portfolio Snapshot", "Current holdings with average cost, invested capital, and P&L.")
    st.dataframe(
        ctx["display_df"][
            [
                "Ticker",
                "Name",
                "Source",
                "Market",
                "Native Currency",
                "Shares",
                "Avg Cost",
                "Price",
                "Invested Capital",
                "Value",
                "Unrealized PnL",
                "Unrealized PnL %",
                "Realized PnL",
                "Weight %",
                "Target %",
                "Deviation %",
            ]
        ],
        use_container_width=True,
        height=420,
    )

    c1, c2 = st.columns([1, 1])

    with c1:
        info_section("Allocation", "Portfolio composition by current market value.")
        st.plotly_chart(ctx["fig_pie"], use_container_width=True)

    with c2:
        info_section("Weights vs Target", "Current weights compared with target weights from the starting portfolio snapshot.")
        st.plotly_chart(ctx["fig_bar"], use_container_width=True)

    if ctx["mode"] == "Private":
        info_section("Cash Balances", "Cash balances by currency and their value in the selected base currency.")
        st.dataframe(ctx["cash_display_df"], use_container_width=True, height=220)