import streamlit as st

from app_core import apply_bloomberg_style
from app_context_runtime import build_app_context_runtime
from pages_app.analytics import render_analytics_page
from pages_app.dashboard import render_dashboard
from pages_app.optimization import render_optimization_page
from pages_app.portfolio_page import render_portfolio_page
from pages_app.private_manager import render_private_manager_page
from pages_app.projections import render_projections_page
from pages_app.rebalancing import render_rebalancing_page
from pages_app.risk import render_risk_page
from pages_app.scenarios import render_scenarios_page
from pages_app.transactions import render_transactions_page


from PIL import Image as _Image
st.set_page_config(
    page_title="Portfolio Management SA | Private",
    page_icon=_Image.open("static/apple-touch-icon.png"),
    layout="wide",
)

apply_bloomberg_style()

st.sidebar.markdown("## Portfolio Management SA")
st.sidebar.caption("Private management version")

_NAV_PAGES = [
    "Dashboard",
    "Portfolio",
    "Analytics",
    "Risk",
    "Scenarios",
    "Projections",
    "Optimization",
    "Rebalance Center",
    "Transactions",
    "Private Manager",
]

if st.session_state.get("private_page_navigation") not in _NAV_PAGES:
    st.session_state["private_page_navigation"] = "Dashboard"

st.sidebar.markdown("### Navigation")
page_name = st.sidebar.selectbox(
    "Page",
    _NAV_PAGES,
    key="private_page_navigation",
    label_visibility="collapsed",
)

st.sidebar.markdown("---")

ctx = build_app_context_runtime("private")

if page_name == "Dashboard":
    render_dashboard(ctx)
elif page_name == "Portfolio":
    render_portfolio_page(ctx)
elif page_name == "Analytics":
    render_analytics_page(ctx)
elif page_name == "Risk":
    render_risk_page(ctx)
elif page_name == "Scenarios":
    render_scenarios_page(ctx)
elif page_name == "Projections":
    render_projections_page(ctx)
elif page_name == "Optimization":
    render_optimization_page(ctx)
elif page_name == "Rebalance Center":
    render_rebalancing_page(ctx)
elif page_name == "Transactions":
    render_transactions_page(ctx)
elif page_name == "Private Manager":
    render_private_manager_page(ctx)