import streamlit as st

from app_core import apply_bloomberg_style, build_app_context
from pages_app.dashboard import render_dashboard
from pages_app.portfolio_page import render_portfolio_page
from pages_app.analytics import render_analytics_page
from pages_app.optimization import render_optimization_page
from pages_app.rebalancing import render_rebalancing_page
from pages_app.risk import render_risk_page
from pages_app.investment_horizon import render_investment_horizon_page
from pages_app.private_manager import render_private_manager_page


st.set_page_config(page_title="Portfolio Dashboard", layout="wide")
apply_bloomberg_style()

ctx = build_app_context()

pages = [
    st.Page(lambda: render_dashboard(ctx), title="Dashboard", icon=":material/dashboard:"),
    st.Page(lambda: render_portfolio_page(ctx), title="Portfolio", icon=":material/account_balance_wallet:"),
    st.Page(lambda: render_analytics_page(ctx), title="Analytics", icon=":material/analytics:"),
    st.Page(lambda: render_optimization_page(ctx), title="Optimization", icon=":material/show_chart:"),
    st.Page(lambda: render_rebalancing_page(ctx), title="Rebalancing", icon=":material/swap_horiz:"),
    st.Page(lambda: render_risk_page(ctx), title="Risk", icon=":material/warning:"),
    st.Page(lambda: render_investment_horizon_page(ctx), title="Investment Horizon", icon=":material/timeline:"),
]

if ctx["mode"] == "Private" and ctx["authenticated"]:
    pages.append(
        st.Page(lambda: render_private_manager_page(ctx), title="Private Manager", icon=":material/lock:")
    )

pg = st.navigation(pages, position="sidebar", expanded=True)
pg.run()