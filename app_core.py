import json
import html
from pathlib import Path

import gspread
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from google.oauth2.service_account import Credentials
from streamlit.components.v1 import html as components_html

from portfolio import public_portfolio
from utils import get_prices, get_historical_data


DEFAULT_RISK_FREE_RATE = 0.02
N_SIMULATIONS = 8000
SUPPORTED_BASE_CCY = ["USD", "EUR", "GBP", "COP", "CHF", "AUD"]
PUBLIC_DEFAULTS_VERSION = "public_defaults_v10_each_20260328"

# Fallbacks for Yahoo issues
PROXY_TICKER_MAP = {
    "IWDA.AS": "EUNL.DE",
}


# =========================
# THEME / UI HELPERS
# =========================
def apply_bloomberg_style():
    st.markdown(
        """
        <style>
        html, body, [class*="css"]  {
            font-family: "IBM Plex Mono", "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", monospace !important;
        }

        .stApp {
            background-color: #0b0f14;
            color: #e6e6e6;
            -webkit-tap-highlight-color: transparent;
        }

        [data-testid="stAppViewContainer"] {
            background-color: #0b0f14;
        }

        .block-container {
            padding-top: calc(1.8rem + env(safe-area-inset-top)) !important;
            padding-right: 1.1rem !important;
            padding-left: 1.1rem !important;
            padding-bottom: 2rem !important;
            max-width: 1500px;
        }

        [data-testid="stSidebar"] {
            background: #0f141b;
            border-right: 1px solid #2a313c;
        }

        [data-testid="stHeader"] {
            background: #0b0f14;
        }

        h1, h2, h3, h4 {
            color: #f3a712 !important;
            letter-spacing: 0.5px;
        }

        .bb-title {
            font-size: 2rem;
            font-weight: 800;
            line-height: 1.15;
            color: #f3a712;
            letter-spacing: 1px;
            padding-top: 0.2rem;
            padding-bottom: 0.8rem;
            margin-top: 0.35rem;
            margin-bottom: 1rem;
            border-bottom: 2px solid #f3a712;
            text-transform: uppercase;
            display: block;
            overflow: visible !important;
        }

        .bb-section {
            background: linear-gradient(180deg, #111821 0%, #0d131a 100%);
            border: 1px solid #2b3340;
            border-left: 4px solid #f3a712;
            border-radius: 6px;
            padding: 0.85rem 1rem 0.9rem 1rem;
            margin: 0.65rem 0 1rem 0;
            box-shadow: 0 0 0 1px rgba(243,167,18,0.05) inset;
        }

        .bb-section-title {
            font-size: 1rem;
            font-weight: 800;
            color: #f3a712;
            text-transform: uppercase;
            margin-bottom: 0.4rem;
            letter-spacing: 0.5px;
        }

        .bb-info {
            color: #7fb3ff;
            cursor: help;
            font-weight: 700;
            margin-left: 0.2rem;
        }

        [data-testid="stMetric"] {
            background: #121922;
            border: 1px solid #2e3744;
            border-top: 2px solid #f3a712;
            border-radius: 6px;
            padding: 0.7rem 0.8rem 0.5rem 0.8rem;
        }

        [data-testid="stMetricLabel"] {
            color: #9fb0c3 !important;
            text-transform: uppercase;
            font-size: 0.75rem !important;
            letter-spacing: 0.6px;
        }

        [data-testid="stMetricValue"] {
            color: #f8f8f8 !important;
            font-size: 1.45rem !important;
            font-weight: 800 !important;
        }

        .stButton > button {
            background: #151d27;
            color: #f3a712;
            border: 1px solid #f3a712;
            border-radius: 4px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.4px;
            min-height: 42px;
        }

        .stButton > button:hover {
            background: #f3a712;
            color: #0b0f14;
            border-color: #f3a712;
        }

        .stSelectbox label, .stNumberInput label, .stTextInput label, .stMarkdown, .stCaption {
            color: #cbd5df !important;
        }

        .stTextInput > div > div > input,
        .stNumberInput input,
        .stSelectbox div[data-baseweb="select"] > div {
            background-color: #0f141b !important;
            color: #f2f2f2 !important;
            border: 1px solid #394250 !important;
            border-radius: 4px !important;
            min-height: 42px !important;
        }

        .stExpander {
            border: 1px solid #2d3642 !important;
            border-radius: 6px !important;
            background: #0f141b !important;
        }

        div[data-testid="stDataFrame"] {
            border: 1px solid #2d3642;
            border-radius: 6px;
            overflow: hidden;
        }

        div[data-testid="stDataFrame"] * {
            color: #e5e7eb !important;
        }

        div[data-testid="stDataFrame"] [role="columnheader"] {
            background-color: #18212c !important;
            color: #f3a712 !important;
            font-weight: 800 !important;
            text-transform: uppercase;
        }

        div[data-testid="stDataFrame"] [role="gridcell"] {
            background-color: #0f141b !important;
        }

        .stAlert {
            border-radius: 6px !important;
            border: 1px solid #2b3340 !important;
        }

        @media (max-width: 900px) {
            .block-container {
                padding-top: calc(3.8rem + env(safe-area-inset-top)) !important;
                padding-right: 0.7rem !important;
                padding-left: 0.7rem !important;
                padding-bottom: 1.5rem !important;
            }

            .bb-title {
                font-size: 1.55rem;
                line-height: 1.15;
                padding-top: 0.15rem;
                padding-bottom: 0.55rem;
                margin-top: 0.6rem;
                margin-bottom: 0.8rem;
            }

            .bb-section {
                padding: 0.65rem 0.75rem 0.7rem 0.75rem;
                margin: 0.45rem 0 0.8rem 0;
            }

            [data-testid="stMetricValue"] {
                font-size: 1.15rem !important;
            }

            [data-testid="stHorizontalBlock"] {
                flex-wrap: wrap !important;
                gap: 0.6rem !important;
            }

            [data-testid="column"] {
                min-width: 100% !important;
                flex: 1 1 100% !important;
                width: 100% !important;
            }

            div[data-testid="stDataFrame"] {
                font-size: 12px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_title(title: str):
    st.markdown(
        f"""
        <div style="height: 0.2rem;"></div>
        <div class="bb-title">{html.escape(title)}</div>
        """,
        unsafe_allow_html=True,
    )


def get_logo_path():
    candidates = [
        Path("assets/logo_pm_sa.png"),
        Path("assets/logo.png"),
        Path("assets/portfolio_logo.png"),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def render_private_dashboard_logo(mode: str, authenticated: bool):
    if mode != "Private" or not authenticated:
        return

    logo_path = get_logo_path()
    if not logo_path:
        return

    c1, c2 = st.columns([1, 5])

    with c1:
        st.image(logo_path, width=110)

    with c2:
        st.markdown(
            """
            <div style="padding-top:0.35rem;">
                <div style="font-size:1.05rem; font-weight:800; color:#f3a712; text-transform:uppercase; letter-spacing:0.6px;">
                    Private Portfolio
                </div>
                <div style="font-size:0.82rem; color:#cbd5df; margin-top:0.2rem;">
                    Portfolio Management SA · Sebastian Aguilar
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def info_html(text: str, help_text: str, size: str = "1rem", weight: str = "700"):
    safe_help = html.escape(help_text, quote=True)
    safe_text = html.escape(text)
    return (
        f"<span style='font-size:{size}; font-weight:{weight}; color:#f3a712; "
        f"text-transform:uppercase; letter-spacing:0.5px;'>{safe_text}</span>"
        f"<span class='bb-info' title='{safe_help}'>ⓘ</span>"
    )


def info_section(title: str, help_text: str):
    st.markdown(
        f"""
        <div class="bb-section">
            <div class="bb-section-title">{info_html(title, help_text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def info_metric(container, label: str, value: str, help_text: str):
    container.markdown(
        info_html(label, help_text, size="0.84rem", weight="800"),
        unsafe_allow_html=True,
    )
    container.metric(" ", value)


def render_status_bar(mode: str, base_currency: str, profile: str, tc_model: str, sheets_ok: bool):
    sheets_text = "SHEETS OK" if sheets_ok else "SHEETS OFF"
    sheets_color = "#22c55e" if sheets_ok else "#ef4444"

    st.markdown(
        f"""
        <div style="
            display:flex;
            gap:18px;
            flex-wrap:wrap;
            align-items:center;
            margin:0.2rem 0 0.9rem 0;
            padding:0.45rem 0.65rem;
            border:1px solid #2b3340;
            border-left:4px solid #f3a712;
            background:#111821;
            border-radius:6px;
            font-size:0.82rem;
            text-transform:uppercase;
            letter-spacing:0.5px;
            color:#cbd5df;
        ">
            <span><b>Mode:</b> {mode}</span>
            <span><b>Base CCY:</b> {base_currency}</span>
            <span><b>Profile:</b> {profile}</span>
            <span><b>TC Model:</b> {tc_model}</span>
            <span><b>Private Sync:</b> <span style="color:{sheets_color}; font-weight:800;">{sheets_text}</span></span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_market_clocks():
    markets = [
        {"label": "New York", "exchange": "NYSE / Nasdaq", "tz": "America/New_York"},
        {"label": "London", "exchange": "LSE", "tz": "Europe/London"},
        {"label": "Frankfurt", "exchange": "Xetra", "tz": "Europe/Berlin"},
        {"label": "Zurich", "exchange": "SIX", "tz": "Europe/Zurich"},
        {"label": "Tokyo", "exchange": "TSE", "tz": "Asia/Tokyo"},
        {"label": "Shanghai", "exchange": "SSE", "tz": "Asia/Shanghai"},
        {"label": "Singapore", "exchange": "SGX", "tz": "Asia/Singapore"},
        {"label": "Bogotá", "exchange": "BVC", "tz": "America/Bogota"},
        {"label": "Sydney", "exchange": "ASX", "tz": "Australia/Sydney"},
    ]

    component = f"""
    <div id="clock-wrapper" style="border:1px solid #2b3340; border-left:4px solid #f3a712; border-radius:6px; padding:12px; background:#111821;">
      <div style="color:#f3a712; font-weight:800; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:10px;">
        Live Market Clocks
      </div>
      <div id="clock-grid" style="display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:10px;"></div>
    </div>

    <script>
      const markets = {json.dumps(markets)};

      function getCols() {{
        const w = window.innerWidth;
        if (w <= 520) return 1;
        if (w <= 900) return 2;
        return 3;
      }}

      function formatTime(tz) {{
        const now = new Date();
        const time = new Intl.DateTimeFormat("en-GB", {{
          timeZone: tz,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false
        }}).format(now);

        const date = new Intl.DateTimeFormat("en-GB", {{
          timeZone: tz,
          weekday: "short",
          day: "2-digit",
          month: "short"
        }}).format(now);

        return {{ time, date }};
      }}

      function setFrameHeight() {{
        const height = document.documentElement.scrollHeight;
        window.parent.postMessage({{
          isStreamlitMessage: true,
          type: "streamlit:setFrameHeight",
          height: height
        }}, "*");
      }}

      function renderClocks() {{
        const grid = document.getElementById("clock-grid");
        const cols = getCols();
        grid.style.gridTemplateColumns = `repeat(${{cols}}, minmax(0, 1fr))`;
        grid.innerHTML = "";

        markets.forEach((m) => {{
          const t = formatTime(m.tz);
          const card = document.createElement("div");
          card.style.background = "#0f141b";
          card.style.border = "1px solid #2d3642";
          card.style.borderRadius = "6px";
          card.style.padding = "12px";
          card.style.minHeight = "102px";
          card.innerHTML = `
            <div style="color:#f3a712; font-weight:800; font-size:13px; text-transform:uppercase;">${{m.label}}</div>
            <div style="color:#9fb0c3; font-size:11px; margin-top:2px;">${{m.exchange}}</div>
            <div style="color:#f8f8f8; font-size:18px; font-weight:800; margin-top:10px;">${{t.time}}</div>
            <div style="color:#7fb3ff; font-size:11px; margin-top:4px;">${{t.date}}</div>
          `;
          grid.appendChild(card);
        }});

        setTimeout(setFrameHeight, 120);
      }}

      renderClocks();
      setInterval(renderClocks, 1000);
      window.addEventListener("resize", renderClocks);
      setTimeout(setFrameHeight, 180);
    </script>
    """
    components_html(component, height=520, scrolling=False)


# =========================
# INVESTMENT HORIZON
# =========================
def build_projection_series(
    initial_value: float,
    annual_return: float,
    years: int,
    monthly_contribution: float = 0.0,
):
    months = int(years * 12)

    if annual_return <= -0.999:
        monthly_rate = -0.999
    else:
        monthly_rate = (1 + annual_return) ** (1 / 12) - 1

    values = [float(initial_value)]

    for _ in range(months):
        next_value = values[-1] * (1 + monthly_rate) + monthly_contribution
        values.append(max(float(next_value), 0.0))

    return pd.DataFrame(
        {
            "Month": range(months + 1),
            "Year": np.arange(months + 1) / 12,
            "Value": values,
        }
    )


def render_investment_horizon_section(
    total_value: float,
    base_currency: str,
    portfolio_returns: pd.Series,
):
    info_section(
        "Investment Horizon",
        "Projected portfolio value over a selected investment horizon using monthly compounding and optional monthly contributions."
    )

    horizon_years = st.selectbox(
        "Investment Horizon (Years)",
        [5, 10, 15, 20, 25, 30],
        index=1,
        help="Select the projection horizon.",
    )

    default_return = 0.08
    if not portfolio_returns.empty:
        hist_return = float(portfolio_returns.mean() * 252)
        if np.isfinite(hist_return):
            default_return = min(max(hist_return, 0.00), 0.15)

    expected_return_pct = st.slider(
        "Expected Annual Return (%)",
        min_value=0.0,
        max_value=20.0,
        value=float(round(default_return * 100, 1)),
        step=0.1,
        format="%.1f",
        help="Annual return assumption used in the projection, expressed as a percentage.",
    )
    expected_return = expected_return_pct / 100.0
    st.caption(f"Selected expected annual return: {expected_return_pct:.1f}%")

    monthly_contribution = st.number_input(
        f"Monthly Contribution ({base_currency})",
        min_value=0.0,
        value=0.0,
        step=100.0,
        help="Optional monthly contribution added to the portfolio projection.",
    )

    scenario_spread_pct = st.slider(
        "Scenario Spread (%)",
        min_value=0.0,
        max_value=10.0,
        value=3.0,
        step=0.1,
        format="%.1f",
        help="Difference around the base expected return used to build conservative and optimistic scenarios.",
    )
    scenario_spread = scenario_spread_pct / 100.0

    conservative_return = max(expected_return - scenario_spread, -0.95)
    optimistic_return = expected_return + scenario_spread

    conservative_df = build_projection_series(
        initial_value=total_value,
        annual_return=conservative_return,
        years=horizon_years,
        monthly_contribution=monthly_contribution,
    )

    base_df = build_projection_series(
        initial_value=total_value,
        annual_return=expected_return,
        years=horizon_years,
        monthly_contribution=monthly_contribution,
    )

    optimistic_df = build_projection_series(
        initial_value=total_value,
        annual_return=optimistic_return,
        years=horizon_years,
        monthly_contribution=monthly_contribution,
    )

    fig_projection = go.Figure()
    fig_projection.add_scatter(
        x=conservative_df["Year"],
        y=conservative_df["Value"],
        name=f"Conservative ({conservative_return:.1%})",
        mode="lines",
    )
    fig_projection.add_scatter(
        x=base_df["Year"],
        y=base_df["Value"],
        name=f"Base ({expected_return:.1%})",
        mode="lines",
    )
    fig_projection.add_scatter(
        x=optimistic_df["Year"],
        y=optimistic_df["Value"],
        name=f"Optimistic ({optimistic_return:.1%})",
        mode="lines",
    )
    fig_projection.update_layout(
        xaxis_title="Years",
        yaxis_title=f"Projected Value ({base_currency})",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=420,
        margin=dict(t=25, b=25, l=25, r=25),
    )
    st.plotly_chart(fig_projection, use_container_width=True)

    c1, c2, c3 = st.columns(3)
    info_metric(
        c1,
        "Conservative Final Value",
        f"{base_currency} {conservative_df['Value'].iloc[-1]:,.2f}",
        "Projected final portfolio value under the conservative scenario.",
    )
    info_metric(
        c2,
        "Base Final Value",
        f"{base_currency} {base_df['Value'].iloc[-1]:,.2f}",
        "Projected final portfolio value under the base scenario.",
    )
    info_metric(
        c3,
        "Optimistic Final Value",
        f"{base_currency} {optimistic_df['Value'].iloc[-1]:,.2f}",
        "Projected final portfolio value under the optimistic scenario.",
    )

    projection_table = pd.DataFrame(
        {
            "Scenario": ["Conservative", "Base", "Optimistic"],
            "Annual Return %": [
                round(conservative_return * 100, 2),
                round(expected_return * 100, 2),
                round(optimistic_return * 100, 2),
            ],
            "Final Value": [
                round(conservative_df["Value"].iloc[-1], 2),
                round(base_df["Value"].iloc[-1], 2),
                round(optimistic_df["Value"].iloc[-1], 2),
            ],
        }
    )
    st.dataframe(projection_table, use_container_width=True)


# =========================
# PRIVATE PORTFOLIO
# =========================
def load_private_portfolio():
    p = st.secrets["private_portfolio"]
    return {
        "SCHD": {"name": "Dividend ETF", "shares": float(p["SCHD"])},
        "VOO": {"name": "S&P 500", "shares": float(p["VOO"])},
        "VWCE.DE": {"name": "All World", "shares": float(p["VWCE_DE"])},
        "IGLN.L": {"name": "Gold", "shares": float(p["IGLN_L"])},
        "BND": {"name": "Bonds", "shares": float(p["BND"])},
    }


def get_manage_password():
    auth_section = dict(st.secrets["auth"])
    return auth_section.get("manage_password", auth_section["password"])


def merge_private_portfolios(base_private: dict, custom_private: dict):
    merged = dict(base_private)
    merged.update(custom_private)
    return merged


# =========================
# GOOGLE SHEETS
# =========================
def connect_private_positions_worksheet():
    try:
        gcp_cfg = dict(st.secrets["gcp_service_account"])
    except Exception as e:
        raise RuntimeError("Missing [gcp_service_account] in Streamlit secrets.") from e

    try:
        sheets_cfg = dict(st.secrets["sheets"])
    except Exception as e:
        raise RuntimeError("Missing [sheets] in Streamlit secrets.") from e

    required_gcp_keys = [
        "type",
        "project_id",
        "private_key",
        "client_email",
        "token_uri",
    ]
    missing_gcp = [k for k in required_gcp_keys if k not in gcp_cfg or not str(gcp_cfg[k]).strip()]
    if missing_gcp:
        raise RuntimeError(f"Missing keys in [gcp_service_account]: {', '.join(missing_gcp)}")

    worksheet_name = str(sheets_cfg.get("private_positions_worksheet", "private_positions")).strip()
    sheet_id = str(sheets_cfg.get("private_positions_sheet_id", "")).strip()
    sheet_url = str(sheets_cfg.get("private_positions_sheet_url", "")).strip()

    if not sheet_id and not sheet_url:
        raise RuntimeError("Missing 'private_positions_sheet_id' or 'private_positions_sheet_url' in [sheets].")

    private_key = str(gcp_cfg["private_key"])
    if "\\n" in private_key:
        gcp_cfg["private_key"] = private_key.replace("\\n", "\n")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    try:
        creds = Credentials.from_service_account_info(gcp_cfg, scopes=scopes)
    except Exception as e:
        raise RuntimeError(f"Invalid Google service account credentials: {e}") from e

    try:
        client = gspread.authorize(creds)
    except Exception as e:
        raise RuntimeError(f"Google authorization failed: {e}") from e

    try:
        if sheet_id:
            spreadsheet = client.open_by_key(sheet_id)
        else:
            spreadsheet = client.open_by_url(sheet_url)
    except Exception as e:
        raise RuntimeError(
            f"Could not open Google Sheet. Verify sheet access, APIs enabled, and sheet id/url. Original error: {e}"
        ) from e

    try:
        ws = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        try:
            ws = spreadsheet.add_worksheet(title=worksheet_name, rows=500, cols=3)
        except Exception as e:
            raise RuntimeError(f"Could not create worksheet '{worksheet_name}': {e}") from e

    expected_header = ["Ticker", "Name", "Shares"]

    try:
        current_header = ws.row_values(1)
    except Exception:
        current_header = []

    if current_header != expected_header:
        try:
            ws.clear()
            ws.update(range_name="A1:C1", values=[expected_header])
        except Exception as e:
            raise RuntimeError(f"Could not initialize worksheet header: {e}") from e

    return ws


def load_private_positions_from_sheets():
    ws = connect_private_positions_worksheet()
    records = ws.get_all_records()

    positions = {}
    for row in records:
        ticker = str(row.get("Ticker", "")).strip().upper()
        name = str(row.get("Name", "")).strip()
        shares = row.get("Shares", 0)

        if ticker and name:
            try:
                positions[ticker] = {
                    "name": name,
                    "shares": float(shares),
                }
            except Exception:
                continue

    return positions


def save_private_positions_to_sheets(positions: dict):
    ws = connect_private_positions_worksheet()

    rows = [["Ticker", "Name", "Shares"]]
    for ticker in sorted(positions.keys()):
        meta = positions[ticker]
        rows.append([ticker, meta["name"], float(meta["shares"])])

    ws.clear()
    ws.update(range_name="A1", values=rows)


def build_private_portfolio_for_save(portfolio_data: dict, prefix: str):
    saved = {}

    for ticker, meta in portfolio_data.items():
        widget_key = f"{prefix}_shares_{ticker}"
        saved[ticker] = {
            "name": meta["name"],
            "shares": float(st.session_state.get(widget_key, meta["shares"])),
        }

    return saved


def update_selected_private_position(updated_portfolio: dict, prefix: str, selected_ticker: str, new_shares: float):
    payload = {}

    for ticker, meta in updated_portfolio.items():
        payload[ticker] = {
            "name": meta["name"],
            "shares": float(st.session_state.get(f"{prefix}_shares_{ticker}", meta["shares"])),
        }

    if selected_ticker not in payload:
        raise ValueError(f"{selected_ticker} not found in private portfolio.")

    payload[selected_ticker]["shares"] = float(new_shares)
    st.session_state[f"{prefix}_shares_{selected_ticker}"] = float(new_shares)

    save_private_positions_to_sheets(payload)


# =========================
# MODE / SIDEBAR
# =========================
def get_active_portfolio(mode: str, authenticated: bool, private_portfolio: dict):
    if mode == "Private" and authenticated:
        return private_portfolio
    return public_portfolio


def get_mode_prefix(mode: str):
    return "private" if mode == "Private" else "public"


def init_mode_state(portfolio_data: dict, prefix: str):
    for ticker, meta in portfolio_data.items():
        key = f"{prefix}_shares_{ticker}"
        if key not in st.session_state:
            st.session_state[key] = float(meta["shares"])


def reset_mode_state(portfolio_data: dict, prefix: str):
    for ticker, meta in portfolio_data.items():
        st.session_state[f"{prefix}_shares_{ticker}"] = float(meta["shares"])


def build_current_portfolio(portfolio_data: dict, prefix: str, mode: str):
    updated = {}
    step_value = 1.0 if mode == "Public" else 0.0001

    for ticker, meta in portfolio_data.items():
        widget_key = f"{prefix}_shares_{ticker}"

        st.sidebar.number_input(
            f"{ticker} shares",
            min_value=0.0,
            step=step_value,
            format="%.4f",
            key=widget_key,
            help=(
                "Number of shares currently held for this asset. "
                "Public mode changes with step 1. Private mode changes with step 0.0001."
            ),
        )

        updated[ticker] = {
            "name": meta["name"],
            "shares": float(st.session_state[widget_key]),
            "base_shares": float(meta["shares"]),
        }

    return updated


# =========================
# FX / PRICE HELPERS
# =========================
def asset_currency(ticker: str) -> str:
    if ticker.endswith(".DE") or ticker.endswith(".AS"):
        return "EUR"
    if ticker.endswith(".L"):
        return "GBP"
    if ticker.endswith(".AX"):
        return "AUD"
    return "USD"


def asset_market_group(ticker: str) -> str:
    if ticker.endswith(".L"):
        return "UK"
    if ticker.endswith(".AX"):
        return "Australia"
    if "." in ticker:
        return "Europe"
    return "US"


def build_fx_data(tickers: list, base_currency: str, period: str = "2y"):
    needed_ccy = set(asset_currency(t) for t in tickers)
    needed_ccy.add(base_currency)
    needed_ccy.add("USD")

    fx_tickers = set()
    for a in needed_ccy:
        for b in needed_ccy:
            if a != b:
                fx_tickers.add(f"{a}{b}=X")

    fx_tickers = sorted(fx_tickers)
    fx_prices = get_prices(fx_tickers) if fx_tickers else {}
    fx_hist = get_historical_data(fx_tickers, period=period) if fx_tickers else pd.DataFrame()

    return fx_prices, fx_hist, fx_tickers


def is_valid_series(df: pd.DataFrame, ticker: str) -> bool:
    try:
        return ticker in df.columns and not pd.to_numeric(df[ticker], errors="coerce").dropna().empty
    except Exception:
        return False


def is_valid_price(prices: dict, ticker: str) -> bool:
    val = prices.get(ticker)
    return isinstance(val, (int, float)) and pd.notna(val) and val > 0


def patch_market_data_with_proxies(live_prices_native: dict, asset_hist_native: pd.DataFrame, tickers: list, period: str = "2y"):
    patched_prices = dict(live_prices_native) if live_prices_native is not None else {}
    patched_hist = asset_hist_native.copy() if asset_hist_native is not None else pd.DataFrame()

    for ticker in tickers:
        proxy = PROXY_TICKER_MAP.get(ticker)
        if not proxy:
            continue

        need_hist = not is_valid_series(patched_hist, ticker)
        need_price = not is_valid_price(patched_prices, ticker)

        if not need_hist and not need_price:
            continue

        proxy_hist = get_historical_data([proxy], period=period)
        proxy_prices = get_prices([proxy])

        if need_hist and not proxy_hist.empty and proxy in proxy_hist.columns:
            patched_hist[ticker] = pd.to_numeric(proxy_hist[proxy], errors="coerce")

        if need_price and is_valid_price(proxy_prices, proxy):
            patched_prices[ticker] = float(proxy_prices[proxy])

    return patched_prices, patched_hist


def _get_direct_or_inverse_current(from_ccy: str, to_ccy: str, fx_prices: dict, fx_hist: pd.DataFrame):
    if from_ccy == to_ccy:
        return 1.0

    direct = f"{from_ccy}{to_ccy}=X"
    inverse = f"{to_ccy}{from_ccy}=X"

    direct_val = fx_prices.get(direct)
    if isinstance(direct_val, (int, float)) and pd.notna(direct_val) and direct_val > 0:
        return float(direct_val)

    inverse_val = fx_prices.get(inverse)
    if isinstance(inverse_val, (int, float)) and pd.notna(inverse_val) and inverse_val > 0:
        return 1.0 / float(inverse_val)

    try:
        if direct in fx_hist.columns:
            direct_hist = pd.to_numeric(fx_hist[direct], errors="coerce").dropna()
            if not direct_hist.empty and direct_hist.iloc[-1] > 0:
                return float(direct_hist.iloc[-1])
    except Exception:
        pass

    try:
        if inverse in fx_hist.columns:
            inverse_hist = pd.to_numeric(fx_hist[inverse], errors="coerce").dropna()
            if not inverse_hist.empty and inverse_hist.iloc[-1] > 0:
                return 1.0 / float(inverse_hist.iloc[-1])
    except Exception:
        pass

    return None


def get_fx_rate_current(from_ccy: str, to_ccy: str, fx_prices: dict, fx_hist: pd.DataFrame):
    if from_ccy == to_ccy:
        return 1.0

    direct = _get_direct_or_inverse_current(from_ccy, to_ccy, fx_prices, fx_hist)
    if direct is not None:
        return direct

    if from_ccy != "USD" and to_ccy != "USD":
        leg1 = _get_direct_or_inverse_current(from_ccy, "USD", fx_prices, fx_hist)
        leg2 = _get_direct_or_inverse_current("USD", to_ccy, fx_prices, fx_hist)
        if leg1 is not None and leg2 is not None:
            return leg1 * leg2

    return np.nan


def get_fx_series(from_ccy: str, to_ccy: str, fx_hist: pd.DataFrame):
    if from_ccy == to_ccy:
        return None

    direct = f"{from_ccy}{to_ccy}=X"
    inverse = f"{to_ccy}{from_ccy}=X"

    try:
        if direct in fx_hist.columns:
            s = pd.to_numeric(fx_hist[direct], errors="coerce").dropna()
            if not s.empty:
                return s
    except Exception:
        pass

    try:
        if inverse in fx_hist.columns:
            s = pd.to_numeric(fx_hist[inverse], errors="coerce").dropna()
            if not s.empty:
                return 1.0 / s.replace(0, np.nan)
    except Exception:
        pass

    if from_ccy != "USD" and to_ccy != "USD":
        s1 = get_fx_series(from_ccy, "USD", fx_hist)
        s2 = get_fx_series("USD", to_ccy, fx_hist)

        if s1 is not None and s2 is not None:
            aligned = pd.concat([s1.rename("leg1"), s2.rename("leg2")], axis=1).dropna()
            if not aligned.empty:
                return aligned["leg1"] * aligned["leg2"]

    return None


def convert_historical_to_base(asset_hist_native: pd.DataFrame, tickers: list, base_currency: str, fx_hist: pd.DataFrame):
    converted = {}
    missing_fx = []

    for ticker in tickers:
        if ticker not in asset_hist_native.columns:
            continue

        native_series = pd.to_numeric(asset_hist_native[ticker], errors="coerce").dropna()
        if native_series.empty:
            continue

        from_ccy = asset_currency(ticker)

        if from_ccy == base_currency:
            converted[ticker] = native_series.rename(ticker)
            continue

        fx_series = get_fx_series(from_ccy, base_currency, fx_hist)
        if fx_series is None:
            missing_fx.append(f"{from_ccy}->{base_currency}")
            continue

        aligned = pd.concat([native_series.rename("asset"), fx_series.rename("fx")], axis=1).dropna()
        if not aligned.empty:
            converted[ticker] = (aligned["asset"] * aligned["fx"]).rename(ticker)

    if not converted:
        return pd.DataFrame(), sorted(set(missing_fx))

    out = pd.concat(converted.values(), axis=1)
    out.columns = list(converted.keys())
    out = out.sort_index().ffill().dropna(how="all")

    return out, sorted(set(missing_fx))


def get_safe_native_price(ticker: str, live_prices: dict, asset_hist_native: pd.DataFrame):
    live_price = live_prices.get(ticker)

    if isinstance(live_price, (int, float)) and pd.notna(live_price) and live_price > 0:
        return float(live_price)

    try:
        if ticker in asset_hist_native.columns:
            last_hist = pd.to_numeric(asset_hist_native[ticker], errors="coerce").dropna().iloc[-1]
            return float(last_hist)
    except Exception:
        pass

    return 0.0


# =========================
# DATAFRAMES / RETURNS
# =========================
def build_portfolio_df(
    updated_portfolio: dict,
    live_prices_native: dict,
    asset_hist_native: pd.DataFrame,
    fx_prices: dict,
    fx_hist: pd.DataFrame,
    base_currency: str,
):
    rows = []
    total_value = 0.0
    base_total_value = 0.0

    for ticker, meta in updated_portfolio.items():
        native_currency = asset_currency(ticker)
        native_price = get_safe_native_price(ticker, live_prices_native, asset_hist_native)
        fx_rate = get_fx_rate_current(native_currency, base_currency, fx_prices, fx_hist)

        if pd.isna(fx_rate):
            fx_rate = 0.0

        price = native_price * fx_rate

        shares = float(meta["shares"])
        base_shares = float(meta["base_shares"])

        value = shares * price
        base_value = base_shares * price

        total_value += value
        base_total_value += base_value

        rows.append(
            {
                "Ticker": ticker,
                "Name": meta["name"],
                "Market": asset_market_group(ticker),
                "Native Currency": native_currency,
                "Shares": round(shares, 4),
                "Native Price": round(native_price, 2),
                "FX Rate": round(fx_rate, 6),
                "Price": round(price, 2),
                "Value": round(value, 2),
                "Base Shares": round(base_shares, 4),
                "Base Value": round(base_value, 2),
            }
        )

    df = pd.DataFrame(rows)

    if total_value > 0:
        df["Weight"] = df["Value"] / total_value
    else:
        df["Weight"] = 0.0

    if base_total_value > 0:
        df["Target Weight"] = df["Base Value"] / base_total_value
    else:
        df["Target Weight"] = 0.0

    df["Weight %"] = (df["Weight"] * 100).round(2)
    df["Target %"] = (df["Target Weight"] * 100).round(2)
    df["Deviation %"] = ((df["Weight"] - df["Target Weight"]) * 100).round(2)

    return df, total_value


def build_portfolio_returns(df: pd.DataFrame, historical_base: pd.DataFrame):
    usable = [ticker for ticker in df["Ticker"] if ticker in historical_base.columns]

    if not usable:
        return pd.Series(dtype=float), pd.DataFrame()

    hist = historical_base[usable].copy().dropna(how="all")
    returns = hist.pct_change().dropna()

    if returns.empty:
        return pd.Series(dtype=float), returns

    weight_map = df.set_index("Ticker")["Weight"]
    weights = weight_map.loc[usable]

    if weights.sum() <= 0:
        return pd.Series(dtype=float), returns

    weights = weights / weights.sum()
    portfolio_returns = returns.mul(weights, axis=1).sum(axis=1)

    return portfolio_returns, returns


def build_benchmark_returns(base_currency: str, fx_hist: pd.DataFrame):
    bench_native = get_historical_data(["VOO"], period="2y")
    if bench_native.empty or "VOO" not in bench_native.columns:
        return pd.Series(dtype=float)

    voo_series = pd.to_numeric(bench_native["VOO"], errors="coerce").dropna()

    if base_currency == "USD":
        return voo_series.pct_change().dropna()

    fx_series = get_fx_series("USD", base_currency, fx_hist)
    if fx_series is None:
        return pd.Series(dtype=float)

    aligned = pd.concat([voo_series.rename("VOO"), fx_series.rename("FX")], axis=1).dropna()
    if aligned.empty:
        return pd.Series(dtype=float)

    bench_base = aligned["VOO"] * aligned["FX"]
    return bench_base.pct_change().dropna()


# =========================
# OPTIMIZATION
# =========================
def get_default_constraints(profile: str):
    if profile == "Aggressive":
        return {"max_single_asset": 0.70, "min_bonds": 0.00, "min_gold": 0.00}
    if profile == "Balanced":
        return {"max_single_asset": 0.45, "min_bonds": 0.10, "min_gold": 0.05}
    return {"max_single_asset": 0.35, "min_bonds": 0.20, "min_gold": 0.10}


def classify_assets(asset_names):
    bonds = {"BND", "AGG", "IEF", "TLT", "VGIT", "BNDX"}
    gold = {"IGLN.L", "GLD", "IAU", "SGLN.L"}

    bond_idx = [i for i, t in enumerate(asset_names) if t in bonds]
    gold_idx = [i for i, t in enumerate(asset_names) if t in gold]

    return bond_idx, gold_idx


def bucket_for_ticker(ticker: str):
    bonds = {"BND", "AGG", "IEF", "TLT", "VGIT", "BNDX"}
    gold = {"IGLN.L", "GLD", "IAU", "SGLN.L"}
    if ticker in bonds:
        return "Bonds"
    if ticker in gold:
        return "Gold"
    return "Equities"


def simulate_constrained_efficient_frontier(
    asset_returns: pd.DataFrame,
    asset_names: list,
    constraints: dict,
    risk_free_rate: float = 0.02,
    n_portfolios: int = 8000,
):
    if asset_returns.empty or asset_returns.shape[1] < 2:
        return pd.DataFrame()

    mean_returns = asset_returns.mean() * 252
    cov_matrix = asset_returns.cov() * 252

    n_assets = len(mean_returns)
    max_single_asset = float(constraints["max_single_asset"])
    min_bonds = float(constraints["min_bonds"])
    min_gold = float(constraints["min_gold"])

    if min_bonds + min_gold > 1:
        return pd.DataFrame()

    bond_idx, gold_idx = classify_assets(asset_names)

    rng = np.random.default_rng(42)
    raw = rng.random((n_portfolios * 6, n_assets))
    weights = raw / raw.sum(axis=1, keepdims=True)

    mask = weights.max(axis=1) <= max_single_asset

    if bond_idx:
        mask &= weights[:, bond_idx].sum(axis=1) >= min_bonds
    elif min_bonds > 0:
        mask &= False

    if gold_idx:
        mask &= weights[:, gold_idx].sum(axis=1) >= min_gold
    elif min_gold > 0:
        mask &= False

    feasible = weights[mask]

    if feasible.shape[0] == 0:
        return pd.DataFrame()

    feasible = feasible[:n_portfolios]

    port_returns = feasible @ mean_returns.values
    port_vols = np.sqrt(np.einsum("ij,jk,ik->i", feasible, cov_matrix.values, feasible))
    sharpe = np.where(port_vols > 0, (port_returns - risk_free_rate) / port_vols, 0)

    frontier = pd.DataFrame(
        {
            "Return": port_returns,
            "Volatility": port_vols,
            "Sharpe": sharpe,
        }
    )
    frontier["Weights"] = list(feasible)

    return frontier


def weights_table(weight_array, asset_names):
    out = pd.DataFrame(
        {
            "Ticker": asset_names,
            "Weight %": np.round(np.array(weight_array) * 100, 2),
        }
    )
    return out.sort_values("Weight %", ascending=False).reset_index(drop=True)


def build_recommended_shares_table(weight_array, asset_names, df_current):
    price_map = df_current.set_index("Ticker")["Price"].to_dict()
    current_shares_map = df_current.set_index("Ticker")["Shares"].to_dict()
    current_weight_map = df_current.set_index("Ticker")["Weight %"].to_dict()
    current_value_map = df_current.set_index("Ticker")["Value"].to_dict()

    total_value = float(df_current["Value"].sum())
    rows = []

    for ticker, weight in zip(asset_names, weight_array):
        price = float(price_map.get(ticker, 0.0))
        current_shares = float(current_shares_map.get(ticker, 0.0))
        current_weight = float(current_weight_map.get(ticker, 0.0))
        current_value = float(current_value_map.get(ticker, 0.0))

        target_value = total_value * float(weight)
        target_shares = target_value / price if price > 0 else 0.0
        delta_shares = target_shares - current_shares

        rows.append(
            {
                "Ticker": ticker,
                "Current Shares": round(current_shares, 4),
                "Recommended Shares": round(target_shares, 4),
                "Shares Delta": round(delta_shares, 4),
                "Current Value": round(current_value, 2),
                "Target Value": round(target_value, 2),
                "Current Weight %": round(current_weight, 2),
                "Target Weight %": round(float(weight) * 100, 2),
            }
        )

    rec = pd.DataFrame(rows)
    rec["Abs Delta"] = rec["Shares Delta"].abs()
    rec = rec.sort_values("Abs Delta", ascending=False).drop(columns=["Abs Delta"]).reset_index(drop=True)
    return rec


# =========================
# COSTS / RISK
# =========================
def estimate_transaction_cost(
    ticker: str,
    trade_value: float,
    base_currency: str,
    native_currency: str,
    model: str,
    params: dict,
):
    if trade_value <= 0:
        return {
            "Commission": 0.0,
            "Slippage": 0.0,
            "FX Cost": 0.0,
            "Total Cost": 0.0,
        }

    market = asset_market_group(ticker)

    if model == "Simple Bps":
        commission = 0.0
        slippage = trade_value * params["simple_bps"] / 10000
        fx_cost = trade_value * params["fx_bps"] / 10000 if native_currency != base_currency else 0.0

    elif model == "Manual Override":
        commission = params["manual_fixed_fee"]
        slippage = trade_value * params["manual_bps"] / 10000
        fx_cost = trade_value * params["fx_bps"] / 10000 if native_currency != base_currency else 0.0

    else:
        if market == "US":
            commission_bps = params["us_commission_bps"]
            min_fee = params["us_min_fee"]
        elif market == "UK":
            commission_bps = params["uk_commission_bps"]
            min_fee = params["uk_min_fee"]
        else:
            commission_bps = params["eu_commission_bps"]
            min_fee = params["eu_min_fee"]

        commission = max(trade_value * commission_bps / 10000, min_fee)
        slippage = trade_value * params["slippage_bps"] / 10000
        fx_cost = trade_value * params["fx_bps"] / 10000 if native_currency != base_currency else 0.0

    total_cost = commission + slippage + fx_cost

    return {
        "Commission": commission,
        "Slippage": slippage,
        "FX Cost": fx_cost,
        "Total Cost": total_cost,
    }


def build_rebalancing_table(
    df_current: pd.DataFrame,
    target_weight_map: dict,
    base_currency: str,
    tc_model: str,
    tc_params: dict,
):
    total_value = float(df_current["Value"].sum())
    rows = []

    for _, row in df_current.iterrows():
        ticker = row["Ticker"]
        price = float(row["Price"])
        current_shares = float(row["Shares"])
        current_value = float(row["Value"])
        current_weight = float(row["Weight"])
        native_currency = row["Native Currency"]
        market = row["Market"]

        target_weight = float(target_weight_map.get(ticker, 0.0))
        target_value = total_value * target_weight
        target_shares = target_value / price if price > 0 else 0.0

        shares_delta = target_shares - current_shares
        value_delta = target_value - current_value
        trade_value = abs(value_delta)

        if abs(value_delta) < 1:
            action = "Hold"
        elif value_delta > 0:
            action = "Buy"
        else:
            action = "Sell"

        costs = estimate_transaction_cost(
            ticker=ticker,
            trade_value=trade_value,
            base_currency=base_currency,
            native_currency=native_currency,
            model=tc_model,
            params=tc_params,
        )

        if action == "Buy":
            net_cash_flow = -(trade_value + costs["Total Cost"])
        elif action == "Sell":
            net_cash_flow = trade_value - costs["Total Cost"]
        else:
            net_cash_flow = 0.0

        rows.append(
            {
                "Ticker": ticker,
                "Market": market,
                "Native Currency": native_currency,
                "Current Shares": round(current_shares, 4),
                "Target Shares": round(target_shares, 4),
                "Shares Delta": round(shares_delta, 4),
                "Current Value": round(current_value, 2),
                "Target Value": round(target_value, 2),
                "Value Delta": round(value_delta, 2),
                "Current Weight %": round(current_weight * 100, 2),
                "Target Weight %": round(target_weight * 100, 2),
                "Estimated Cost": round(costs["Total Cost"], 2),
                "Net Cash Flow": round(net_cash_flow, 2),
                "Action": action,
            }
        )

    out = pd.DataFrame(rows)
    out["Abs Value Delta"] = out["Value Delta"].abs()
    out = out.sort_values("Abs Value Delta", ascending=False).drop(columns=["Abs Value Delta"]).reset_index(drop=True)
    return out


def build_stress_test_table(df_current: pd.DataFrame, shocks: dict):
    rows = []
    current_total = float(df_current["Value"].sum())
    stressed_total = 0.0

    for _, row in df_current.iterrows():
        ticker = row["Ticker"]
        bucket = bucket_for_ticker(ticker)
        shock = float(shocks.get(bucket, 0.0))

        current_price = float(row["Price"])
        current_value = float(row["Value"])
        shares = float(row["Shares"])

        stressed_price = current_price * (1 + shock)
        stressed_value = shares * stressed_price
        stressed_total += stressed_value

        rows.append(
            {
                "Ticker": ticker,
                "Bucket": bucket,
                "Shock %": round(shock * 100, 2),
                "Current Price": round(current_price, 2),
                "Stressed Price": round(stressed_price, 2),
                "Current Value": round(current_value, 2),
                "Stressed Value": round(stressed_value, 2),
                "P/L": round(stressed_value - current_value, 2),
            }
        )

    out = pd.DataFrame(rows)
    if stressed_total > 0:
        out["Stressed Weight %"] = (out["Stressed Value"] / stressed_total * 100).round(2)
    else:
        out["Stressed Weight %"] = 0.0

    return out, current_total, stressed_total


def compute_rolling_metrics(portfolio_returns: pd.Series, benchmark_returns: pd.Series, risk_free_rate: float, window: int):
    if portfolio_returns.empty:
        return pd.DataFrame()

    df_roll = pd.DataFrame(index=portfolio_returns.index)
    rolling_vol = portfolio_returns.rolling(window).std() * np.sqrt(252)
    rolling_return = portfolio_returns.rolling(window).mean() * 252
    rolling_sharpe = (rolling_return - risk_free_rate) / rolling_vol.replace(0, np.nan)

    cum = (1 + portfolio_returns).cumprod()
    rolling_peak = cum.rolling(window).max()
    rolling_drawdown = cum / rolling_peak - 1

    df_roll["Rolling Volatility"] = rolling_vol
    df_roll["Rolling Sharpe"] = rolling_sharpe
    df_roll["Rolling Drawdown"] = rolling_drawdown

    if not benchmark_returns.empty:
        aligned = pd.concat(
            [portfolio_returns.rename("Portfolio"), benchmark_returns.rename("Benchmark")],
            axis=1
        ).dropna()

        if not aligned.empty:
            rolling_cov = aligned["Portfolio"].rolling(window).cov(aligned["Benchmark"])
            rolling_var = aligned["Benchmark"].rolling(window).var()
            rolling_beta = rolling_cov / rolling_var.replace(0, np.nan)
            df_roll = df_roll.join(rolling_beta.rename("Rolling Beta"), how="left")

    return df_roll.dropna(how="all")


# =========================
# APP CONTEXT
# =========================
def build_app_context():
    private_available = True
    positions_sheet_available = True
    positions_sheet_error = ""
    private_portfolio = {}
    private_sheet_positions = {}

    try:
        base_private_portfolio = load_private_portfolio()
    except Exception as e:
        private_available = False
        base_private_portfolio = {}
        positions_sheet_error = f"Private base portfolio error: {e}"

    if private_available:
        try:
            private_sheet_positions = load_private_positions_from_sheets()
        except Exception as e:
            positions_sheet_available = False
            positions_sheet_error = str(e)
            private_sheet_positions = {}

        private_portfolio = merge_private_portfolios(
            base_private_portfolio,
            private_sheet_positions,
        )

    mode = st.sidebar.selectbox("View Mode", ["Public", "Private"])
    authenticated = False

    if mode == "Private":
        if not private_available:
            st.error("Private portfolio not available. Check Streamlit secrets.")
            st.stop()

        password = st.sidebar.text_input("Password", type="password")

        if not password:
            st.stop()

        if password != st.secrets["auth"]["password"]:
            st.error("Incorrect password.")
            st.stop()

        authenticated = True

    base_currency = st.sidebar.selectbox(
        "Base Currency",
        SUPPORTED_BASE_CCY,
        index=0,
        help="Reference currency used to convert all positions, weights, returns, and rebalancing calculations.",
    )

    portfolio_data = get_active_portfolio(mode, authenticated, private_portfolio)
    prefix = get_mode_prefix(mode)

    init_mode_state(portfolio_data, prefix)

    if mode == "Public" and st.session_state.get("public_defaults_version") != PUBLIC_DEFAULTS_VERSION:
        reset_mode_state(portfolio_data, prefix)
        st.session_state["public_defaults_version"] = PUBLIC_DEFAULTS_VERSION

    if st.sidebar.button("Reset Portfolio", help="Restore the original share quantities defined for the active mode."):
        reset_mode_state(portfolio_data, prefix)
        st.rerun()

    st.sidebar.header("Portfolio Inputs")
    updated_portfolio = build_current_portfolio(portfolio_data, prefix, mode)

    st.sidebar.header("Optimization Settings")
    profile = st.sidebar.selectbox("Investor Profile", ["Aggressive", "Balanced", "Conservative"])
    defaults = get_default_constraints(profile)

    with st.sidebar.expander("Custom Constraints", expanded=False):
        max_single_asset = st.number_input("Max single-asset weight", 0.05, 1.00, float(defaults["max_single_asset"]), 0.01, format="%.2f")
        min_bonds = st.number_input("Minimum bonds allocation", 0.00, 1.00, float(defaults["min_bonds"]), 0.01, format="%.2f")
        min_gold = st.number_input("Minimum gold allocation", 0.00, 1.00, float(defaults["min_gold"]), 0.01, format="%.2f")
        risk_free_rate = st.number_input("Risk-free rate", 0.00, 0.20, float(DEFAULT_RISK_FREE_RATE), 0.005, format="%.3f")

    constraints = {
        "max_single_asset": max_single_asset,
        "min_bonds": min_bonds,
        "min_gold": min_gold,
    }

    st.sidebar.header("Transaction Cost Model")
    tc_model = st.sidebar.selectbox(
        "Model",
        ["Broker Profile", "Simple Bps", "Manual Override"],
        help="Automated cost estimation model used in the rebalancing engine.",
    )

    with st.sidebar.expander("Transaction Cost Parameters", expanded=False):
        if tc_model == "Broker Profile":
            us_commission_bps = st.number_input("US commission (bps)", 0.0, 100.0, 3.0, 0.5)
            us_min_fee = st.number_input(f"US minimum fee ({base_currency})", 0.0, 50.0, 1.0, 0.5)
            eu_commission_bps = st.number_input("Europe commission (bps)", 0.0, 100.0, 5.0, 0.5)
            eu_min_fee = st.number_input(f"Europe minimum fee ({base_currency})", 0.0, 50.0, 1.5, 0.5)
            uk_commission_bps = st.number_input("UK commission (bps)", 0.0, 100.0, 5.0, 0.5)
            uk_min_fee = st.number_input(f"UK minimum fee ({base_currency})", 0.0, 50.0, 1.5, 0.5)
            slippage_bps = st.number_input("Slippage (bps)", 0.0, 100.0, 5.0, 0.5)
            fx_bps = st.number_input("FX conversion cost (bps)", 0.0, 100.0, 10.0, 0.5)

            tc_params = {
                "us_commission_bps": us_commission_bps,
                "us_min_fee": us_min_fee,
                "eu_commission_bps": eu_commission_bps,
                "eu_min_fee": eu_min_fee,
                "uk_commission_bps": uk_commission_bps,
                "uk_min_fee": uk_min_fee,
                "slippage_bps": slippage_bps,
                "fx_bps": fx_bps,
            }

        elif tc_model == "Simple Bps":
            simple_bps = st.number_input("All-in trading cost (bps)", 0.0, 100.0, 10.0, 0.5)
            fx_bps = st.number_input("FX conversion cost (bps)", 0.0, 100.0, 10.0, 0.5)

            tc_params = {
                "simple_bps": simple_bps,
                "fx_bps": fx_bps,
            }

        else:
            manual_bps = st.number_input("Variable cost (bps)", 0.0, 100.0, 8.0, 0.5)
            manual_fixed_fee = st.number_input(f"Fixed fee per trade ({base_currency})", 0.0, 100.0, 1.0, 0.5)
            fx_bps = st.number_input("FX conversion cost (bps)", 0.0, 100.0, 10.0, 0.5)

            tc_params = {
                "manual_bps": manual_bps,
                "manual_fixed_fee": manual_fixed_fee,
                "fx_bps": fx_bps,
            }

    st.sidebar.header("Stress Testing")
    equity_shock = st.sidebar.number_input("Equities Shock", -1.00, 1.00, -0.10, 0.01, format="%.2f")
    bonds_shock = st.sidebar.number_input("Bonds Shock", -1.00, 1.00, -0.03, 0.01, format="%.2f")
    gold_shock = st.sidebar.number_input("Gold Shock", -1.00, 1.00, 0.05, 0.01, format="%.2f")
    rolling_window = st.sidebar.slider("Rolling Window (days)", 21, 252, 63, 21)

    stress_shocks = {
        "Equities": equity_shock,
        "Bonds": bonds_shock,
        "Gold": gold_shock,
    }

    tickers = list(updated_portfolio.keys())
    live_prices_native = get_prices(tickers)
    asset_hist_native = get_historical_data(tickers, period="2y")

    if asset_hist_native.empty:
        st.error("Could not load historical data.")
        st.stop()

    live_prices_native, asset_hist_native = patch_market_data_with_proxies(
        live_prices_native=live_prices_native,
        asset_hist_native=asset_hist_native,
        tickers=tickers,
        period="2y",
    )

    fx_prices, fx_hist, _ = build_fx_data(tickers, base_currency, period="2y")
    historical_base, missing_fx = convert_historical_to_base(asset_hist_native, tickers, base_currency, fx_hist)

    if historical_base.empty:
        st.error("Could not build base-currency historical series.")
        st.stop()

    missing_hist = [ticker for ticker in tickers if ticker not in historical_base.columns]
    if missing_hist:
        st.warning(f"No converted historical data for: {', '.join(missing_hist)}")

    if missing_fx:
        st.warning(f"Missing FX history for: {', '.join(missing_fx)}")

    df, total_value = build_portfolio_df(
        updated_portfolio=updated_portfolio,
        live_prices_native=live_prices_native,
        asset_hist_native=asset_hist_native,
        fx_prices=fx_prices,
        fx_hist=fx_hist,
        base_currency=base_currency,
    )

    display_df = df[
        [
            "Ticker",
            "Name",
            "Market",
            "Native Currency",
            "Shares",
            "Native Price",
            "FX Rate",
            "Price",
            "Value",
            "Weight %",
            "Target %",
            "Deviation %",
        ]
    ].copy()

    nonzero_df = df[df["Value"] > 0].copy()

    if not nonzero_df.empty:
        fig_pie = px.pie(nonzero_df, names="Name", values="Value", hole=0.45)
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
    else:
        fig_pie = go.Figure()
        fig_pie.add_annotation(
            text="No portfolio value to display",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=18, color="#cbd5df"),
        )

    fig_pie.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=360,
        margin=dict(t=20, b=20, l=20, r=20),
        legend=dict(orientation="h", y=-0.08),
    )

    fig_bar = go.Figure()
    fig_bar.add_bar(x=df["Ticker"], y=df["Weight %"], name="Actual %")
    fig_bar.add_bar(x=df["Ticker"], y=df["Target %"], name="Target %")
    fig_bar.update_layout(
        barmode="group",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=360,
        margin=dict(t=20, b=20, l=20, r=20),
    )

    portfolio_returns, asset_returns = build_portfolio_returns(df, historical_base)
    benchmark_returns = build_benchmark_returns(base_currency, fx_hist)

    total_return = 0.0
    volatility = 0.0
    sharpe = 0.0
    max_drawdown = 0.0
    alpha = 0.0
    beta = 0.0
    tracking_error = 0.0
    information_ratio = 0.0

    portfolio_cum = pd.Series(dtype=float)
    benchmark_cum = pd.Series(dtype=float)

    if not portfolio_returns.empty:
        portfolio_cum = (1 + portfolio_returns).cumprod()
        total_return = float(portfolio_cum.iloc[-1] - 1)
        volatility = float(portfolio_returns.std() * np.sqrt(252))

        if volatility > 0:
            sharpe = float((portfolio_returns.mean() * 252 - risk_free_rate) / volatility)

        rolling_max = portfolio_cum.cummax()
        drawdown = portfolio_cum / rolling_max - 1
        max_drawdown = float(drawdown.min())

    if not portfolio_returns.empty and not benchmark_returns.empty:
        aligned = pd.concat(
            [portfolio_returns.rename("Portfolio"), benchmark_returns.rename("Benchmark")],
            axis=1
        ).dropna()

        if not aligned.empty:
            benchmark_cum = (1 + aligned["Benchmark"]).cumprod()

            bench_var = aligned["Benchmark"].var()
            if bench_var > 0:
                beta = float(aligned.cov().loc["Portfolio", "Benchmark"] / bench_var)

            p_mean = float(aligned["Portfolio"].mean() * 252)
            b_mean = float(aligned["Benchmark"].mean() * 252)
            alpha = float(p_mean - beta * b_mean)

            excess = aligned["Portfolio"] - aligned["Benchmark"]
            tracking_error = float(excess.std() * np.sqrt(252))

            if tracking_error > 0:
                information_ratio = float((excess.mean() * 252) / tracking_error)

    fig_perf = None
    portfolio_cum_return = None
    benchmark_cum_return = None
    excess_vs_benchmark = None

    if not portfolio_cum.empty:
        fig_perf = go.Figure()
        fig_perf.add_scatter(x=portfolio_cum.index, y=portfolio_cum, name="Portfolio")

        portfolio_last_x = portfolio_cum.index[-1]
        portfolio_last_y = portfolio_cum.iloc[-1]
        portfolio_cum_return = float(portfolio_last_y - 1)

        fig_perf.add_annotation(
            x=portfolio_last_x,
            y=portfolio_last_y,
            text=f"Portfolio: {portfolio_cum_return:.2%}",
            showarrow=True,
            arrowhead=2,
            ax=20,
            ay=-20,
        )

        if not benchmark_cum.empty:
            fig_perf.add_scatter(x=benchmark_cum.index, y=benchmark_cum, name="VOO")

            benchmark_last_x = benchmark_cum.index[-1]
            benchmark_last_y = benchmark_cum.iloc[-1]
            benchmark_cum_return = float(benchmark_last_y - 1)
            excess_vs_benchmark = float(portfolio_cum_return - benchmark_cum_return)

            fig_perf.add_annotation(
                x=benchmark_last_x,
                y=benchmark_last_y,
                text=f"VOO: {benchmark_cum_return:.2%}",
                showarrow=True,
                arrowhead=2,
                ax=20,
                ay=20,
            )

        fig_perf.update_layout(
            paper_bgcolor="#0b0f14",
            plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"),
            height=400,
            margin=dict(t=20, b=20, l=20, r=20),
        )

    frontier = simulate_constrained_efficient_frontier(
        asset_returns=asset_returns,
        asset_names=asset_returns.columns.tolist() if not asset_returns.empty else [],
        constraints=constraints,
        risk_free_rate=risk_free_rate,
        n_portfolios=N_SIMULATIONS,
    )

    max_sharpe_row = None
    min_vol_row = None
    usable = []
    fig_frontier = None
    current_return = 0.0
    current_vol = 0.0
    current_sharpe = 0.0

    if not frontier.empty:
        mean_returns = asset_returns.mean() * 252
        cov_matrix = asset_returns.cov() * 252
        usable = asset_returns.columns.tolist()

        current_weights = (
            df.set_index("Ticker").loc[usable, "Weight"] /
            max(df.set_index("Ticker").loc[usable, "Weight"].sum(), 1e-12)
        ).values

        current_return = float(current_weights @ mean_returns.values)
        current_vol = float(np.sqrt(current_weights @ cov_matrix.values @ current_weights.T))
        current_sharpe = float((current_return - risk_free_rate) / current_vol) if current_vol > 0 else 0.0

        max_sharpe_row = frontier.loc[frontier["Sharpe"].idxmax()]
        min_vol_row = frontier.loc[frontier["Volatility"].idxmin()]

        max_x = max(
            frontier["Volatility"].max(),
            current_vol,
            float(max_sharpe_row["Volatility"]),
            float(min_vol_row["Volatility"]),
        ) * 1.1

        cml_x = np.linspace(0, max_x, 100)
        cml_y = risk_free_rate + float(max_sharpe_row["Sharpe"]) * cml_x

        fig_frontier = go.Figure()
        fig_frontier.add_trace(
            go.Scatter(
                x=frontier["Volatility"],
                y=frontier["Return"],
                mode="markers",
                marker=dict(
                    size=5,
                    color=frontier["Sharpe"],
                    colorscale="Viridis",
                    showscale=True,
                    colorbar=dict(title="Sharpe"),
                ),
                name="Simulated Portfolios",
                hovertemplate="Volatility: %{x:.2%}<br>Expected Return: %{y:.2%}<br>Sharpe: %{marker.color:.2f}<extra></extra>",
            )
        )
        fig_frontier.add_trace(
            go.Scatter(
                x=cml_x,
                y=cml_y,
                mode="lines",
                name="Capital Market Line",
            )
        )
        fig_frontier.add_trace(
            go.Scatter(
                x=[current_vol],
                y=[current_return],
                mode="markers+text",
                text=["Current"],
                textposition="top center",
                marker=dict(size=12, symbol="x"),
                name="Current Portfolio",
            )
        )
        fig_frontier.add_trace(
            go.Scatter(
                x=[max_sharpe_row["Volatility"]],
                y=[max_sharpe_row["Return"]],
                mode="markers+text",
                text=["Max Sharpe"],
                textposition="top center",
                marker=dict(size=12, symbol="diamond"),
                name="Max Sharpe",
            )
        )
        fig_frontier.add_trace(
            go.Scatter(
                x=[min_vol_row["Volatility"]],
                y=[min_vol_row["Return"]],
                mode="markers+text",
                text=["Min Vol"],
                textposition="bottom center",
                marker=dict(size=12, symbol="circle"),
                name="Min Volatility",
            )
        )
        fig_frontier.update_layout(
            xaxis_title="Volatility",
            yaxis_title="Expected Return",
            paper_bgcolor="#0b0f14",
            plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"),
            height=430,
            margin=dict(t=20, b=20, l=20, r=20),
        )

    stress_df, current_total_value, stressed_total_value = build_stress_test_table(df, stress_shocks)
    stress_pnl = stressed_total_value - current_total_value
    stress_return = (stressed_total_value / current_total_value - 1) if current_total_value > 0 else 0.0

    fig_stress = go.Figure()
    fig_stress.add_bar(x=stress_df["Ticker"], y=stress_df["Current Value"], name="Current Value")
    fig_stress.add_bar(x=stress_df["Ticker"], y=stress_df["Stressed Value"], name="Stressed Value")
    fig_stress.update_layout(
        barmode="group",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=380,
        margin=dict(t=20, b=20, l=20, r=20),
    )

    rolling_df = compute_rolling_metrics(portfolio_returns, benchmark_returns, risk_free_rate, rolling_window)

    return {
        "mode": mode,
        "authenticated": authenticated,
        "base_currency": base_currency,
        "profile": profile,
        "tc_model": tc_model,
        "positions_sheet_available": positions_sheet_available,
        "positions_sheet_error": positions_sheet_error,
        "portfolio_data": portfolio_data,
        "private_portfolio": private_portfolio,
        "updated_portfolio": updated_portfolio,
        "prefix": prefix,
        "df": df,
        "display_df": display_df,
        "total_value": total_value,
        "fig_pie": fig_pie,
        "fig_bar": fig_bar,
        "portfolio_returns": portfolio_returns,
        "asset_returns": asset_returns,
        "benchmark_returns": benchmark_returns,
        "total_return": total_return,
        "volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "alpha": alpha,
        "beta": beta,
        "tracking_error": tracking_error,
        "information_ratio": information_ratio,
        "fig_perf": fig_perf,
        "portfolio_cum_return": portfolio_cum_return,
        "benchmark_cum_return": benchmark_cum_return,
        "excess_vs_benchmark": excess_vs_benchmark,
        "constraints": constraints,
        "risk_free_rate": risk_free_rate,
        "fig_frontier": fig_frontier,
        "frontier": frontier,
        "max_sharpe_row": max_sharpe_row,
        "min_vol_row": min_vol_row,
        "usable": usable,
        "current_return": current_return,
        "current_vol": current_vol,
        "current_sharpe": current_sharpe,
        "tc_params": tc_params,
        "stress_df": stress_df,
        "current_total_value": current_total_value,
        "stressed_total_value": stressed_total_value,
        "stress_pnl": stress_pnl,
        "stress_return": stress_return,
        "fig_stress": fig_stress,
        "rolling_df": rolling_df,
    }