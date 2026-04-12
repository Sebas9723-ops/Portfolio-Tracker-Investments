"""Risk & Scenarios — merged page (Risk + Scenarios tabs)."""
import streamlit as st
from app_core import render_page_title
from pages_app.risk import render_risk_page
from pages_app.scenarios import render_scenarios_page


def render_risk_scenarios_page(ctx):
    render_page_title("Risk & Scenarios")
    tab_risk, tab_scenarios = st.tabs(["Risk", "Scenarios"])
    with tab_risk:
        render_risk_page(ctx)
    with tab_scenarios:
        render_scenarios_page(ctx)
