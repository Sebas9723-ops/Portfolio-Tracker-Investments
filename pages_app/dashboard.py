import streamlit as st

from app_core import render_page_title, render_status_bar, render_market_clocks, info_section, info_metric


def render_dashboard(ctx):
    render_page_title("Dashboard")

    render_status_bar(
        mode=ctx["mode"],
        base_currency=ctx["base_currency"],
        profile=ctx["profile"],
        tc_model=ctx["tc_model"],
        sheets_ok=(ctx["positions_sheet_available"] if ctx["mode"] == "Private" else True),
    )

    render_market_clocks()

    d1, d2, d3, d4 = st.columns(4)
    info_metric(d1, f"Total Value ({ctx['base_currency']})", f"{ctx['base_currency']} {ctx['total_value']:,.2f}", "Current market value of the portfolio converted into the selected base currency.")
    info_metric(d2, "Return", f"{ctx['total_return']:.2%}", "Cumulative portfolio return over the historical sample.")
    info_metric(d3, "Volatility", f"{ctx['volatility']:.2%}", "Annualized standard deviation of portfolio returns.")
    info_metric(d4, "Sharpe Ratio", f"{ctx['sharpe']:.2f}", "Risk-adjusted return using the selected risk-free rate.")

    c_left, c_right = st.columns([1.2, 1])

    with c_left:
        info_section("Top Holdings", "Largest portfolio positions by current market value.")
        top_holdings = ctx["display_df"].sort_values("Value", ascending=False).head(5)[
            ["Ticker", "Name", "Value", "Weight %", "Deviation %"]
        ]
        st.dataframe(top_holdings, use_container_width=True)

    with c_right:
        info_section("Portfolio Allocation", "Portfolio composition by market value.")
        st.plotly_chart(ctx["fig_pie"], use_container_width=True)

    if ctx["fig_perf"] is not None:
        info_section("Performance vs Benchmark", "Cumulative growth of the portfolio versus VOO.")
        st.plotly_chart(ctx["fig_perf"], use_container_width=True)