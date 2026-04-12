"""Performance — merged page (Analytics + Performance Calendar tabs)."""
import streamlit as st
from app_core import render_page_title
from pages_app.analytics import render_analytics_page
from pages_app.performance_calendar import render_performance_calendar_page


def render_performance_page(ctx):
    render_page_title("Performance")
    tab_analytics, tab_calendar = st.tabs(["Analytics", "Calendar"])
    with tab_analytics:
        render_analytics_page(ctx)
    with tab_calendar:
        render_performance_calendar_page(ctx)
