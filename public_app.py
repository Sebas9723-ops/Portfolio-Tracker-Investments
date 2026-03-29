import streamlit as st

from app_core import apply_bloomberg_style
from app_context_runtime import build_app_context_runtime
from pages_app.analytics import render_analytics_page
from pages_app.dashboard import render_dashboard
from pages_app.optimization import render_optimization_page
from pages_app.portfolio_page import render_portfolio_page
from pages_app.rebalancing import render_rebalancing_page


st.set_page_config(
    page_title="Portfolio Management SA | Public",
    layout="wide",
)

apply_bloomberg_style()

st.sidebar.markdown("## Portfolio Management SA")
st.sidebar.caption("Public showcase version")

st.sidebar.markdown("### Navigation")
page_name = st.sidebar.selectbox(
    "Page",
    [
        "Dashboard",
        "Portfolio",
        "Analytics",
        "Optimization",
        "Rebalance Center",
    ],
    key="public_page_navigation",
    label_visibility="collapsed",
)

st.sidebar.markdown("---")

ctx = build_app_context_runtime("public")

if page_name == "Dashboard":
    render_dashboard(ctx)
elif page_name == "Portfolio":
    render_portfolio_page(ctx)
elif page_name == "Analytics":
    render_analytics_page(ctx)
elif page_name == "Optimization":
    render_optimization_page(ctx)
elif page_name == "Rebalance Center":
    render_rebalancing_page(ctx)