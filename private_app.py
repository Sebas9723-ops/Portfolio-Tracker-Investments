import streamlit as st

from app_core import apply_bloomberg_style
from app_context_runtime import build_app_context_runtime
from pages_app.analytics import render_analytics_page
from pages_app.dashboard import render_dashboard
from pages_app.optimization import render_optimization_page
from pages_app.portfolio_page import render_portfolio_page
from pages_app.performance_calendar import render_performance_calendar_page
from pages_app.private_manager import render_private_manager_page
from pages_app.projections import render_projections_page
from pages_app.rebalancing import render_rebalancing_page
from pages_app.risk import render_risk_page
from pages_app.scenarios import render_scenarios_page
from pages_app.trade_journal import render_trade_journal_page
from pages_app.transactions import render_transactions_page
from pages_app.market_overview import render_market_overview_page
from pages_app.order_blotter import render_order_blotter_page
from pages_app.ticker_lookup import render_ticker_lookup_page
from pages_app.watchlist import render_watchlist_page
from pages_app.technicals import render_technicals_page
from pages_app.backtesting import render_backtesting_page
from pages_app.ml_signals import render_ml_signals_page
from pages_app.paper_trading import render_paper_trading_page
from pages_app.whatif import render_whatif_page
from pages_app.alerts import render_alerts_page
from pages_app.income import render_income_page
from pages_app.investment_horizon import render_investment_horizon_page
from pages_app.xtb_import import render_xtb_import_page
from pages_app.yield_curve import render_yield_curve_page
from pages_app.sector_heatmap import render_sector_heatmap_page
from pages_app.news_feed import render_news_feed_page
from pages_app.options_chain import render_options_chain_page
from pages_app.earnings_calendar import render_earnings_calendar_page
from pages_app.fundamentals import render_fundamentals_page
from pages_app.economic_calendar import render_economic_calendar_page


from PIL import Image as _Image
st.set_page_config(
    page_title="Portfolio Management SA | Private",
    page_icon=_Image.open("static/apple-touch-icon.png"),
    layout="wide",
)

apply_bloomberg_style()


# ── Login page ─────────────────────────────────────────────────────────────────

def _check_credentials(username: str, password: str) -> bool:
    expected_password = st.secrets["auth"].get("password", "")
    expected_username = st.secrets["auth"].get("username", "")
    if not expected_password:
        return False
    password_ok = password == expected_password
    username_ok = (not expected_username) or (username.strip() == expected_username)
    return password_ok and username_ok


def _render_login_page():
    st.markdown("""
        <style>
        [data-testid="stSidebar"] {display: none;}
        </style>
    """, unsafe_allow_html=True)

    st.markdown("<br><br>", unsafe_allow_html=True)
    _, col, _ = st.columns([1, 1.4, 1])
    with col:
        try:
            st.image(_Image.open("static/logo_pm_sa.png"), use_container_width=True)
        except Exception:
            st.markdown(
                "<h2 style='color:#f3a712;font-family:monospace;text-align:center'>"
                "PORTFOLIO MANAGEMENT SA</h2>",
                unsafe_allow_html=True,
            )
        st.markdown(
            "<p style='color:#888;font-family:monospace;text-align:center;margin-top:8px;margin-bottom:32px'>"
            "Private Access</p>",
            unsafe_allow_html=True,
        )

        username = st.text_input("Usuario", key="login_username", placeholder="usuario")
        password = st.text_input("Contraseña", type="password", key="login_password",
                                 placeholder="••••••••")

        if st.button("Iniciar sesión", type="primary", use_container_width=True):
            if _check_credentials(username, password):
                st.session_state["private_authenticated"] = True
                st.rerun()
            else:
                st.error("Usuario o contraseña incorrectos.")


if not st.session_state.get("private_authenticated"):
    _render_login_page()
    st.stop()

# ── Authenticated app ──────────────────────────────────────────────────────────

st.sidebar.markdown("## Portfolio Management SA")
st.sidebar.caption("Private management version")

_NAV_PAGES = [
    "Dashboard",
    "Watchlist",
    "Portfolio",
    "Transactions",
    "Analytics",
    "Performance Calendar",
    "Risk",
    "Scenarios",
    "Optimization",
    "Rebalance Center",
    "Projections",
    "Market Overview",
    "Ticker Lookup",
    "Technicals",
    "Trade Journal",
    "Order Blotter",
    "Private Manager",
    "Backtesting",
    "ML Signals",
    "Paper Trading",
    "What-If Simulator",
    "Custom Alerts",
    "Income",
    "Investment Horizon",
    "XTB Import",
    "Yield Curve",
    "Sector Heat Map",
    "News Feed",
    "Options Chain",
    "Earnings Calendar",
    "Fundamentals",
    "Macro Dashboard",
]

if st.session_state.get("private_page_navigation") not in _NAV_PAGES:
    st.session_state["private_page_navigation"] = "Dashboard"

if st.sidebar.button("Cerrar sesión", key="logout_btn"):
    st.session_state.clear()
    st.rerun()

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
elif page_name == "Performance Calendar":
    render_performance_calendar_page(ctx)
elif page_name == "Trade Journal":
    render_trade_journal_page(ctx)
elif page_name == "Market Overview":
    render_market_overview_page(ctx)
elif page_name == "Order Blotter":
    render_order_blotter_page(ctx)
elif page_name == "Ticker Lookup":
    render_ticker_lookup_page(ctx)
elif page_name == "Technicals":
    render_technicals_page(ctx)
elif page_name == "Watchlist":
    render_watchlist_page(ctx)
elif page_name == "Private Manager":
    render_private_manager_page(ctx)
elif page_name == "Backtesting":
    render_backtesting_page(ctx)
elif page_name == "ML Signals":
    render_ml_signals_page(ctx)
elif page_name == "Paper Trading":
    render_paper_trading_page(ctx)
elif page_name == "What-If Simulator":
    render_whatif_page(ctx)
elif page_name == "Custom Alerts":
    render_alerts_page(ctx)
elif page_name == "Income":
    render_income_page(ctx)
elif page_name == "Investment Horizon":
    render_investment_horizon_page(ctx)
elif page_name == "XTB Import":
    render_xtb_import_page(ctx)
elif page_name == "Yield Curve":
    render_yield_curve_page(ctx)
elif page_name == "Sector Heat Map":
    render_sector_heatmap_page(ctx)
elif page_name == "News Feed":
    render_news_feed_page(ctx)
elif page_name == "Options Chain":
    render_options_chain_page(ctx)
elif page_name == "Earnings Calendar":
    render_earnings_calendar_page(ctx)
elif page_name == "Fundamentals":
    render_fundamentals_page(ctx)
elif page_name == "Macro Dashboard":
    render_economic_calendar_page(ctx)