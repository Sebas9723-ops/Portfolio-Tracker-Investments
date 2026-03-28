import streamlit as st

from app_core import render_page_title, render_status_bar, info_section, info_metric


def render_risk_page(ctx):
    render_page_title("Risk")

    render_status_bar(
        mode=ctx["mode"],
        base_currency=ctx["base_currency"],
        profile=ctx["profile"],
        tc_model=ctx["tc_model"],
        sheets_ok=(ctx["positions_sheet_available"] if ctx["mode"] == "Private" else True),
    )

    info_section(
        "Scenario / Stress Testing",
        "Applies category-level shocks to estimate how the portfolio would behave under adverse or favorable market scenarios."
    )

    s1, s2, s3 = st.columns(3)
    info_metric(s1, "Current Portfolio Value", f"{ctx['base_currency']} {ctx['current_total_value']:,.2f}", "Current portfolio value before the stress scenario.")
    info_metric(s2, "Stressed Portfolio Value", f"{ctx['base_currency']} {ctx['stressed_total_value']:,.2f}", "Portfolio value after applying the stress scenario.")
    info_metric(s3, "Scenario P/L", f"{ctx['base_currency']} {ctx['stress_pnl']:,.2f} ({ctx['stress_return']:.2%})", "Profit or loss implied by the selected shocks.")

    st.plotly_chart(ctx["fig_stress"], use_container_width=True)
    st.dataframe(ctx["stress_df"], use_container_width=True)