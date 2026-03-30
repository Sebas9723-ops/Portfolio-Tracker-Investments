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
from pages_app.transactions import render_transactions_page
from pages_app.income import render_income_page


from PIL import Image as _Image
st.set_page_config(
    page_title="Portfolio Management SA",
    page_icon=_Image.open("static/apple-touch-icon.png"),
    layout="wide",
)
apply_bloomberg_style()

ctx = build_app_context()

pages = [
    st.Page(
        lambda: render_dashboard(ctx),
        title="Dashboard",
        url_path="dashboard",
        default=True,
    ),
    st.Page(
        lambda: render_portfolio_page(ctx),
        title="Portfolio",
        url_path="portfolio",
    ),
    st.Page(
        lambda: render_analytics_page(ctx),
        title="Analytics",
        url_path="analytics",
    ),
    st.Page(
        lambda: render_optimization_page(ctx),
        title="Optimization",
        url_path="optimization",
    ),
    st.Page(
        lambda: render_rebalancing_page(ctx),
        title="Rebalancing",
        url_path="rebalancing",
    ),
    st.Page(
        lambda: render_risk_page(ctx),
        title="Risk",
        url_path="risk",
    ),
    st.Page(
        lambda: render_investment_horizon_page(ctx),
        title="Investment Horizon",
        url_path="investment-horizon",
    ),
    st.Page(
        lambda: render_income_page(ctx),
        title="Income",
        url_path="income",
    ),
]

if ctx["mode"] == "Private" and ctx["authenticated"]:
    pages.append(
        st.Page(
            lambda: render_transactions_page(ctx),
            title="Transactions",
            url_path="transactions",
        )
    )

    pages.append(
        st.Page(
            lambda: render_private_manager_page(ctx),
            title="Private Manager",
            url_path="private-manager",
        )
    )

pg = st.navigation(pages, position="sidebar", expanded=True)
pg.run()