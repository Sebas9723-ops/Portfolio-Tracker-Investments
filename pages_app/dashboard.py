import streamlit as st

from app_core import (
    render_page_title,
    render_status_bar,
    render_market_clocks,
    render_private_dashboard_logo,
    info_section,
    info_metric,
)


def render_dashboard(ctx):
    render_page_title("Dashboard")

    render_private_dashboard_logo(
        mode=ctx["mode"],
        authenticated=ctx["authenticated"],
    )

    render_status_bar(
        mode=ctx["mode"],
        base_currency=ctx["base_currency"],
        profile=ctx["profile"],
        tc_model=ctx["tc_model"],
        sheets_ok=(ctx["positions_sheet_available"] if ctx["mode"] == "Private" else True),
    )

    render_market_clocks()

    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    info_metric(r1c1, f"Total Portfolio ({ctx['base_currency']})", f"{ctx['base_currency']} {ctx['total_portfolio_value']:,.2f}", "Invested assets plus cash.")
    info_metric(r1c2, "Invested Assets", f"{ctx['base_currency']} {ctx['holdings_value']:,.2f}", "Market value of invested positions.")
    info_metric(r1c3, "Cash", f"{ctx['base_currency']} {ctx['cash_total_value']:,.2f}", "Cash balances converted to the selected base currency.")
    info_metric(r1c4, "Unrealized PnL", f"{ctx['base_currency']} {ctx['unrealized_pnl']:,.2f}", "Profit or loss on open positions.")

    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    info_metric(r2c1, "Return", f"{ctx['total_return']:.2%}", "Cumulative portfolio return over the historical sample.")
    info_metric(r2c2, "Volatility", f"{ctx['volatility']:.2%}", "Annualized volatility of the portfolio.")
    info_metric(r2c3, "Sharpe Ratio", f"{ctx['sharpe']:.2f}", "Risk-adjusted return relative to the selected risk-free rate.")
    info_metric(r2c4, "Realized PnL", f"{ctx['base_currency']} {ctx['realized_pnl']:,.2f}", "Profit or loss realized through sales.")

    r3c1, r3c2, r3c3, r3c4 = st.columns(4)
    info_metric(r3c1, "Estimated Annual Dividends", f"{ctx['base_currency']} {ctx['estimated_annual_dividends']:,.2f}", "Estimated annual dividend income based on current holdings.")
    info_metric(r3c2, "Dividends YTD", f"{ctx['base_currency']} {ctx['dividends_ytd']:,.2f}", "Collected dividends year-to-date.")
    info_metric(r3c3, "Dividends Total", f"{ctx['base_currency']} {ctx['dividends_total']:,.2f}", "All collected dividends registered in the sheet.")
    yield_pct = (ctx["estimated_annual_dividends"] / ctx["holdings_value"] * 100) if ctx["holdings_value"] > 0 else 0.0
    info_metric(r3c4, "Portfolio Dividend Yield", f"{yield_pct:.2f}%", "Estimated annual dividend yield over invested assets.")

    c_left, c_right = st.columns([1.15, 1])

    with c_left:
        info_section("Top Holdings", "Largest portfolio positions by current market value.")
        top_holdings = ctx["display_df"].sort_values("Value", ascending=False).head(5)[
            ["Ticker", "Name", "Shares", "Value", "Weight %", "Unrealized PnL"]
        ]
        st.dataframe(top_holdings, use_container_width=True, height=245)

    with c_right:
        info_section("Portfolio Allocation", "Portfolio composition by market value, including cash when available.")
        st.plotly_chart(ctx["fig_pie"], use_container_width=True)

    if ctx["mode"] == "Private":
        info_section("Cash Balances", "Cash balances stored in Google Sheets and converted to the selected base currency.")
        st.dataframe(ctx["cash_display_df"], use_container_width=True, height=220)

    if ctx["fig_perf"] is not None:
        info_section("Performance vs Benchmark", "Cumulative growth of the portfolio versus VOO.")
        st.plotly_chart(ctx["fig_perf"], use_container_width=True)