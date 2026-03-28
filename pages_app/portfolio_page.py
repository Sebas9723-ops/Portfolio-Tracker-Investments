import streamlit as st

from app_core import render_page_title, render_status_bar, info_section, info_metric


def render_portfolio_page(ctx):
    render_page_title("Portfolio")

    render_status_bar(
        mode=ctx["mode"],
        base_currency=ctx["base_currency"],
        profile=ctx["profile"],
        tc_model=ctx["tc_model"],
        sheets_ok=(ctx["positions_sheet_available"] if ctx["mode"] == "Private" else True),
    )

    info_section("Portfolio", f"Snapshot of current positions in {ctx['base_currency']}, including FX conversion, current weights, target weights, and deviations.")
    st.dataframe(ctx["display_df"], use_container_width=True)
    info_metric(st, f"Total Value ({ctx['base_currency']})", f"{ctx['base_currency']} {ctx['total_value']:,.2f}", f"Current market value of the portfolio converted into {ctx['base_currency']}.")

    info_section("Portfolio Allocation", f"Portfolio composition by market value in {ctx['base_currency']}.")
    st.plotly_chart(ctx["fig_pie"], use_container_width=True)

    info_section("Target vs Actual Allocation", "Compares current weights with the original base weights for the active mode.")
    st.plotly_chart(ctx["fig_bar"], use_container_width=True)