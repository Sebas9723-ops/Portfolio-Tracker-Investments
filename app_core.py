from __future__ import annotations

import json
import html
from pathlib import Path
from datetime import date, datetime, timedelta

import gspread
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from google.oauth2.service_account import Credentials
from streamlit.components.v1 import html as components_html

from portfolio import public_portfolio
from utils import get_prices, get_historical_data, get_market_times


DEFAULT_RISK_FREE_RATE = 0.02
N_SIMULATIONS = 4000
SUPPORTED_BASE_CCY = ["USD", "EUR", "GBP", "COP", "CHF", "AUD"]
PUBLIC_DEFAULTS_VERSION = "public_defaults_v12_phase2"
GOOGLE_SHEETS_CACHE_TTL = 300

PROXY_TICKER_MAP = {
    "IWDA.AS": "EUNL.DE",
}

# Tickers that don't follow the standard exchange currency convention.
# Add any ticker here whose actual quote currency differs from its exchange suffix.
TICKER_CURRENCY_OVERRIDE = {
    "IGLN.L": "USD",  # iShares Physical Gold ETC — quoted in USD on LSE, not GBP
}

PRIVATE_POSITIONS_HEADERS = ["Ticker", "Name", "Shares", "AvgCost"]
TRANSACTIONS_HEADERS = ["date", "ticker", "type", "shares", "price", "fees", "notes"]
CASH_BALANCES_HEADERS = ["currency", "amount"]
DIVIDENDS_HEADERS = ["date", "ticker", "amount", "currency", "notes"]

DIVIDEND_META = {
    "VOO": {"yield": 0.015, "months": [3, 6, 9, 12], "frequency": "Quarterly"},
    "SCHD": {"yield": 0.035, "months": [3, 6, 9, 12], "frequency": "Quarterly"},
    "BND": {"yield": 0.032, "months": list(range(1, 13)), "frequency": "Monthly"},
    "GLD": {"yield": 0.0, "months": [], "frequency": "None"},
    "IGLN.L": {"yield": 0.0, "months": [], "frequency": "None"},
    "IWDA.AS": {"yield": 0.0, "months": [], "frequency": "Accumulating"},
    "VWCE.DE": {"yield": 0.0, "months": [], "frequency": "Accumulating"},
    "EUNL.DE": {"yield": 0.0, "months": [], "frequency": "Accumulating"},
}


# =========================
# UI
# =========================
def apply_bloomberg_style():
    # Inject apple-touch-icon via components.html (scripts run; targets parent document head)
    import streamlit.components.v1 as _components
    _ICON_SRC = "data:image/png;base64,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"
    _components.html(
        """<script>
(function() {{
    var src = "data:image/png;base64,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";
    var targets = [];
    try { targets.push(window.parent.document); } catch(e) {}
    try { if (window.top !== window.parent) targets.push(window.top.document); } catch(e) {}
    targets.forEach(function(doc) {
        ['apple-touch-icon', 'apple-touch-icon-precomposed'].forEach(function(rel) {
            var el = doc.querySelector('link[rel="' + rel + '"]') || doc.createElement('link');
            el.rel = rel;
            el.setAttribute('href', src);
            if (!el.parentNode) doc.head.appendChild(el);
        });
        var mf = doc.querySelector('link[rel="manifest"]') || doc.createElement('link');
        mf.rel = 'manifest';
        mf.setAttribute('href', '/app/static/manifest.json');
        if (!mf.parentNode) doc.head.appendChild(mf);
        // Override page title too
        try { doc.title = 'Portafolio Management SA'; } catch(e) {}
    });
})();
</script>""",
        height=0,
    )
    st.markdown(
        """
        <style>
        html, body, [class*="css"] {
            font-family: "IBM Plex Mono", "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", monospace !important;
        }

        .stApp {
            background-color: #0b0f14;
            color: #e6e6e6;
        }

        [data-testid="stAppViewContainer"] {
            background-color: #0b0f14;
        }

        [data-testid="stSidebar"] {
            background: #0f141b;
            border-right: 1px solid #2a313c;
        }

        [data-testid="stHeader"] {
            background: #0b0f14;
        }

        .block-container {
            padding-top: 1.8rem !important;
            padding-left: 1.1rem !important;
            padding-right: 1.1rem !important;
            padding-bottom: 2rem !important;
            max-width: 1500px;
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
        }

        .bb-section {
            background: linear-gradient(180deg, #111821 0%, #0d131a 100%);
            border: 1px solid #2b3340;
            border-left: 4px solid #f3a712;
            border-radius: 6px;
            padding: 0.85rem 1rem 0.9rem 1rem;
            margin: 0.65rem 0 1rem 0;
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
            font-size: 1.35rem !important;
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

        .stTextInput > div > div > input,
        .stNumberInput input,
        .stSelectbox div[data-baseweb="select"] > div,
        .stDateInput input {
            background-color: #0f141b !important;
            color: #f2f2f2 !important;
            border: 1px solid #394250 !important;
            border-radius: 4px !important;
            min-height: 42px !important;
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
                padding-top: 3.2rem !important;
                padding-left: 0.7rem !important;
                padding-right: 0.7rem !important;
            }

            .bb-title {
                font-size: 1.55rem;
            }

            [data-testid="stMetricValue"] {
                font-size: 1.1rem !important;
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
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_title(title: str):
    st.markdown(
        f"""
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
        st.image(logo_path, width=105)

    with c2:
        st.markdown(
            """
            <div style="padding-top:0.35rem;">
                <div style="font-size:1.02rem; font-weight:800; color:#f3a712; text-transform:uppercase; letter-spacing:0.6px;">
                    Private Portfolio
                </div>
                <div style="font-size:0.82rem; color:#cbd5df; margin-top:0.2rem;">
                    Portfolio Management SA
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
    sheets_text = "Sheets OK" if sheets_ok else "Sheets Off"
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
            <span><b>Base Ccy:</b> {base_currency}</span>
            <span><b>Profile:</b> {profile}</span>
            <span><b>TC Model:</b> {tc_model}</span>
            <span><b>Private Sync:</b> <span style="color:{sheets_color}; font-weight:800;">{sheets_text}</span></span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_market_clocks():
    from streamlit.components.v1 import html as components_html

    components_html(
        """
        <style>
            body {
                margin: 0;
                background: transparent;
                font-family: "IBM Plex Mono", monospace;
            }

            .pm-clock-wrapper {
                border: 1px solid #2b3340;
                border-left: 4px solid #f3a712;
                border-radius: 6px;
                padding: 12px;
                background: #111821;
                width: 100%;
                box-sizing: border-box;
            }

            .pm-clock-title {
                color: #f3a712;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-bottom: 10px;
                font-size: 15px;
            }

            .pm-clock-grid {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 10px;
                width: 100%;
            }

            .pm-clock-card {
                background: #0f141b;
                border: 1px solid #2d3642;
                border-radius: 6px;
                padding: 10px;
                min-height: 94px;
                box-sizing: border-box;
                overflow: hidden;
            }

            .pm-clock-name {
                color: #f3a712;
                font-weight: 800;
                font-size: 13px;
                text-transform: uppercase;
                line-height: 1.1;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }

            .pm-clock-exchange {
                color: #9fb0c3;
                font-size: 11px;
                margin-top: 2px;
                line-height: 1.05;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }

            .pm-clock-time {
                color: #f8f8f8;
                font-size: 18px;
                font-weight: 800;
                margin-top: 8px;
                line-height: 1.05;
                white-space: nowrap;
            }

            .pm-clock-date {
                color: #7fb3ff;
                font-size: 11px;
                margin-top: 4px;
                line-height: 1.05;
                white-space: nowrap;
            }

            @media (max-width: 900px) {
                .pm-clock-grid {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                    gap: 8px;
                }

                .pm-clock-card {
                    padding: 8px 10px;
                    min-height: 82px;
                }

                .pm-clock-name {
                    font-size: 12px;
                }

                .pm-clock-exchange {
                    font-size: 10px;
                }

                .pm-clock-time {
                    font-size: 16px;
                    margin-top: 6px;
                }

                .pm-clock-date {
                    font-size: 10px;
                }
            }

            @media (max-width: 320px) {
                .pm-clock-grid {
                    grid-template-columns: 1fr;
                }
            }
        </style>

        <div class="pm-clock-wrapper">
            <div class="pm-clock-title">Live Market Clocks</div>
            <div class="pm-clock-grid" id="pm-clock-grid"></div>
        </div>

        <script>
            const markets = [
                { name: "New York", exchange: "NYSE / Nasdaq", tz: "America/New_York" },
                { name: "London", exchange: "LSE", tz: "Europe/London" },
                { name: "Frankfurt", exchange: "Xetra", tz: "Europe/Berlin" },
                { name: "Zurich", exchange: "SIX", tz: "Europe/Zurich" },
                { name: "Tokyo", exchange: "TSE", tz: "Asia/Tokyo" },
                { name: "Shanghai", exchange: "SSE", tz: "Asia/Shanghai" },
                { name: "Singapore", exchange: "SGX", tz: "Asia/Singapore" },
                { name: "Bogotá", exchange: "BVC", tz: "America/Bogota" },
                { name: "Sydney", exchange: "ASX", tz: "Australia/Sydney" }
            ];

            function formatClock(tz) {
                const now = new Date();

                const time = new Intl.DateTimeFormat("en-GB", {
                    timeZone: tz,
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                    hour12: false
                }).format(now);

                const date = new Intl.DateTimeFormat("en-GB", {
                    timeZone: tz,
                    weekday: "short",
                    day: "2-digit",
                    month: "short"
                }).format(now);

                return { time, date };
            }

            function renderClocks() {
                const container = document.getElementById("pm-clock-grid");
                if (!container) return;

                container.innerHTML = markets.map(m => {
                    const clock = formatClock(m.tz);
                    return `
                        <div class="pm-clock-card">
                            <div class="pm-clock-name">${m.name}</div>
                            <div class="pm-clock-exchange">${m.exchange}</div>
                            <div class="pm-clock-time">${clock.time}</div>
                            <div class="pm-clock-date">${clock.date}</div>
                        </div>
                    `;
                }).join("");
            }

            renderClocks();
            setInterval(renderClocks, 1000);
        </script>
        """,
        height=495,
    )

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
    )
    expected_return = expected_return_pct / 100.0
    st.caption(f"Selected expected annual return: {expected_return_pct:.1f}%")

    monthly_contribution = st.number_input(
        f"Monthly Contribution ({base_currency})",
        min_value=0.0,
        value=0.0,
        step=100.0,
    )

    scenario_spread_pct = st.slider(
        "Scenario Spread (%)",
        min_value=0.0,
        max_value=10.0,
        value=3.0,
        step=0.1,
        format="%.1f",
    )
    scenario_spread = scenario_spread_pct / 100.0

    conservative_return = max(expected_return - scenario_spread, -0.95)
    optimistic_return = expected_return + scenario_spread

    conservative_df = build_projection_series(total_value, conservative_return, horizon_years, monthly_contribution)
    base_df = build_projection_series(total_value, expected_return, horizon_years, monthly_contribution)
    optimistic_df = build_projection_series(total_value, optimistic_return, horizon_years, monthly_contribution)

    fig_projection = go.Figure()
    fig_projection.add_scatter(x=conservative_df["Year"], y=conservative_df["Value"], name=f"Conservative ({conservative_return:.1%})", mode="lines")
    fig_projection.add_scatter(x=base_df["Year"], y=base_df["Value"], name=f"Base ({expected_return:.1%})", mode="lines")
    fig_projection.add_scatter(x=optimistic_df["Year"], y=optimistic_df["Value"], name=f"Optimistic ({optimistic_return:.1%})", mode="lines")
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
    info_metric(c1, "Conservative Final Value", f"{base_currency} {conservative_df['Value'].iloc[-1]:,.2f}", "Projected final value in the conservative scenario.")
    info_metric(c2, "Base Final Value", f"{base_currency} {base_df['Value'].iloc[-1]:,.2f}", "Projected final value in the base scenario.")
    info_metric(c3, "Optimistic Final Value", f"{base_currency} {optimistic_df['Value'].iloc[-1]:,.2f}", "Projected final value in the optimistic scenario.")


# =========================
# SHEETS
# =========================
def _get_gcp_cfg():
    try:
        gcp_cfg = dict(st.secrets["gcp_service_account"])
    except Exception as e:
        raise RuntimeError("Missing [gcp_service_account] in Streamlit secrets.") from e

    required_keys = ["type", "project_id", "private_key", "client_email", "token_uri"]
    missing = [k for k in required_keys if k not in gcp_cfg or not str(gcp_cfg[k]).strip()]
    if missing:
        raise RuntimeError(f"Missing keys in [gcp_service_account]: {', '.join(missing)}")

    private_key = str(gcp_cfg["private_key"])
    if "\\n" in private_key:
        gcp_cfg["private_key"] = private_key.replace("\\n", "\n")

    return gcp_cfg


def _get_sheets_cfg():
    try:
        return dict(st.secrets["sheets"])
    except Exception as e:
        raise RuntimeError("Missing [sheets] in Streamlit secrets.") from e


def _get_private_positions_sheet_locator():
    sheets_cfg = _get_sheets_cfg()

    sheet_id = str(sheets_cfg.get("private_positions_sheet_id", "")).strip()
    sheet_url = str(sheets_cfg.get("private_positions_sheet_url", "")).strip()

    if not sheet_id and not sheet_url:
        raise RuntimeError("Missing 'private_positions_sheet_id' or 'private_positions_sheet_url' in [sheets].")

    return sheet_id, sheet_url


def get_private_positions_sheet_id():
    sheet_id, sheet_url = _get_private_positions_sheet_locator()

    if sheet_id:
        return sheet_id

    if "/d/" not in sheet_url:
        raise RuntimeError("Invalid Google Sheets URL in [sheets].")

    return sheet_url.split("/d/")[1].split("/")[0]


def _get_private_positions_worksheet_name():
    sheets_cfg = _get_sheets_cfg()
    return str(sheets_cfg.get("private_positions_worksheet", "private_positions")).strip()


@st.cache_resource(show_spinner=False)
def _get_gspread_client_cached():
    gcp_cfg = _get_gcp_cfg()

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = Credentials.from_service_account_info(gcp_cfg, scopes=scopes)
    return gspread.authorize(creds)


@st.cache_resource(show_spinner=False)
def _get_spreadsheet_cached(sheet_id: str, sheet_url: str):
    client = _get_gspread_client_cached()

    if sheet_id:
        return client.open_by_key(sheet_id)
    return client.open_by_url(sheet_url)


@st.cache_data(ttl=GOOGLE_SHEETS_CACHE_TTL, show_spinner=False)
def _get_worksheet_header_cached(sheet_id: str, sheet_url: str, worksheet_name: str):
    spreadsheet = _get_spreadsheet_cached(sheet_id, sheet_url)
    ws = spreadsheet.worksheet(worksheet_name)
    return ws.row_values(1)


@st.cache_data(ttl=GOOGLE_SHEETS_CACHE_TTL, show_spinner=False)
def _get_worksheet_records_cached(sheet_id: str, sheet_url: str, worksheet_name: str):
    spreadsheet = _get_spreadsheet_cached(sheet_id, sheet_url)
    ws = spreadsheet.worksheet(worksheet_name)
    return ws.get_all_records(value_render_option="UNFORMATTED_VALUE")


@st.cache_data(ttl=GOOGLE_SHEETS_CACHE_TTL, show_spinner=False)
def _get_worksheet_values_cached(sheet_id: str, sheet_url: str, worksheet_name: str):
    spreadsheet = _get_spreadsheet_cached(sheet_id, sheet_url)
    ws = spreadsheet.worksheet(worksheet_name)
    return ws.get_all_values()


def _clear_google_sheets_cache():
    _get_worksheet_header_cached.clear()
    _get_worksheet_records_cached.clear()
    _get_worksheet_values_cached.clear()


def _get_spreadsheet():
    sheet_id, sheet_url = _get_private_positions_sheet_locator()
    return _get_spreadsheet_cached(sheet_id, sheet_url)


def _connect_named_worksheet(worksheet_name, headers, default_rows=None):
    sheet_id, sheet_url = _get_private_positions_sheet_locator()
    spreadsheet = _get_spreadsheet_cached(sheet_id, sheet_url)

    created = False
    try:
        ws = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=max(len(headers), 5))
        created = True

    current_header = []
    if not created:
        try:
            current_header = _get_worksheet_header_cached(sheet_id, sheet_url, worksheet_name)
        except Exception:
            current_header = headers

    if created or current_header != headers:
        ws.clear()
        rows = [headers]
        if default_rows:
            rows.extend(default_rows)
        ws.update(range_name="A1", values=rows)
        _clear_google_sheets_cache()

    return ws


def connect_private_positions_worksheet():
    worksheet_name = _get_private_positions_worksheet_name()
    return _connect_named_worksheet(worksheet_name, PRIVATE_POSITIONS_HEADERS)


def connect_transactions_worksheet():
    return _connect_named_worksheet("transactions", TRANSACTIONS_HEADERS)


def connect_cash_balances_worksheet():
    default_rows = [[ccy, 0.0] for ccy in SUPPORTED_BASE_CCY]
    return _connect_named_worksheet("cash_balances", CASH_BALANCES_HEADERS, default_rows=default_rows)


def connect_dividends_worksheet():
    return _connect_named_worksheet("dividends_received", DIVIDENDS_HEADERS)


def load_private_positions_from_sheets():
    worksheet_name = _get_private_positions_worksheet_name()
    sheet_id, sheet_url = _get_private_positions_sheet_locator()

    try:
        connect_private_positions_worksheet()
        records = _get_worksheet_records_cached(sheet_id, sheet_url, worksheet_name)
    except Exception:
        return {}

    positions = {}
    for row in records:
        ticker = str(row.get("Ticker", "")).strip().upper()
        name = str(row.get("Name", "")).strip()
        shares = row.get("Shares", 0)
        avg_cost_raw = row.get("AvgCost", None)

        if ticker and name:
            try:
                entry = {
                    "name": name,
                    "shares": float(shares),
                    "base_shares": float(shares),
                }
                if avg_cost_raw not in (None, "", "0", 0):
                    try:
                        avg_cost = float(avg_cost_raw)
                        if avg_cost > 0:
                            entry["avg_cost"] = avg_cost
                    except Exception:
                        pass
                positions[ticker] = entry
            except Exception:
                continue

    return positions


def save_private_positions_to_sheets(positions: dict):
    ws = connect_private_positions_worksheet()

    rows = [PRIVATE_POSITIONS_HEADERS]
    for ticker in sorted(positions.keys()):
        meta = positions[ticker]
        avg_cost = float(meta.get("avg_cost", 0.0))
        rows.append([ticker, meta["name"], float(meta["shares"]), avg_cost])

    ws.clear()
    ws.update(range_name="A1", values=rows)
    _clear_google_sheets_cache()


def load_transactions_from_sheets():
    sheet_id, sheet_url = _get_private_positions_sheet_locator()

    try:
        connect_transactions_worksheet()
        records = _get_worksheet_records_cached(sheet_id, sheet_url, "transactions")
    except Exception:
        return pd.DataFrame(columns=TRANSACTIONS_HEADERS)

    if not records:
        return pd.DataFrame(columns=TRANSACTIONS_HEADERS)

    df = pd.DataFrame(records)
    df.columns = [str(c).strip().lower() for c in df.columns]

    for col in TRANSACTIONS_HEADERS:
        if col not in df.columns:
            df[col] = np.nan

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["type"] = df["type"].astype(str).str.strip().str.upper()
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce").fillna(0.0)
    df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0.0)
    df["fees"] = pd.to_numeric(df["fees"], errors="coerce").fillna(0.0)
    df["notes"] = df["notes"].fillna("").astype(str)

    df = df.dropna(subset=["date"])
    df = df[df["ticker"] != ""]
    df = df[df["type"].isin(["BUY", "SELL"])]
    df = df.sort_values(["date"]).reset_index(drop=True)

    return df[TRANSACTIONS_HEADERS]


def append_transaction_to_sheets(tx: dict):
    ws = connect_transactions_worksheet()
    row = [
        str(tx["date"]),
        str(tx["ticker"]).upper().strip(),
        str(tx["type"]).upper().strip(),
        float(tx["shares"]),
        float(tx["price"]),
        float(tx.get("fees", 0.0)),
        str(tx.get("notes", "")).strip(),
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")
    _clear_google_sheets_cache()


def load_cash_balances_from_sheets():
    sheet_id, sheet_url = _get_private_positions_sheet_locator()

    try:
        connect_cash_balances_worksheet()
        records = _get_worksheet_records_cached(sheet_id, sheet_url, "cash_balances")
    except Exception:
        return pd.DataFrame(
            {
                "currency": SUPPORTED_BASE_CCY,
                "amount": [0.0] * len(SUPPORTED_BASE_CCY),
            }
        )

    if not records:
        return pd.DataFrame(
            {
                "currency": SUPPORTED_BASE_CCY,
                "amount": [0.0] * len(SUPPORTED_BASE_CCY),
            }
        )

    df = pd.DataFrame(records)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "currency" not in df.columns:
        df["currency"] = ""
    if "amount" not in df.columns:
        df["amount"] = 0.0

    df["currency"] = df["currency"].astype(str).str.strip().str.upper()
    # Normalize amount: Sheets may return "2,58" (locale comma) instead of "2.58"
    df["amount"] = pd.to_numeric(
        df["amount"].astype(str).str.replace(",", ".", regex=False),
        errors="coerce",
    ).fillna(0.0)
    df = df[df["currency"] != ""].copy()

    existing = set(df["currency"].tolist())
    missing = [ccy for ccy in SUPPORTED_BASE_CCY if ccy not in existing]
    if missing:
        add_df = pd.DataFrame({"currency": missing, "amount": [0.0] * len(missing)})
        df = pd.concat([df, add_df], ignore_index=True)

    df = df.drop_duplicates(subset=["currency"], keep="last").reset_index(drop=True)
    return df


def save_cash_balances_to_sheets(cash_df: pd.DataFrame):
    ws = connect_cash_balances_worksheet()

    df = cash_df.copy()
    df["currency"] = df["currency"].astype(str).str.strip().str.upper()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df = df[df["currency"] != ""].drop_duplicates(subset=["currency"], keep="last")

    preferred_order = {ccy: i for i, ccy in enumerate(SUPPORTED_BASE_CCY)}
    df["__sort"] = df["currency"].map(lambda x: preferred_order.get(x, 999))
    df = df.sort_values(["__sort", "currency"]).drop(columns="__sort").reset_index(drop=True)

    rows = [CASH_BALANCES_HEADERS]
    for _, row in df.iterrows():
        rows.append([row["currency"], float(row["amount"])])

    ws.clear()
    ws.update(range_name="A1", values=rows)
    _clear_google_sheets_cache()


def adjust_cash_balance(currency: str, delta: float):
    cash_df = load_cash_balances_from_sheets()
    currency = str(currency).upper().strip()

    if currency in cash_df["currency"].values:
        cash_df.loc[cash_df["currency"] == currency, "amount"] += float(delta)
    else:
        cash_df = pd.concat(
            [cash_df, pd.DataFrame({"currency": [currency], "amount": [float(delta)]})],
            ignore_index=True,
        )

    save_cash_balances_to_sheets(cash_df)


def load_dividends_from_sheets():
    sheet_id, sheet_url = _get_private_positions_sheet_locator()

    try:
        connect_dividends_worksheet()
        records = _get_worksheet_records_cached(sheet_id, sheet_url, "dividends_received")
    except Exception:
        return pd.DataFrame(columns=DIVIDENDS_HEADERS)

    if not records:
        return pd.DataFrame(columns=DIVIDENDS_HEADERS)

    df = pd.DataFrame(records)
    df.columns = [str(c).strip().lower() for c in df.columns]

    for col in DIVIDENDS_HEADERS:
        if col not in df.columns:
            df[col] = np.nan

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["currency"] = df["currency"].astype(str).str.strip().str.upper()
    df["notes"] = df["notes"].fillna("").astype(str)

    df = df.dropna(subset=["date"])
    df = df[df["ticker"] != ""].sort_values("date").reset_index(drop=True)
    return df[DIVIDENDS_HEADERS]


def append_dividend_to_sheets(div_tx: dict):
    ws = connect_dividends_worksheet()
    row = [
        str(div_tx["date"]),
        str(div_tx["ticker"]).upper().strip(),
        float(div_tx["amount"]),
        str(div_tx["currency"]).upper().strip(),
        str(div_tx.get("notes", "")).strip(),
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")
    _clear_google_sheets_cache()


# =========================
# PORTFOLIO
# =========================
def load_private_portfolio():
    p = st.secrets["private_portfolio"]
    return {
        "SCHD": {"name": "Dividend ETF", "shares": float(p["SCHD"]), "base_shares": float(p["SCHD"])},
        "VOO": {"name": "S&P 500", "shares": float(p["VOO"]), "base_shares": float(p["VOO"])},
        "VWCE.DE": {"name": "All World", "shares": float(p["VWCE_DE"]), "base_shares": float(p["VWCE_DE"])},
        "IGLN.L": {"name": "Gold", "shares": float(p["IGLN_L"]), "base_shares": float(p["IGLN_L"])},
        "BND": {"name": "Bonds", "shares": float(p["BND"]), "base_shares": float(p["BND"])},
    }


def get_manage_password():
    auth_section = dict(st.secrets["auth"])
    return auth_section.get("manage_password", auth_section["password"])


def merge_private_portfolios(base_private: dict, custom_private: dict):
    merged = dict(base_private)
    for ticker, meta in custom_private.items():
        if ticker in merged:
            merged[ticker]["shares"] = meta["shares"]
            merged[ticker]["base_shares"] = meta.get("base_shares", meta["shares"])
            merged[ticker]["name"] = meta["name"]
            if "avg_cost" in meta:
                merged[ticker]["avg_cost"] = meta["avg_cost"]
        else:
            merged[ticker] = dict(meta)
    return merged


def build_transaction_positions(transactions_df: pd.DataFrame, name_map: dict, base_shares_map: dict):
    state = {}

    if transactions_df is None or transactions_df.empty:
        return {}, {}

    for _, row in transactions_df.sort_values("date").iterrows():
        ticker = str(row["ticker"]).upper().strip()
        tx_type = str(row["type"]).upper().strip()
        shares = float(row["shares"])
        price = float(row["price"])
        fees = float(row.get("fees", 0.0))

        if ticker not in state:
            state[ticker] = {
                "shares": 0.0,
                "invested_capital_native": 0.0,
                "realized_pnl_native": 0.0,
                "tx_count": 0,
            }

        s = state[ticker]
        s["tx_count"] += 1

        if tx_type == "BUY":
            total_cost = shares * price + fees
            s["shares"] += shares
            s["invested_capital_native"] += total_cost

        elif tx_type == "SELL":
            current_shares = float(s["shares"])
            avg_cost = (float(s["invested_capital_native"]) / current_shares) if current_shares > 0 else price
            proceeds = shares * price - fees
            cost_removed = min(shares, current_shares) * avg_cost

            s["realized_pnl_native"] += proceeds - cost_removed
            s["invested_capital_native"] = max(s["invested_capital_native"] - cost_removed, 0.0)
            s["shares"] = max(current_shares - shares, 0.0)

    positions = {}
    stats = {}

    for ticker, s in state.items():
        shares = float(s["shares"])
        invested = float(s["invested_capital_native"])
        avg_cost = invested / shares if shares > 0 else 0.0

        stats[ticker] = {
            "name": name_map.get(ticker, ticker),
            "shares": shares,
            "avg_cost_native": avg_cost,
            "invested_capital_native": invested,
            "realized_pnl_native": float(s["realized_pnl_native"]),
            "tx_count": int(s["tx_count"]),
            "tracked": True,
        }

        positions[ticker] = {
            "name": name_map.get(ticker, ticker),
            "shares": shares,
            "base_shares": base_shares_map.get(ticker, shares),
        }

    return positions, stats


def build_private_portfolio_for_save(portfolio_data: dict, prefix: str):
    saved = {}

    for ticker, meta in portfolio_data.items():
        widget_key = f"{prefix}_shares_{ticker}"
        shares_val = float(st.session_state.get(widget_key, meta["shares"]))
        saved[ticker] = {
            "name": meta["name"],
            "shares": shares_val,
        }

    return saved


# =========================
# SIDEBAR
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


def build_current_portfolio(portfolio_data: dict, prefix: str, mode: str, disable_inputs: bool = False):
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
            disabled=disable_inputs,
        )

        updated[ticker] = {
            "name": meta["name"],
            "shares": float(st.session_state[widget_key]),
            "base_shares": float(meta.get("base_shares", meta["shares"])),
            "target_weight": meta.get("target_weight"),
        }

    return updated


# =========================
# FX / PRICES
# =========================
def asset_currency(ticker: str) -> str:
    ticker = str(ticker).upper().strip()
    if ticker in TICKER_CURRENCY_OVERRIDE:
        return TICKER_CURRENCY_OVERRIDE[ticker]
    if ticker.endswith(".DE") or ticker.endswith(".AS"):
        return "EUR"
    if ticker.endswith(".L"):
        return "GBP"
    if ticker.endswith(".AX"):
        return "AUD"
    return "USD"


def asset_market_group(ticker: str) -> str:
    ticker = str(ticker).upper().strip()
    if ticker.endswith(".L"):
        return "UK"
    if ticker.endswith(".AX"):
        return "Australia"
    if "." in ticker:
        return "Europe"
    return "US"


@st.cache_data(ttl=3600, show_spinner=False)
def build_fx_data(tickers: list[str], base_currency: str, period: str = "2y"):
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


@st.cache_data(ttl=3600, show_spinner=False)
def load_market_data_with_proxies(tickers: list[str], period: str = "2y"):
    source_tickers = []
    seen = set()

    for ticker in tickers:
        source = PROXY_TICKER_MAP.get(ticker, ticker)
        if source not in seen:
            source_tickers.append(source)
            seen.add(source)

    raw_prices = get_prices(source_tickers)
    raw_hist = get_historical_data(source_tickers, period=period)

    mapped_prices = {}
    mapped_hist = pd.DataFrame()

    if raw_hist is not None and not raw_hist.empty:
        mapped_hist = pd.DataFrame(index=raw_hist.index)

    for ticker in tickers:
        source = PROXY_TICKER_MAP.get(ticker, ticker)

        price_val = raw_prices.get(source)
        if isinstance(price_val, (int, float)) and pd.notna(price_val):
            mapped_prices[ticker] = float(price_val)

        if raw_hist is not None and not raw_hist.empty and source in raw_hist.columns:
            mapped_hist[ticker] = pd.to_numeric(raw_hist[source], errors="coerce")

    return mapped_prices, mapped_hist


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


@st.cache_data(ttl=3600, show_spinner=False)
def convert_historical_to_base(asset_hist_native: pd.DataFrame, tickers: list[str], base_currency: str, fx_hist: pd.DataFrame):
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

        fx_series = pd.to_numeric(fx_series, errors="coerce").dropna()
        if fx_series.empty:
            missing_fx.append(f"{from_ccy}->{base_currency}")
            continue

        aligned = (
            pd.concat([native_series.rename("asset"), fx_series.rename("fx")], axis=1)
            .sort_index()
            .ffill()
            .dropna()
        )

        if not aligned.empty:
            converted[ticker] = (aligned["asset"] * aligned["fx"]).rename(ticker)

    if not converted:
        return pd.DataFrame(), sorted(set(missing_fx))

    out = pd.concat(converted.values(), axis=1)
    out.columns = list(converted.keys())
    out = out.sort_index().ffill().dropna(how="all")

    return out, sorted(set(missing_fx))


@st.cache_data(ttl=3600, show_spinner=False)
def backfill_missing_proxy_history(
    historical_base: pd.DataFrame,
    tickers: list[str],
    base_currency: str,
    fx_hist: pd.DataFrame,
    period: str = "2y",
):
    out = historical_base.copy()

    for ticker in tickers:
        already_ok = False
        if ticker in out.columns:
            s = pd.to_numeric(out[ticker], errors="coerce").dropna()
            if not s.empty:
                already_ok = True

        if already_ok:
            continue

        proxy = PROXY_TICKER_MAP.get(ticker)
        if not proxy:
            continue

        proxy_hist = get_historical_data([proxy], period=period)
        if proxy_hist is None or proxy_hist.empty or proxy not in proxy_hist.columns:
            continue

        native_series = pd.to_numeric(proxy_hist[proxy], errors="coerce").dropna()
        if native_series.empty:
            continue

        from_ccy = asset_currency(proxy)

        if from_ccy == base_currency:
            out[ticker] = native_series
            continue

        fx_series = get_fx_series(from_ccy, base_currency, fx_hist)
        if fx_series is None:
            continue

        fx_series = pd.to_numeric(fx_series, errors="coerce").dropna()
        if fx_series.empty:
            continue

        aligned = (
            pd.concat([native_series.rename("asset"), fx_series.rename("fx")], axis=1)
            .sort_index()
            .ffill()
            .dropna()
        )

        if not aligned.empty:
            out[ticker] = aligned["asset"] * aligned["fx"]

    return out


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
# DATAFRAMES
# =========================
def build_cash_display_df(cash_balances_df: pd.DataFrame, base_currency: str, fx_prices: dict, fx_hist: pd.DataFrame):
    rows = []

    for _, row in cash_balances_df.iterrows():
        ccy = str(row["currency"]).upper().strip()
        amount = float(row["amount"])
        fx_rate = get_fx_rate_current(ccy, base_currency, fx_prices, fx_hist)
        if pd.isna(fx_rate):
            fx_rate = 0.0
        rows.append(
            {
                "Currency": ccy,
                "Amount": round(amount, 2),
                "FX Rate": round(fx_rate, 6),
                f"Value ({base_currency})": round(amount * fx_rate, 2),
            }
        )

    out = pd.DataFrame(rows)
    total_cash_value = float(out[f"Value ({base_currency})"].sum()) if not out.empty else 0.0
    return out, total_cash_value


def build_portfolio_df(
    updated_portfolio: dict,
    live_prices_native: dict,
    asset_hist_native: pd.DataFrame,
    fx_prices: dict,
    fx_hist: pd.DataFrame,
    base_currency: str,
    tx_stats_map=None,
):
    rows = []
    total_value = 0.0
    base_total_value = 0.0
    total_invested_base = 0.0
    total_unrealized_base = 0.0
    total_realized_base = 0.0
    any_base_shares_differ = False

    tx_stats_map = tx_stats_map or {}

    for ticker, meta in updated_portfolio.items():
        native_currency = asset_currency(ticker)
        native_price = get_safe_native_price(ticker, live_prices_native, asset_hist_native)
        fx_rate = get_fx_rate_current(native_currency, base_currency, fx_prices, fx_hist)

        if pd.isna(fx_rate):
            fx_rate = 0.0

        price = native_price * fx_rate

        shares = float(meta["shares"])
        base_shares = float(meta.get("base_shares", meta["shares"]))
        if abs(base_shares - shares) > 1e-9:
            any_base_shares_differ = True
        target_weight_override = meta.get("target_weight")

        tx_stat = tx_stats_map.get(ticker)
        manual_avg_cost = meta.get("avg_cost")
        if tx_stat and tx_stat.get("tracked", False):
            avg_cost_native = float(tx_stat["avg_cost_native"])
            invested_native = float(tx_stat["invested_capital_native"])
            realized_native = float(tx_stat["realized_pnl_native"])
            source = "Transactions"
        elif manual_avg_cost and float(manual_avg_cost) > 0:
            avg_cost_native = float(manual_avg_cost)
            invested_native = shares * avg_cost_native
            realized_native = 0.0
            source = "Manual Avg Cost"
        else:
            avg_cost_native = native_price if shares > 0 else 0.0
            invested_native = shares * native_price
            realized_native = 0.0
            source = "Snapshot"

        avg_cost_base = avg_cost_native * fx_rate
        invested_base = invested_native * fx_rate
        realized_base = realized_native * fx_rate

        value = shares * price
        base_value = base_shares * price
        unrealized_base = value - invested_base
        unrealized_pct = (unrealized_base / invested_base) if invested_base > 0 else 0.0

        total_value += value
        base_total_value += base_value
        total_invested_base += invested_base
        total_unrealized_base += unrealized_base
        total_realized_base += realized_base

        rows.append(
            {
                "Ticker": ticker,
                "Name": meta["name"],
                "Source": source,
                "Market": asset_market_group(ticker),
                "Native Currency": native_currency,
                "Shares": round(shares, 4),
                "Native Price": round(native_price, 2),
                "Avg Cost Native": round(avg_cost_native, 4),
                "FX Rate": round(fx_rate, 6),
                "Price": round(price, 2),
                "Avg Cost": round(avg_cost_base, 2),
                "Invested Capital": round(invested_base, 2),
                "Value": round(value, 2),
                "Unrealized PnL": round(unrealized_base, 2),
                "Unrealized PnL %": round(unrealized_pct * 100, 2),
                "Realized PnL": round(realized_base, 2),
                "Base Shares": round(base_shares, 4),
                "Base Value": round(base_value, 2),
                "Target Weight Override": target_weight_override,
            }
        )

    df = pd.DataFrame(rows)

    if total_value > 0:
        df["Weight"] = df["Value"] / total_value
    else:
        df["Weight"] = 0.0

    if "Target Weight Override" in df.columns and df["Target Weight Override"].notna().any():
        df["Target Weight"] = df["Target Weight Override"].fillna(0.0)
        total_tw = df["Target Weight"].sum()
        if total_tw > 0:
            df["Target Weight"] = df["Target Weight"] / total_tw
        else:
            df["Target Weight"] = 0.0
    else:
        # Only use base_shares-derived targets when at least one ticker has
        # base_shares explicitly different from current shares — otherwise
        # Base Value == Value and Target Weight would mirror Current Weight.
        if any_base_shares_differ and base_total_value > 0:
            df["Target Weight"] = df["Base Value"] / base_total_value
        elif len(df) > 0:
            df["Target Weight"] = 1.0 / len(df)
        else:
            df["Target Weight"] = 0.0

    df["Weight %"] = (df["Weight"] * 100).round(2)
    df["Target %"] = (df["Target Weight"] * 100).round(2)
    df["Deviation %"] = ((df["Weight"] - df["Target Weight"]) * 100).round(2)

    totals = {
        "holdings_value": float(total_value),
        "invested_capital": float(total_invested_base),
        "unrealized_pnl": float(total_unrealized_base),
        "realized_pnl": float(total_realized_base),
    }

    return df, total_value, totals


@st.cache_data(ttl=3600, show_spinner=False)
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


@st.cache_data(ttl=3600, show_spinner=False)
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
# DIVIDENDS / CONTRIBUTIONS
# =========================
@st.cache_data(ttl=86400, show_spinner=False)
def build_dividend_insights(
    df: pd.DataFrame,
    dividends_df: pd.DataFrame,
    base_currency: str,
    fx_prices: dict,
    fx_hist: pd.DataFrame,
):
    annual_rows = []
    calendar_rows = []
    estimated_annual_total = 0.0

    today = date.today()
    one_year_out = today + timedelta(days=365)

    for _, row in df.iterrows():
        ticker = row["Ticker"]
        name = row["Name"]
        value = float(row["Value"])
        meta = DIVIDEND_META.get(ticker, {"yield": 0.0, "months": [], "frequency": "None"})

        annual_est = value * float(meta["yield"])
        estimated_annual_total += annual_est

        annual_rows.append(
            {
                "Ticker": ticker,
                "Name": name,
                "Estimated Yield %": round(float(meta["yield"]) * 100, 2),
                "Estimated Annual Dividend": round(annual_est, 2),
                "Frequency": meta["frequency"],
            }
        )

        months = meta.get("months", [])
        if annual_est > 0 and months:
            payments_per_year = len(months)
            payment_amount = annual_est / payments_per_year if payments_per_year > 0 else 0.0

            for offset in range(13):
                candidate = today + timedelta(days=30 * offset)
                if candidate.month in months:
                    pay_date = date(candidate.year, candidate.month, 15)
                    if today <= pay_date <= one_year_out:
                        calendar_rows.append(
                            {
                                "Pay Date": pay_date,
                                "Ticker": ticker,
                                "Name": name,
                                f"Estimated Amount ({base_currency})": round(payment_amount, 2),
                            }
                        )

    annual_df = pd.DataFrame(annual_rows)
    if calendar_rows:
        calendar_df = pd.DataFrame(calendar_rows).drop_duplicates().sort_values("Pay Date").reset_index(drop=True)
    else:
        calendar_df = pd.DataFrame(columns=["Pay Date", "Ticker", "Name", f"Estimated Amount ({base_currency})"])

    collected_df = dividends_df.copy()
    if collected_df.empty:
        collected_display_df = pd.DataFrame(columns=["Date", "Ticker", "Amount", "Currency", f"Amount ({base_currency})", "Notes"])
        return annual_df, calendar_df, collected_display_df, estimated_annual_total, 0.0, 0.0

    amounts_base = []
    for _, row in collected_df.iterrows():
        ccy = str(row["currency"]).upper().strip()
        fx_rate = get_fx_rate_current(ccy, base_currency, fx_prices, fx_hist)
        if pd.isna(fx_rate):
            fx_rate = 0.0
        amounts_base.append(float(row["amount"]) * fx_rate)

    collected_df[f"amount_{base_currency.lower()}"] = amounts_base

    current_year = datetime.today().year
    dividends_ytd = float(collected_df[collected_df["date"].dt.year == current_year][f"amount_{base_currency.lower()}"].sum())
    dividends_total = float(collected_df[f"amount_{base_currency.lower()}"].sum())

    collected_display_df = collected_df.copy()
    collected_display_df["date"] = pd.to_datetime(collected_df["date"]).dt.date
    collected_display_df = collected_display_df.rename(
        columns={
            "date": "Date",
            "ticker": "Ticker",
            "amount": "Amount",
            "currency": "Currency",
            "notes": "Notes",
            f"amount_{base_currency.lower()}": f"Amount ({base_currency})",
        }
    )
    collected_display_df = collected_display_df[["Date", "Ticker", "Amount", "Currency", f"Amount ({base_currency})", "Notes"]]
    collected_display_df = collected_display_df.sort_values("Date", ascending=False).reset_index(drop=True)

    return annual_df, calendar_df, collected_display_df, estimated_annual_total, dividends_ytd, dividends_total


def build_contribution_suggestion(df: pd.DataFrame, contribution_amount: float):
    if contribution_amount <= 0 or df.empty:
        return pd.DataFrame(columns=[
            "Ticker", "Name", "Current Value", "Target Value After Contribution",
            "Suggested Buy Value", "Price", "Suggested Shares"
        ])

    work = df.copy()
    total_after = float(work["Value"].sum()) + float(contribution_amount)

    work["Target Value After Contribution"] = work["Target Weight"] * total_after
    work["Gap"] = work["Target Value After Contribution"] - work["Value"]
    work["Positive Gap"] = work["Gap"].clip(lower=0.0)

    if float(work["Positive Gap"].sum()) <= 0:
        work["Positive Gap"] = work["Target Weight"]

    positive_total = float(work["Positive Gap"].sum())
    if positive_total <= 0:
        work["Suggested Buy Value"] = 0.0
    else:
        work["Suggested Buy Value"] = contribution_amount * work["Positive Gap"] / positive_total

    work["Suggested Shares"] = np.where(
        work["Price"] > 0,
        work["Suggested Buy Value"] / work["Price"],
        0.0,
    )

    out = work[[
        "Ticker",
        "Name",
        "Value",
        "Target Value After Contribution",
        "Suggested Buy Value",
        "Price",
        "Suggested Shares",
    ]].copy()

    out = out.rename(columns={"Value": "Current Value"})
    out = out.sort_values("Suggested Buy Value", ascending=False).reset_index(drop=True)

    for col in ["Current Value", "Target Value After Contribution", "Suggested Buy Value", "Price", "Suggested Shares"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out["Current Value"] = out["Current Value"].round(2)
    out["Target Value After Contribution"] = out["Target Value After Contribution"].round(2)
    out["Suggested Buy Value"] = out["Suggested Buy Value"].round(2)
    out["Price"] = out["Price"].round(2)
    out["Suggested Shares"] = out["Suggested Shares"].round(4)

    return out


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


@st.cache_data(ttl=86400, show_spinner=False)
def simulate_constrained_efficient_frontier(
    asset_returns: pd.DataFrame,
    asset_names: list[str],
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
# REBALANCING / RISK
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
        return {"Commission": 0.0, "Slippage": 0.0, "FX Cost": 0.0, "Total Cost": 0.0}

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
    return {"Commission": commission, "Slippage": slippage, "FX Cost": fx_cost, "Total Cost": total_cost}


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


@st.cache_data(ttl=3600, show_spinner=False)
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
        aligned = pd.concat([portfolio_returns.rename("Portfolio"), benchmark_returns.rename("Benchmark")], axis=1).dropna()
        if not aligned.empty:
            rolling_cov = aligned["Portfolio"].rolling(window).cov(aligned["Benchmark"])
            rolling_var = aligned["Benchmark"].rolling(window).var()
            rolling_beta = rolling_cov / rolling_var.replace(0, np.nan)
            df_roll = df_roll.join(rolling_beta.rename("Rolling Beta"), how="left")

    return df_roll.dropna(how="all")


# =========================
# CONTEXT
# =========================
def build_app_context():
    private_available = True
    positions_sheet_available = True
    positions_sheet_error = ""
    private_portfolio = {}
    private_sheet_positions = {}
    tx_stats_map = {}
    transactions_df = pd.DataFrame(columns=TRANSACTIONS_HEADERS)
    cash_balances_df = pd.DataFrame(columns=CASH_BALANCES_HEADERS)
    dividends_df = pd.DataFrame(columns=DIVIDENDS_HEADERS)

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

        try:
            transactions_df = load_transactions_from_sheets()
        except Exception:
            transactions_df = pd.DataFrame(columns=TRANSACTIONS_HEADERS)

        try:
            cash_balances_df = load_cash_balances_from_sheets()
        except Exception:
            cash_balances_df = pd.DataFrame({"currency": SUPPORTED_BASE_CCY, "amount": [0.0] * len(SUPPORTED_BASE_CCY)})

        try:
            dividends_df = load_dividends_from_sheets()
        except Exception:
            dividends_df = pd.DataFrame(columns=DIVIDENDS_HEADERS)

        snapshot_private = merge_private_portfolios(base_private_portfolio, private_sheet_positions)
        name_map = {t: meta["name"] for t, meta in snapshot_private.items()}
        base_shares_map = {t: meta.get("base_shares", meta["shares"]) for t, meta in snapshot_private.items()}

        tx_positions, tx_stats_map = build_transaction_positions(transactions_df, name_map, base_shares_map)

        private_portfolio = {ticker: dict(meta) for ticker, meta in snapshot_private.items()}
        for ticker, meta in tx_positions.items():
            if ticker in private_portfolio:
                private_portfolio[ticker]["shares"] = meta["shares"]
            else:
                private_portfolio[ticker] = dict(meta)

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

    base_currency = st.sidebar.selectbox("Base Currency", SUPPORTED_BASE_CCY, index=0)

    portfolio_data = get_active_portfolio(mode, authenticated, private_portfolio)
    prefix = get_mode_prefix(mode)

    init_mode_state(portfolio_data, prefix)

    if mode == "Public" and st.session_state.get("public_defaults_version") != PUBLIC_DEFAULTS_VERSION:
        reset_mode_state(portfolio_data, prefix)
        st.session_state["public_defaults_version"] = PUBLIC_DEFAULTS_VERSION

    if st.sidebar.button("Reset Portfolio"):
        reset_mode_state(portfolio_data, prefix)
        st.rerun()

    has_transactions = bool(mode == "Private" and authenticated and not transactions_df.empty)
    if has_transactions:
        st.sidebar.info("Private shares are derived from the Transactions sheet.")

    st.sidebar.header("Portfolio Inputs")
    updated_portfolio = build_current_portfolio(
        portfolio_data=portfolio_data,
        prefix=prefix,
        mode=mode,
        disable_inputs=has_transactions,
    )

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
    tc_model = st.sidebar.selectbox("Model", ["Broker Profile", "Simple Bps", "Manual Override"])

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

    stress_shocks = {"Equities": equity_shock, "Bonds": bonds_shock, "Gold": gold_shock}

    tickers = list(updated_portfolio.keys())

    live_prices_native, asset_hist_native = load_market_data_with_proxies(tickers=tickers, period="2y")

    if asset_hist_native is None or asset_hist_native.empty or asset_hist_native.dropna(how="all").empty:
        st.error("Could not load historical data.")
        st.stop()

    fx_prices, fx_hist, _ = build_fx_data(tickers, base_currency, period="2y")
    historical_base, missing_fx = convert_historical_to_base(asset_hist_native, tickers, base_currency, fx_hist)
    historical_base = backfill_missing_proxy_history(historical_base, tickers, base_currency, fx_hist, period="2y")

    if historical_base.empty or historical_base.dropna(how="all").empty:
        st.error("Could not build base-currency historical series.")
        st.stop()

    missing_hist = []
    for ticker in tickers:
        if ticker not in historical_base.columns:
            missing_hist.append(ticker)
        else:
            s = pd.to_numeric(historical_base[ticker], errors="coerce").dropna()
            if s.empty:
                missing_hist.append(ticker)

    if missing_hist:
        filtered_missing = [t for t in missing_hist if t not in PROXY_TICKER_MAP]
        if filtered_missing:
            st.warning(f"No converted historical data for: {', '.join(filtered_missing)}")

    if missing_fx:
        st.warning(f"Missing FX history for: {', '.join(missing_fx)}")

    df, total_value, pnl_totals = build_portfolio_df(
        updated_portfolio=updated_portfolio,
        live_prices_native=live_prices_native,
        asset_hist_native=asset_hist_native,
        fx_prices=fx_prices,
        fx_hist=fx_hist,
        base_currency=base_currency,
        tx_stats_map=tx_stats_map,
    )

    cash_display_df, cash_total_value = build_cash_display_df(cash_balances_df, base_currency, fx_prices, fx_hist)
    total_portfolio_value = pnl_totals["holdings_value"] + cash_total_value

    display_df = df[
        [
            "Ticker",
            "Name",
            "Source",
            "Market",
            "Native Currency",
            "Shares",
            "Avg Cost",
            "Price",
            "Invested Capital",
            "Value",
            "Unrealized PnL",
            "Unrealized PnL %",
            "Weight %",
            "Target %",
            "Deviation %",
        ]
    ].copy()

    alloc_df = df[df["Value"] > 0][["Name", "Value"]].copy()
    if cash_total_value > 0:
        alloc_df = pd.concat([alloc_df, pd.DataFrame([{"Name": "Cash", "Value": cash_total_value}])], ignore_index=True)

    if not alloc_df.empty:
        fig_pie = px.pie(alloc_df, names="Name", values="Value", hole=0.45)
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
    else:
        fig_pie = go.Figure()
        fig_pie.add_annotation(text="No portfolio value to display", x=0.5, y=0.5, showarrow=False, font=dict(size=18, color="#cbd5df"))

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
        aligned = pd.concat([portfolio_returns.rename("Portfolio"), benchmark_returns.rename("Benchmark")], axis=1).dropna()

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

        if not benchmark_cum.empty:
            fig_perf.add_scatter(x=benchmark_cum.index, y=benchmark_cum, name="VOO")
            benchmark_last_y = benchmark_cum.iloc[-1]
            benchmark_cum_return = float(benchmark_last_y - 1)
            excess_vs_benchmark = float(portfolio_cum_return - benchmark_cum_return)

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
                marker=dict(size=5, color=frontier["Sharpe"], colorscale="Viridis", showscale=True, colorbar=dict(title="Sharpe")),
                name="Simulated Portfolios",
            )
        )
        fig_frontier.add_trace(go.Scatter(x=cml_x, y=cml_y, mode="lines", name="Capital Market Line"))
        fig_frontier.add_trace(go.Scatter(x=[current_vol], y=[current_return], mode="markers+text", text=["Current"], textposition="top center", marker=dict(size=12, symbol="x"), name="Current Portfolio"))
        fig_frontier.add_trace(go.Scatter(x=[max_sharpe_row["Volatility"]], y=[max_sharpe_row["Return"]], mode="markers+text", text=["Max Sharpe"], textposition="top center", marker=dict(size=12, symbol="diamond"), name="Max Sharpe"))
        fig_frontier.add_trace(go.Scatter(x=[min_vol_row["Volatility"]], y=[min_vol_row["Return"]], mode="markers+text", text=["Min Vol"], textposition="bottom center", marker=dict(size=12, symbol="circle"), name="Min Volatility"))
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

    annual_dividend_df, dividend_calendar_df, collected_dividends_df, estimated_annual_dividends, dividends_ytd, dividends_total = build_dividend_insights(
        df=df,
        dividends_df=dividends_df,
        base_currency=base_currency,
        fx_prices=fx_prices,
        fx_hist=fx_hist,
    )

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
        "transactions_df": transactions_df,
        "cash_balances_df": cash_balances_df,
        "cash_display_df": cash_display_df,
        "dividends_df": dividends_df,
        "collected_dividends_df": collected_dividends_df,
        "annual_dividend_df": annual_dividend_df,
        "dividend_calendar_df": dividend_calendar_df,
        "estimated_annual_dividends": estimated_annual_dividends,
        "dividends_ytd": dividends_ytd,
        "dividends_total": dividends_total,
        "has_transactions": has_transactions,
        "holdings_value": pnl_totals["holdings_value"],
        "cash_total_value": cash_total_value,
        "total_portfolio_value": total_portfolio_value,
        "invested_capital": pnl_totals["invested_capital"],
        "unrealized_pnl": pnl_totals["unrealized_pnl"],
        "realized_pnl": pnl_totals["realized_pnl"],
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
        "fx_prices": fx_prices,
        "fx_hist": fx_hist,
    }