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
from pages_app.xtb_manager import render_xtb_manager_page


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
        st.markdown(
            "<h1 style='color:#f3a712;font-family:monospace;text-align:center;margin-bottom:4px'>"
            "PORTAFOLIO<br>MANAGEMENT SA</h1>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='color:#888;font-family:monospace;text-align:center;margin-top:0;margin-bottom:32px'>"
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
    "Portfolio",
    "Analytics",
    "Risk",
    "Scenarios",
    "Projections",
    "Optimization",
    "Rebalance Center",
    "Transactions",
    "XTB Manager",
    "Private Manager",
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
elif page_name == "XTB Manager":
    render_xtb_manager_page(ctx)
elif page_name == "Private Manager":
    render_private_manager_page(ctx)