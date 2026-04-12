import streamlit as st

from app_core import apply_bloomberg_style
from app_context_runtime import build_app_context_runtime
from pages_app.dashboard import render_dashboard
from pages_app.portfolio_page import render_portfolio_page
from pages_app.optimization import render_optimization_page
from pages_app.rebalancing import render_rebalancing_page
from pages_app.risk_scenarios import render_risk_scenarios_page
from pages_app.performance_page import render_performance_page
from pages_app.investment_horizon import render_investment_horizon_page
from pages_app.projections import render_projections_page
from pages_app.economic_calendar import render_economic_calendar_page
from pages_app.technicals import render_technicals_page
from pages_app.fundamentals import render_fundamentals_page
from pages_app.whatif import render_whatif_page
from pages_app.trade_log import render_trade_log_page
from pages_app.alerts import render_alerts_page
from pages_app.xtb_import import render_xtb_import_page
from pages_app.transactions import render_transactions_page
from pages_app.private_manager import render_private_manager_page

from PIL import Image as _Image
st.set_page_config(
    page_title="Portfolio Management SA | Private",
    page_icon=_Image.open("static/apple-touch-icon.png"),
    layout="wide",
)

apply_bloomberg_style()


# ── Login ──────────────────────────────────────────────────────────────────────

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


# ── Navigation structure ───────────────────────────────────────────────────────

SECTION_PAGES = {
    "OPERATE":  ["Dashboard", "Portfolio", "Optimization", "Rebalance Center", "Manage Positions"],
    "ANALYZE":  ["Risk & Scenarios", "Performance", "Investment Horizon", "Projections"],
    "RESEARCH": ["Macro Dashboard", "Technicals", "Fundamentals", "What-If Simulator"],
    "SETTINGS": ["Trade Log", "Custom Alerts", "XTB Import", "Transactions"],
}

ALL_PAGES = [p for pages in SECTION_PAGES.values() for p in pages]

# Restore previously selected page; default to Dashboard
_saved_page = st.session_state.get("private_page_navigation", "Dashboard")
if _saved_page not in ALL_PAGES:
    _saved_page = "Dashboard"

# Find which section the saved page belongs to
_saved_section = next(
    (sec for sec, pages in SECTION_PAGES.items() if _saved_page in pages),
    "OPERATE",
)

# ── Sidebar ────────────────────────────────────────────────────────────────────

st.sidebar.markdown("## Portfolio Management SA")
st.sidebar.caption("Private management version")

if st.sidebar.button("CERRAR SESIÓN", key="logout_btn"):
    st.session_state.clear()
    st.rerun()

st.sidebar.markdown("---")

section = st.sidebar.selectbox(
    "Section",
    list(SECTION_PAGES.keys()),
    index=list(SECTION_PAGES.keys()).index(_saved_section),
    key="private_section_navigation",
    label_visibility="collapsed",
    format_func=lambda s: f"── {s}",
)

page_name = st.sidebar.radio(
    "Page",
    SECTION_PAGES[section],
    index=SECTION_PAGES[section].index(_saved_page) if _saved_page in SECTION_PAGES[section] else 0,
    key=f"private_page_radio_{section}",
    label_visibility="collapsed",
)

st.session_state["private_page_navigation"] = page_name

st.sidebar.markdown("---")

# ── Build context ──────────────────────────────────────────────────────────────

ctx = build_app_context_runtime("private")

# ── Sidebar mini KPI (always visible) ─────────────────────────────────────────
import datetime as _dt
_total_val = float(ctx.get("total_portfolio_value", 0.0))
_invested = float(ctx.get("invested_capital", 0.0))
_unrealized = float(ctx.get("unrealized_pnl", 0.0))
_simple_ret = (_unrealized / _invested) if _invested > 0 else 0.0
_ccy = ctx.get("base_currency", "USD")
_ret_color = "#00ff88" if _simple_ret >= 0 else "#ff4444"
_ret_arrow = "▲" if _simple_ret >= 0 else "▼"
_mkt_open = False
try:
    import pytz as _pytz
    _now_et = _dt.datetime.now(_pytz.timezone("America/New_York"))
    _mkt_open = (
        _now_et.weekday() < 5
        and _dt.time(9, 30) <= _now_et.time() <= _dt.time(16, 0)
    )
except Exception:
    pass
_dot_cls = "open" if _mkt_open else "closed"
_mkt_label = "Market Open" if _mkt_open else "Market Closed"

st.sidebar.markdown(
    f"""
    <div style='background:#111;border:1px solid #1e2535;border-radius:6px;
        padding:10px 12px;margin-bottom:8px;'>
      <div style='font-size:0.62rem;color:#555;text-transform:uppercase;letter-spacing:0.8px;
          margin-bottom:4px;'>
        <span class='live-dot {_dot_cls}'></span>{_mkt_label}
      </div>
      <div style='font-size:1.1rem;font-weight:800;color:#f2f2f2;font-family:IBM Plex Mono,monospace'>
        {_ccy} {_total_val:,.0f}
      </div>
      <div style='font-size:0.78rem;font-weight:700;color:{_ret_color};margin-top:2px'>
        {_ret_arrow} {abs(_simple_ret):.2%} simple return
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Route ──────────────────────────────────────────────────────────────────────

if page_name == "Dashboard":
    render_dashboard(ctx)
elif page_name == "Portfolio":
    render_portfolio_page(ctx)
elif page_name == "Optimization":
    render_optimization_page(ctx)
elif page_name == "Rebalance Center":
    render_rebalancing_page(ctx)
elif page_name == "Manage Positions":
    render_private_manager_page(ctx)
elif page_name == "Risk & Scenarios":
    render_risk_scenarios_page(ctx)
elif page_name == "Performance":
    render_performance_page(ctx)
elif page_name == "Investment Horizon":
    render_investment_horizon_page(ctx)
elif page_name == "Projections":
    render_projections_page(ctx)
elif page_name == "Macro Dashboard":
    render_economic_calendar_page(ctx)
elif page_name == "Technicals":
    render_technicals_page(ctx)
elif page_name == "Fundamentals":
    render_fundamentals_page(ctx)
elif page_name == "What-If Simulator":
    render_whatif_page(ctx)
elif page_name == "Trade Log":
    render_trade_log_page(ctx)
elif page_name == "Custom Alerts":
    render_alerts_page(ctx)
elif page_name == "XTB Import":
    render_xtb_import_page(ctx)
elif page_name == "Transactions":
    render_transactions_page(ctx)
