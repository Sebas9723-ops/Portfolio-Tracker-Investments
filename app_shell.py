import streamlit as st

from app_core import apply_bloomberg_style
from app_context_runtime import build_app_context_runtime
from pages_app.analytics import render_analytics_page
from pages_app.dashboard import render_dashboard
from pages_app.optimization import render_optimization_page
from pages_app.portfolio_page import render_portfolio_page
from pages_app.private_manager import render_private_manager_page
from pages_app.rebalancing import render_rebalancing_page
from pages_app.transactions import render_transactions_page


PUBLIC_PAGES = {
    "Dashboard": render_dashboard,
    "Portfolio": render_portfolio_page,
    "Analytics": render_analytics_page,
    "Optimization": render_optimization_page,
    "Rebalance Center": render_rebalancing_page,
}

PRIVATE_PAGES = {
    "Dashboard": render_dashboard,
    "Portfolio": render_portfolio_page,
    "Analytics": render_analytics_page,
    "Optimization": render_optimization_page,
    "Rebalance Center": render_rebalancing_page,
    "Transactions": render_transactions_page,
    "Private Manager": render_private_manager_page,
}


def run_app(app_scope: str):
    apply_bloomberg_style()

    if app_scope == "public":
        st.sidebar.markdown("## Portfolio Management SA")
        st.sidebar.caption("Public showcase version")
        page_map = PUBLIC_PAGES
    elif app_scope == "private":
        st.sidebar.markdown("## Portfolio Management SA")
        st.sidebar.caption("Private management version")
        page_map = PRIVATE_PAGES
    else:
        raise ValueError("app_scope must be 'public' or 'private'")

    st.sidebar.markdown("### Navigation")
    page_name = st.sidebar.selectbox(
        "Page",
        list(page_map.keys()),
        key=f"{app_scope}_page_navigation",
        label_visibility="collapsed",
    )

    st.sidebar.markdown("---")

    ctx = build_app_context_runtime(app_scope)

    renderer = page_map[page_name]
    renderer(ctx)