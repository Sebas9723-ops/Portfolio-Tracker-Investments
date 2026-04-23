from __future__ import annotations

import html
import json
from pathlib import Path
from datetime import date, datetime, timedelta

import gspread
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from google.oauth2.service_account import Credentials
from portfolio import public_portfolio
from utils import get_prices, get_historical_data, get_market_times


DEFAULT_RISK_FREE_RATE = 0.045  # fallback — overridden at runtime by get_risk_free_rate()
N_SIMULATIONS = 3000


# =========================
# LIVE MARKET CONSTANTS
# =========================

@st.cache_data(ttl=86400, show_spinner=False)
def get_risk_free_rate() -> float:
    """Fetch the current 3-month US T-Bill rate (^IRX) from yfinance.

    Returns annualized rate as a decimal (e.g. 0.045 for 4.5%).
    Falls back to DEFAULT_RISK_FREE_RATE if the feed is unavailable.
    """
    import yfinance as yf
    try:
        hist = yf.Ticker("^IRX").history(period="5d")
        if not hist.empty:
            rate = float(hist["Close"].dropna().iloc[-1]) / 100.0
            if 0.0 < rate < 0.20:
                return round(rate, 4)
    except Exception:
        pass
    return DEFAULT_RISK_FREE_RATE


_YIELD_FALLBACK_MAP: dict[str, float] = {
    "8RMY.DE": 0.0, "EIMI.UK": 0.0, "VOO": 0.0130, "VWCE.DE": 0.0150,
    "IWDA.AS": 0.0150, "AGG": 0.0310,
    "IEF": 0.0280, "TLT": 0.0360, "IGLN.L": 0.0,
    "GLD": 0.0, "IAU": 0.0,
}


@st.cache_data(ttl=86400, show_spinner=False)
def get_live_dividend_yield(ticker: str) -> float:
    """Fetch trailing annual dividend yield for a ticker from yfinance.

    Returns yield as a decimal (e.g. 0.036 for 3.6%).
    Falls back to _YIELD_FALLBACK_MAP, then 0.0 if unavailable.
    """
    import yfinance as yf
    try:
        info = yf.Ticker(ticker).info
        for key in ("trailingAnnualDividendYield", "dividendYield"):
            val = info.get(key)
            if val is not None:
                val = float(val)
                if 0.0 <= val <= 0.30:
                    return round(val, 6)
    except Exception:
        pass
    return _YIELD_FALLBACK_MAP.get(ticker.upper(), 0.0)
SUPPORTED_BASE_CCY = ["USD", "EUR", "GBP", "COP", "CHF", "AUD"]
PUBLIC_DEFAULTS_VERSION = "public_defaults_v12_phase2"
GOOGLE_SHEETS_CACHE_TTL = 300
PORTFOLIO_START_DATE = date(2026, 3, 27)

PROXY_TICKER_MAP = {
    "IWDA.AS": "EUNL.DE",
    "EIMI.UK": "EIMI.L",  # yfinance uses .L suffix for LSE tickers
}

# Tickers that don't follow the standard exchange currency convention.
# Add any ticker here whose actual quote currency differs from its exchange suffix.
TICKER_CURRENCY_OVERRIDE = {
    "IGLN.L": "USD",  # iShares Physical Gold ETC — quoted in USD on LSE, not GBP
    "EIMI.UK": "USD",  # iShares Core MSCI EM IMI — quoted in USD on LSE, not GBP
}

PRIVATE_POSITIONS_HEADERS = ["Ticker", "Name", "Shares", "AvgCost"]
TRANSACTIONS_HEADERS = ["date", "ticker", "type", "shares", "price", "fees", "notes"]
CASH_BALANCES_HEADERS = ["currency", "amount"]
NON_PORTFOLIO_CASH_HEADERS = ["label", "currency", "amount", "institution", "notes"]
DIVIDENDS_HEADERS = ["date", "ticker", "amount", "currency", "notes"]

DIVIDEND_META = {
    "VOO": {"yield": 0.015, "months": [3, 6, 9, 12], "frequency": "Quarterly"},
    "8RMY.DE": {"yield": 0.0, "months": [], "frequency": "Accumulating"},
    "EIMI.UK": {"yield": 0.0, "months": [], "frequency": "Accumulating"},
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
    st.html(
        """
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;800&display=swap" rel="stylesheet">
        <style>
        /* ── Semantic color tokens ─────────────────────────────────────────── */
        :root {
            --clr-pos:   #00ff88;
            --clr-neg:   #ff4444;
            --clr-amber: #f5a623;
            --clr-bg:    #0a0a0a;
            --clr-card:  #111111;
            --clr-border:#2a313c;
        }

        /* ── Base ──────────────────────────────────────────────────────────── */
        html, body, [class*="css"] {
            font-family: "IBM Plex Mono", "SFMono-Regular", Menlo, Monaco, Consolas, monospace !important;
        }

        .stApp, [data-testid="stAppViewContainer"] {
            background-color: var(--clr-bg);
            color: #e6e6e6;
        }

        [data-testid="stSidebar"] {
            background: #0d0d0d;
            border-right: 1px solid var(--clr-border);
        }

        [data-testid="stHeader"] { background: var(--clr-bg); }

        .block-container {
            padding-top: 1.8rem !important;
            padding-left: 1.1rem !important;
            padding-right: 1.1rem !important;
            padding-bottom: 2rem !important;
            max-width: 1500px;
        }

        /* ── Page title ────────────────────────────────────────────────────── */
        .bb-title {
            font-size: 2rem;
            font-weight: 800;
            line-height: 1.15;
            color: var(--clr-amber);
            letter-spacing: 1px;
            padding-top: 0.2rem;
            padding-bottom: 0.8rem;
            margin-top: 0.35rem;
            margin-bottom: 1rem;
            border-bottom: 2px solid var(--clr-amber);
            text-transform: uppercase;
            display: block;
        }

        /* ── Section header ────────────────────────────────────────────────── */
        .bb-section {
            background: linear-gradient(180deg, #111111 0%, #0d0d0d 100%);
            border: 1px solid #1e2535;
            border-left: 4px solid var(--clr-amber);
            border-radius: 6px;
            padding: 0.85rem 1rem 0.9rem 1rem;
            margin: 0.65rem 0 1rem 0;
        }

        .bb-section-title {
            font-size: 1rem;
            font-weight: 800;
            color: var(--clr-amber);
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

        /* ── Metric cards (custom .bb-metric) ──────────────────────────────── */
        .bb-metric {
            background: var(--clr-card);
            border: 1px solid #1e2535;
            border-radius: 6px;
            padding: 0.75rem 0.9rem 0;
            position: relative;
            overflow: hidden;
            margin-bottom: 0.5rem;
        }
        .bb-metric::after {
            content: '';
            display: block;
            height: 3px;
            border-radius: 0 0 6px 6px;
            margin-top: 0.6rem;
            background: var(--accent, var(--clr-amber));
        }
        .bb-metric-label {
            font-size: 0.68rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: #6b7f96;
            margin-bottom: 0.25rem;
        }
        .bb-metric-value {
            font-size: 1.45rem;
            font-weight: 800;
            color: #f2f2f2;
            line-height: 1.1;
            letter-spacing: -0.5px;
        }
        .bb-metric-delta {
            font-size: 0.72rem;
            font-weight: 600;
            margin-top: 0.2rem;
            margin-bottom: 0.1rem;
        }
        .bb-metric-bar-wrap {
            background: #1a1a2e;
            border-radius: 3px;
            height: 5px;
            margin-top: 0.4rem;
            margin-bottom: 0.1rem;
            overflow: hidden;
        }
        .bb-metric-bar-fill {
            height: 100%;
            border-radius: 3px;
            background: var(--clr-pos);
            transition: width 0.4s ease;
        }

        /* ── Native st.metric override (fallback) ──────────────────────────── */
        [data-testid="stMetric"] {
            background: var(--clr-card);
            border: 1px solid #1e2535;
            border-bottom: 3px solid var(--clr-amber);
            border-radius: 6px;
            padding: 0.7rem 0.8rem 0.5rem 0.8rem;
        }
        [data-testid="stMetricLabel"] {
            color: #6b7f96 !important;
            text-transform: uppercase;
            font-size: 0.68rem !important;
            letter-spacing: 0.8px;
        }
        [data-testid="stMetricValue"] {
            color: #f2f2f2 !important;
            font-size: 1.45rem !important;
            font-weight: 800 !important;
        }

        /* ── Buttons ───────────────────────────────────────────────────────── */
        .stButton > button {
            background: #111111;
            color: var(--clr-amber);
            border: 1px solid var(--clr-amber);
            border-radius: 4px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.4px;
            min-height: 42px;
        }
        .stButton > button:hover {
            background: var(--clr-amber);
            color: #0a0a0a;
            border-color: var(--clr-amber);
        }

        /* ── Inputs ────────────────────────────────────────────────────────── */
        .stTextInput > div > div > input,
        .stNumberInput input,
        .stSelectbox div[data-baseweb="select"] > div,
        .stDateInput input {
            background-color: #111111 !important;
            color: #f2f2f2 !important;
            border: 1px solid #394250 !important;
            border-radius: 4px !important;
            min-height: 42px !important;
        }

        /* ── Tables ────────────────────────────────────────────────────────── */
        div[data-testid="stDataFrame"] {
            border: 1px solid #1e2535;
            border-radius: 6px;
            overflow: hidden;
        }
        div[data-testid="stDataFrame"] * {
            color: #e5e7eb !important;
            font-family: "IBM Plex Mono", monospace !important;
        }
        div[data-testid="stDataFrame"] [role="columnheader"] {
            background-color: #111111 !important;
            color: var(--clr-amber) !important;
            font-weight: 800 !important;
            text-transform: uppercase;
            position: sticky !important;
            top: 0 !important;
            z-index: 10 !important;
        }
        div[data-testid="stDataFrame"] [role="gridcell"] {
            background-color: #0d0d0d !important;
        }
        div[data-testid="stDataFrame"] [role="row"]:hover [role="gridcell"] {
            background-color: #1a1a2e !important;
        }

        /* ── Pulsing live dot ──────────────────────────────────────────────── */
        @keyframes pulse-green {
            0%   { box-shadow: 0 0 0 0 rgba(0,255,136,0.7); }
            70%  { box-shadow: 0 0 0 7px rgba(0,255,136,0); }
            100% { box-shadow: 0 0 0 0 rgba(0,255,136,0); }
        }
        @keyframes pulse-grey {
            0%   { box-shadow: 0 0 0 0 rgba(120,120,120,0.5); }
            70%  { box-shadow: 0 0 0 6px rgba(120,120,120,0); }
            100% { box-shadow: 0 0 0 0 rgba(120,120,120,0); }
        }
        .live-dot {
            display: inline-block;
            width: 9px; height: 9px;
            border-radius: 50%;
            margin-right: 6px;
            vertical-align: middle;
        }
        .live-dot.open  { background: var(--clr-pos);  animation: pulse-green 1.4s infinite; }
        .live-dot.closed{ background: #666;             animation: pulse-grey  2s   infinite; }

        /* ── Alerts ────────────────────────────────────────────────────────── */
        .stAlert {
            border-radius: 6px !important;
            border: 1px solid #1e2535 !important;
        }

        /* ── Responsive ────────────────────────────────────────────────────── */
        @media (max-width: 900px) {
            .block-container {
                padding-top: 3.2rem !important;
                padding-left: 0.7rem !important;
                padding-right: 0.7rem !important;
            }
            .bb-title { font-size: 1.55rem; }
            .bb-metric-value { font-size: 1.15rem !important; }
            [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: 0.6rem !important; }
            [data-testid="column"] { min-width: 100% !important; flex: 1 1 100% !important; }
        }
        </style>
        """,

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


def info_metric(
    container,
    label: str,
    value: str,
    help_text: str,
    delta: str | None = None,
    delta_positive: bool | None = None,
    accent_color: str | None = None,
    sharpe_value: float | None = None,
    sharpe_target: float = 3.0,
):
    """Bloomberg-style metric card with semantic accent line and optional delta / Sharpe bar."""
    import html as _html

    # Determine accent color
    if accent_color is None:
        accent_color = "#f5a623"  # amber default

    # Delta row
    delta_html = ""
    if delta is not None:
        if delta_positive is True:
            d_color, d_arrow = "#00ff88", "↑"
        elif delta_positive is False:
            d_color, d_arrow = "#ff4444", "↓"
        else:
            d_color, d_arrow = "#9fb0c3", "·"
        delta_html = (
            f"<div class='bb-metric-delta' style='color:{d_color}'>"
            f"{d_arrow} {_html.escape(str(delta))}</div>"
        )

    # Sharpe progress bar
    bar_html = ""
    if sharpe_value is not None:
        pct = min(float(sharpe_value) / sharpe_target, 1.0) * 100.0
        bar_color = "#00ff88" if float(sharpe_value) >= 1.0 else "#ff4444"
        bar_html = (
            f"<div class='bb-metric-bar-wrap'>"
            f"<div class='bb-metric-bar-fill' style='width:{pct:.1f}%;background:{bar_color}'></div>"
            f"</div>"
            f"<div style='font-size:0.62rem;color:#555;margin-bottom:0.1rem'>"
            f"Sharpe {float(sharpe_value):.2f} / target {sharpe_target:.1f}</div>"
        )

    card = (
        f"<div class='bb-metric' style='--accent:{accent_color}' title='{_html.escape(help_text)}'>"
        f"<div class='bb-metric-label'>{_html.escape(label)}</div>"
        f"<div class='bb-metric-value'>{_html.escape(value)}</div>"
        f"{delta_html}{bar_html}"
        f"</div>"
    )
    container.markdown(card, unsafe_allow_html=True)


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


def render_financial_independence_section(
    total_value: float,
    base_currency: str,
    portfolio_returns: pd.Series,
    non_portfolio_cash_value: float = 0.0,
    default_settings: dict | None = None,
):
    info_section(
        "Financial Independence Simulator",
        "Monte Carlo simulation (1 000 paths · GBM) showing the probability of reaching "
        "financial independence — the point where your portfolio can sustain your target "
        "monthly withdrawal indefinitely."
    )

    net_worth = total_value + non_portfolio_cash_value

    # Pre-fill session state from saved defaults (only on first load of a session)
    _s = default_settings or {}
    _defaults = {
        "fi_monthly_contribution": float(_s.get("monthly_contribution", 500.0)),
        "fi_target_withdrawal":    float(_s.get("fi_target_withdrawal", 3000.0)),
        "fi_inflation_pct":        float(_s.get("fi_inflation_pct", 3.0)),
        "fi_swr_pct":              float(_s.get("fi_swr_pct", 4.0)),
        "fi_horizon_years":        int(float(_s.get("fi_horizon_years", 30))),
    }
    for _k, _v in _defaults.items():
        if _k not in st.session_state:
            st.session_state[_k] = _v

    # ── Inputs ────────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    with c1:
        target_withdrawal = st.number_input(
            f"Target Monthly Withdrawal ({base_currency})",
            min_value=0.0,
            max_value=1_000_000.0,
            step=100.0,
            help="How much you want to withdraw per month in retirement (in today's money).",
            key="fi_target_withdrawal",
        )
        monthly_contribution = st.number_input(
            f"Monthly Contribution ({base_currency})",
            min_value=0.0,
            step=50.0,
            help="How much you add to the portfolio each month.",
            key="fi_monthly_contribution",
        )
    with c2:
        inflation_pct = st.number_input(
            "Annual Inflation (%)",
            min_value=0.0,
            max_value=20.0,
            step=0.5,
            format="%.1f",
            help="Used to inflate the withdrawal target over time and deflate real returns.",
            key="fi_inflation_pct",
        )
        swr_pct = st.number_input(
            "Safe Withdrawal Rate (%)",
            min_value=0.1,
            max_value=10.0,
            step=0.1,
            format="%.1f",
            help="The annual withdrawal rate you consider sustainable (classic: 4%).",
            key="fi_swr_pct",
        )
    with c3:
        horizon_years = st.slider(
            "Simulation Horizon (Years)",
            min_value=5, max_value=50, step=5,
            key="fi_horizon_years",
        )
        default_vol = 0.15
        if portfolio_returns is not None and not portfolio_returns.empty and len(portfolio_returns) > 20:
            default_vol = float(min(portfolio_returns.std() * np.sqrt(252), 0.40))
        if "fi_annual_vol" not in st.session_state:
            st.session_state["fi_annual_vol"] = float(round(default_vol * 100, 1))
        annual_vol_pct = st.number_input(
            "Annual Volatility (%)",
            min_value=1.0,
            max_value=50.0,
            step=0.5,
            format="%.1f",
            help="Portfolio annual volatility. Pre-filled from your historical returns.",
            key="fi_annual_vol",
        )

    # Expected return: pre-fill from history
    default_return = 0.08
    if portfolio_returns is not None and not portfolio_returns.empty and len(portfolio_returns) > 20:
        hr = float(portfolio_returns.mean() * 252)
        if np.isfinite(hr):
            default_return = min(max(hr, 0.02), 0.18)
    if "fi_annual_return" not in st.session_state:
        st.session_state["fi_annual_return"] = float(round(default_return * 100, 1))
    annual_return_pct = st.slider(
        "Expected Annual Return (%)",
        min_value=0.0, max_value=20.0,
        step=0.1, format="%.1f",
        key="fi_annual_return",
    )

    annual_return = annual_return_pct / 100.0
    annual_vol = annual_vol_pct / 100.0
    inflation = inflation_pct / 100.0
    swr = swr_pct / 100.0
    n_paths = 1000
    n_months = horizon_years * 12

    # Real (inflation-adjusted) return
    real_return = (1 + annual_return) / (1 + inflation) - 1
    monthly_real_return = (1 + real_return) ** (1 / 12) - 1
    monthly_vol = annual_vol / np.sqrt(12)

    # FI target: portfolio size needed to sustain target_withdrawal/month in REAL terms
    fi_target = (target_withdrawal * 12) / swr if swr > 0 else 0.0

    # ── Required contribution recommendation ─────────────────────────────────
    if fi_target > 0 and monthly_real_return > 0 and n_months > 0:
        growth_factor = (1 + monthly_real_return) ** n_months
        portfolio_fv = net_worth * growth_factor
        if fi_target > portfolio_fv:
            required_pmt = (fi_target - portfolio_fv) * monthly_real_return / (growth_factor - 1)
        else:
            required_pmt = 0.0
    else:
        required_pmt = None

    # ── Recommended contribution box ─────────────────────────────────────────
    st.divider()
    if required_pmt is None:
        st.info("Recommended contribution: cannot compute — adjust return or horizon.")
    elif required_pmt <= 0:
        st.success("Already on track — no additional contribution needed to reach FI.")
    else:
        st.metric(
            label="Recommended Monthly Contribution",
            value=base_currency + " " + "{:,.0f}".format(required_pmt),
            help="Monthly contribution needed to reach your FI target within the horizon, at the expected return and inflation.",
        )
        st.caption(
            "Target " + base_currency + " " + "{:,.0f}".format(fi_target)
            + " in " + str(horizon_years) + " yrs"
            + " | Return " + "{:.1f}".format(annual_return_pct) + "%"
            + " | Inflation " + "{:.1f}".format(inflation_pct) + "%"
            + " | SWR " + "{:.1f}".format(swr_pct) + "%"
        )
    st.divider()

    # ── Monte Carlo ───────────────────────────────────────────────────────────
    rng = np.random.default_rng(seed=42)
    shocks = rng.normal(
        loc=(monthly_real_return - 0.5 * monthly_vol ** 2),
        scale=monthly_vol,
        size=(n_months, n_paths),
    )
    monthly_growth = np.exp(shocks)  # GBM multiplicative factor

    # Simulate paths
    paths = np.empty((n_months + 1, n_paths))
    paths[0] = net_worth
    for m in range(n_months):
        paths[m + 1] = np.maximum(paths[m] * monthly_growth[m] + monthly_contribution, 0.0)

    # ── FI detection ─────────────────────────────────────────────────────────
    fi_months = np.full(n_paths, np.nan)
    for p in range(n_paths):
        hits = np.where(paths[:, p] >= fi_target)[0]
        if len(hits) > 0:
            fi_months[p] = hits[0]

    fi_years = fi_months / 12.0
    prob_fi_by_year = []
    year_range = list(range(1, horizon_years + 1))
    for yr in year_range:
        prob = float(np.mean(fi_months <= yr * 12))
        prob_fi_by_year.append(prob)

    median_fi_years = float(np.nanmedian(fi_years)) if not np.all(np.isnan(fi_years)) else None
    prob_fi_total = float(np.mean(~np.isnan(fi_months)))

    # ── Fan chart ─────────────────────────────────────────────────────────────
    year_axis = np.arange(n_months + 1) / 12.0
    p10 = np.percentile(paths, 10, axis=1)
    p25 = np.percentile(paths, 25, axis=1)
    p50 = np.percentile(paths, 50, axis=1)
    p75 = np.percentile(paths, 75, axis=1)
    p90 = np.percentile(paths, 90, axis=1)

    fig_fan = go.Figure()
    fig_fan.add_scatter(x=year_axis, y=p90, mode="lines", line=dict(color="rgba(243,167,18,0.15)", width=0), name="P90", showlegend=False)
    fig_fan.add_scatter(x=year_axis, y=p10, mode="lines", fill="tonexty", fillcolor="rgba(243,167,18,0.10)", line=dict(color="rgba(243,167,18,0.15)", width=0), name="P10–P90 band", showlegend=True)
    fig_fan.add_scatter(x=year_axis, y=p75, mode="lines", line=dict(color="rgba(243,167,18,0.25)", width=0), name="P75", showlegend=False)
    fig_fan.add_scatter(x=year_axis, y=p25, mode="lines", fill="tonexty", fillcolor="rgba(243,167,18,0.20)", line=dict(color="rgba(243,167,18,0.25)", width=0), name="P25–P75 band", showlegend=True)
    fig_fan.add_scatter(x=year_axis, y=p50, mode="lines", line=dict(color="#f3a712", width=2.5), name="Median path")
    fig_fan.add_hline(y=fi_target, line_dash="dash", line_color="#4dff4d", annotation_text=f"FI target ({base_currency} {fi_target:,.0f})", annotation_position="top right")
    fig_fan.update_layout(
        xaxis_title="Years from now",
        yaxis_title=f"Portfolio value ({base_currency})",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=420,
        margin=dict(t=20, b=20, l=20, r=20),
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    st.plotly_chart(fig_fan, use_container_width=True)

    # ── Probability curve ─────────────────────────────────────────────────────
    fig_prob = go.Figure()
    fig_prob.add_scatter(
        x=year_range, y=[p * 100 for p in prob_fi_by_year],
        mode="lines+markers", line=dict(color="#f3a712", width=2),
        hovertemplate="Year %{x}: %{y:.1f}% probability<extra></extra>",
    )
    fig_prob.add_hline(y=50, line_dash="dot", line_color="#888", annotation_text="50% probability")
    fig_prob.add_hline(y=90, line_dash="dot", line_color="#4dff4d", annotation_text="90% probability")
    fig_prob.update_layout(
        xaxis_title="Years from now",
        yaxis_title="Probability of reaching FI (%)",
        yaxis=dict(range=[0, 101]),
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=320,
        margin=dict(t=20, b=20, l=20, r=20),
    )

    info_section("Probability of Financial Independence by Year", "Likelihood of sustaining your target monthly withdrawal.")
    st.plotly_chart(fig_prob, use_container_width=True)

    # ── Key metrics ───────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "FI Target",
        f"{base_currency} {fi_target:,.0f}",
        help=f"Portfolio size needed at {swr_pct:.1f}% SWR to sustain {base_currency} {target_withdrawal:,.0f}/month",
    )
    c2.metric(
        "Median FI Year",
        f"Year {median_fi_years:.1f}" if median_fi_years is not None else "Not within horizon",
        help="Half of simulated paths reach FI before this year.",
    )
    c3.metric(
        f"P(FI in {horizon_years}y)",
        f"{prob_fi_total:.0%}",
        help=f"Probability of achieving financial independence within {horizon_years} years.",
    )
    c4.metric(
        "Current Coverage",
        f"{(net_worth * swr / 12) / target_withdrawal:.0%}",
        help="How much of your target monthly withdrawal can the current portfolio already sustain.",
    )

    st.caption(
        f"Monte Carlo: {n_paths:,} paths · GBM · Real return (inflation-adjusted): {real_return:.2%}/yr · "
        f"Starting net worth: {base_currency} {net_worth:,.0f} · "
        f"FI = portfolio ≥ {base_currency} {fi_target:,.0f} (target withdrawal × 12 ÷ SWR)."
    )


def render_investment_horizon_section(
    total_value: float,
    base_currency: str,
    portfolio_returns: pd.Series,
    default_settings: dict | None = None,
):
    info_section(
        "Investment Horizon",
        "Projected portfolio value over a selected investment horizon using monthly compounding and optional monthly contributions."
    )

    _s = default_settings or {}

    _horizon_options = [5, 10, 15, 20, 25, 30]
    if "ih_horizon_years" not in st.session_state:
        _saved_horizon = int(float(_s.get("ih_horizon_years", 10)))
        st.session_state["ih_horizon_years"] = _saved_horizon if _saved_horizon in _horizon_options else 10
    horizon_years = st.selectbox(
        "Investment Horizon (Years)",
        _horizon_options,
        key="ih_horizon_years",
        help="Select the projection horizon.",
    )

    default_return = 0.08
    if not portfolio_returns.empty:
        hist_return = float(portfolio_returns.mean() * 252)
        if np.isfinite(hist_return):
            default_return = min(max(hist_return, 0.00), 0.15)
    if "ih_annual_return" not in st.session_state:
        _saved_return = float(_s.get("ih_annual_return", round(default_return * 100, 1)))
        st.session_state["ih_annual_return"] = min(max(_saved_return, 0.0), 20.0)

    expected_return_pct = st.slider(
        "Expected Annual Return (%)",
        min_value=0.0,
        max_value=20.0,
        step=0.1,
        format="%.1f",
        key="ih_annual_return",
    )
    expected_return = expected_return_pct / 100.0
    st.caption(f"Selected expected annual return: {expected_return_pct:.1f}%")

    if "ih_monthly_contribution" not in st.session_state:
        st.session_state["ih_monthly_contribution"] = float(_s.get("monthly_contribution", 0.0))
    monthly_contribution = st.number_input(
        f"Monthly Contribution ({base_currency})",
        min_value=0.0,
        step=100.0,
        key="ih_monthly_contribution",
    )

    if "ih_scenario_spread" not in st.session_state:
        _saved_spread = float(_s.get("ih_scenario_spread", 3.0))
        st.session_state["ih_scenario_spread"] = min(max(_saved_spread, 0.0), 10.0)
    scenario_spread_pct = st.slider(
        "Scenario Spread (%)",
        min_value=0.0,
        max_value=10.0,
        step=0.1,
        format="%.1f",
        key="ih_scenario_spread",
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


def connect_non_portfolio_cash_worksheet():
    return _connect_named_worksheet("non_portfolio_cash", NON_PORTFOLIO_CASH_HEADERS)


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


def _parse_gsheets_date(val):
    """Convert a Google Sheets date serial number (days since Dec 30, 1899) to an ISO string.

    Google Sheets stores date-formatted cells as integers when returned with
    UNFORMATTED_VALUE. This avoids pd.to_datetime interpreting them as nanoseconds
    (which produces 1970-01-01 dates).
    """
    if isinstance(val, (int, float)) and 1 < val < 200_000:
        from datetime import datetime, timedelta
        return (datetime(1899, 12, 30) + timedelta(days=int(val))).strftime("%Y-%m-%d")
    return val


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

    df["date"] = pd.to_datetime(df["date"].apply(_parse_gsheets_date), errors="coerce")
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
    ws.append_row(row, value_input_option="RAW")
    _clear_google_sheets_cache()


TRADE_JOURNAL_HEADERS = [
    "id", "date", "ticker", "direction", "shares", "entry_price",
    "target_price", "stop_loss", "thesis", "status", "exit_date", "exit_price", "notes",
]


def connect_trade_journal_worksheet():
    return _connect_named_worksheet("trade_journal", TRADE_JOURNAL_HEADERS)


@st.cache_data(ttl=GOOGLE_SHEETS_CACHE_TTL, show_spinner=False)
def load_trade_journal_from_sheets() -> pd.DataFrame:
    sheet_id, sheet_url = _get_private_positions_sheet_locator()
    try:
        connect_trade_journal_worksheet()
        records = _get_worksheet_records_cached(sheet_id, sheet_url, "trade_journal")
    except Exception:
        return pd.DataFrame(columns=TRADE_JOURNAL_HEADERS)

    if not records:
        return pd.DataFrame(columns=TRADE_JOURNAL_HEADERS)

    df = pd.DataFrame(records)
    df.columns = [str(c).strip().lower() for c in df.columns]
    for col in TRADE_JOURNAL_HEADERS:
        if col not in df.columns:
            df[col] = ""
    for col in ["shares", "entry_price", "target_price", "stop_loss", "exit_price"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"].apply(_parse_gsheets_date), errors="coerce")
    df["exit_date"] = pd.to_datetime(df["exit_date"].apply(_parse_gsheets_date), errors="coerce")
    df = df.dropna(subset=["date"])
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    return df[TRADE_JOURNAL_HEADERS].reset_index(drop=True)


def append_trade_journal_entry(entry: dict):
    ws = connect_trade_journal_worksheet()
    row = [
        str(entry.get("id", "")),
        str(entry.get("date", "")),
        str(entry.get("ticker", "")).upper().strip(),
        str(entry.get("direction", "")).upper().strip(),
        float(entry.get("shares", 0.0)),
        float(entry.get("entry_price", 0.0)),
        float(entry.get("target_price", 0.0)) if entry.get("target_price") else "",
        float(entry.get("stop_loss", 0.0)) if entry.get("stop_loss") else "",
        str(entry.get("thesis", "")).strip(),
        str(entry.get("status", "Active")).strip(),
        str(entry.get("exit_date", "")).strip(),
        float(entry.get("exit_price", 0.0)) if entry.get("exit_price") else "",
        str(entry.get("notes", "")).strip(),
    ]
    ws.append_row(row, value_input_option="RAW")
    _clear_google_sheets_cache()


def update_trade_journal_entry(entry_id: str, updates: dict):
    """Update an existing trade journal row by its id column."""
    ws = connect_trade_journal_worksheet()
    records = ws.get_all_values()
    if len(records) < 2:
        return
    header = [str(h).strip().lower() for h in records[0]]
    id_col = header.index("id") + 1 if "id" in header else None
    if id_col is None:
        return
    for i, row in enumerate(records[1:], start=2):
        if str(row[id_col - 1]).strip() == str(entry_id).strip():
            for field, val in updates.items():
                if field in header:
                    col_num = header.index(field) + 1
                    ws.update_cell(i, col_num, val)
            break
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


def load_non_portfolio_cash_from_sheets() -> pd.DataFrame:
    sheet_id, sheet_url = _get_private_positions_sheet_locator()
    try:
        connect_non_portfolio_cash_worksheet()
        records = _get_worksheet_records_cached(sheet_id, sheet_url, "non_portfolio_cash")
    except Exception:
        return pd.DataFrame(columns=NON_PORTFOLIO_CASH_HEADERS)

    if not records:
        return pd.DataFrame(columns=NON_PORTFOLIO_CASH_HEADERS)

    df = pd.DataFrame(records)
    df.columns = [str(c).strip().lower() for c in df.columns]
    for col in NON_PORTFOLIO_CASH_HEADERS:
        if col not in df.columns:
            df[col] = ""
    df["amount"] = pd.to_numeric(
        df["amount"].astype(str).str.replace(",", ".", regex=False),
        errors="coerce",
    ).fillna(0.0)
    df["currency"] = df["currency"].astype(str).str.strip().str.upper()
    df["label"] = df["label"].astype(str).str.strip()
    return df[df["label"] != ""].reset_index(drop=True)


def save_non_portfolio_cash_to_sheets(df: pd.DataFrame):
    ws = connect_non_portfolio_cash_worksheet()
    clean = df.copy()
    for col in NON_PORTFOLIO_CASH_HEADERS:
        if col not in clean.columns:
            clean[col] = ""
    clean["amount"] = pd.to_numeric(clean["amount"], errors="coerce").fillna(0.0)
    clean["currency"] = clean["currency"].astype(str).str.strip().str.upper()
    clean["label"] = clean["label"].astype(str).str.strip()
    clean = clean[clean["label"] != ""].reset_index(drop=True)

    rows = [NON_PORTFOLIO_CASH_HEADERS]
    for _, row in clean.iterrows():
        rows.append([
            str(row["label"]), str(row["currency"]), float(row["amount"]),
            str(row.get("institution", "")), str(row.get("notes", "")),
        ])
    ws.clear()
    ws.update(range_name="A1", values=rows)
    _clear_google_sheets_cache()


USER_SETTINGS_HEADERS = ["key", "value"]


def connect_user_settings_worksheet():
    return _connect_named_worksheet("user_settings", USER_SETTINGS_HEADERS)


def load_user_settings_from_sheets() -> dict:
    sheet_id, sheet_url = _get_private_positions_sheet_locator()
    try:
        connect_user_settings_worksheet()
        records = _get_worksheet_records_cached(sheet_id, sheet_url, "user_settings")
    except Exception:
        return {}
    if not records:
        return {}
    result = {}
    for r in records:
        key = str(r.get("key", "")).strip()
        val = str(r.get("value", "")).strip()
        if key:
            result[key] = val
    return result


def save_user_settings_to_sheets(settings: dict):
    ws = connect_user_settings_worksheet()
    rows = [USER_SETTINGS_HEADERS]
    for key, value in settings.items():
        rows.append([str(key), str(value)])
    ws.clear()
    ws.update(range_name="A1", values=rows)
    _clear_google_sheets_cache()


WATCHLIST_HEADERS = ["ticker", "notes"]


def connect_watchlist_worksheet():
    return _connect_named_worksheet("watchlist", WATCHLIST_HEADERS)


def load_watchlist_from_sheets() -> list:
    sheet_id, sheet_url = _get_private_positions_sheet_locator()
    try:
        connect_watchlist_worksheet()
        records = _get_worksheet_records_cached(sheet_id, sheet_url, "watchlist")
    except Exception:
        return []
    tickers = []
    for r in records:
        t = str(r.get("ticker", "")).strip().upper()
        if t:
            tickers.append(t)
    return tickers


def save_watchlist_to_sheets(tickers: list):
    ws = connect_watchlist_worksheet()
    rows = [WATCHLIST_HEADERS]
    for t in tickers:
        t = str(t).upper().strip()
        if t:
            rows.append([t, ""])
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


# =========================
# PAPER TRADING
# =========================

PAPER_TRADES_HEADERS = [
    "id", "timestamp", "ticker", "action", "shares", "price", "fees", "notes", "source",
]
PAPER_CONFIG_HEADERS = ["key", "value"]


def connect_paper_trades_worksheet():
    return _connect_named_worksheet("paper_trades", PAPER_TRADES_HEADERS)


def connect_paper_config_worksheet():
    return _connect_named_worksheet(
        "paper_config",
        PAPER_CONFIG_HEADERS,
        default_rows=[["starting_capital", 100000.0]],
    )


@st.cache_data(ttl=GOOGLE_SHEETS_CACHE_TTL, show_spinner=False)
def load_paper_trades_from_sheets() -> pd.DataFrame:
    sheet_id, sheet_url = _get_private_positions_sheet_locator()
    try:
        connect_paper_trades_worksheet()
        records = _get_worksheet_records_cached(sheet_id, sheet_url, "paper_trades")
    except Exception:
        return pd.DataFrame(columns=PAPER_TRADES_HEADERS)

    if not records:
        return pd.DataFrame(columns=PAPER_TRADES_HEADERS)

    df = pd.DataFrame(records)
    df.columns = [str(c).strip().lower() for c in df.columns]
    for col in PAPER_TRADES_HEADERS:
        if col not in df.columns:
            df[col] = ""
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce").fillna(0.0)
    df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0.0)
    df["fees"] = pd.to_numeric(df["fees"], errors="coerce").fillna(0.0)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["action"] = df["action"].astype(str).str.strip().str.upper()
    df = df.dropna(subset=["timestamp"])
    return df[PAPER_TRADES_HEADERS].sort_values("timestamp").reset_index(drop=True)


@st.cache_data(ttl=GOOGLE_SHEETS_CACHE_TTL, show_spinner=False)
def load_paper_capital_from_sheets() -> float:
    sheet_id, sheet_url = _get_private_positions_sheet_locator()
    try:
        connect_paper_config_worksheet()
        records = _get_worksheet_records_cached(sheet_id, sheet_url, "paper_config")
    except Exception:
        return 100_000.0

    for row in records:
        if str(row.get("key", "")).strip().lower() == "starting_capital":
            try:
                return float(row.get("value", 100_000.0))
            except Exception:
                return 100_000.0
    return 100_000.0


def save_paper_capital_to_sheets(capital: float):
    ws = connect_paper_config_worksheet()
    records = ws.get_all_values()
    for i, row in enumerate(records[1:], start=2):
        if len(row) >= 1 and str(row[0]).strip().lower() == "starting_capital":
            ws.update_cell(i, 2, float(capital))
            _clear_google_sheets_cache()
            return
    ws.append_row(["starting_capital", float(capital)], value_input_option="RAW")
    _clear_google_sheets_cache()


def append_paper_trade_to_sheets(trade: dict):
    ws = connect_paper_trades_worksheet()
    row = [
        str(trade.get("id", "")),
        str(trade.get("timestamp", "")),
        str(trade.get("ticker", "")).upper().strip(),
        str(trade.get("action", "")).upper().strip(),
        float(trade.get("shares", 0.0)),
        float(trade.get("price", 0.0)),
        float(trade.get("fees", 0.0)),
        str(trade.get("notes", "")).strip(),
        str(trade.get("source", "MANUAL")).strip(),
    ]
    ws.append_row(row, value_input_option="RAW")
    _clear_google_sheets_cache()


def reset_paper_trades_to_sheets():
    """Clear all paper trades (requires management password check in UI)."""
    ws = connect_paper_trades_worksheet()
    ws.clear()
    ws.update(range_name="A1", values=[PAPER_TRADES_HEADERS])
    _clear_google_sheets_cache()


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

    df["date"] = pd.to_datetime(df["date"].apply(_parse_gsheets_date), errors="coerce")
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
    ws.append_row(row, value_input_option="RAW")
    _clear_google_sheets_cache()


# =========================
# PORTFOLIO
# =========================
def load_private_portfolio():
    p = st.secrets["private_portfolio"]
    return {
        "8RMY.DE": {"name": "iShares MSCI EM Multifactor ETF", "shares": float(p.get("8RMY_DE", 0.0)), "base_shares": float(p.get("8RMY_DE", 0.0))},
        "EIMI.UK": {"name": "iShares Core MSCI EM IMI", "shares": float(p.get("EIMI_UK", 0.0)), "base_shares": float(p.get("EIMI_UK", 0.0))},
        "VOO": {"name": "S&P 500", "shares": float(p["VOO"]), "base_shares": float(p["VOO"])},
        "VWCE.DE": {"name": "All World", "shares": float(p["VWCE_DE"]), "base_shares": float(p["VWCE_DE"])},
        "IGLN.L": {"name": "Gold", "shares": float(p["IGLN_L"]), "base_shares": float(p["IGLN_L"])},
        "QQQM": {"name": "Nasdaq-100 Growth ETF", "shares": float(p.get("QQQM", 0.0)), "base_shares": float(p.get("QQQM", 0.0))},
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
        # Tickers not in base portfolio are ignored — base is the source of truth
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


@st.cache_data(ttl=900, show_spinner=False)
def build_fx_data(tickers: list[str], base_currency: str, period: str = "2y", extra_currencies: tuple[str, ...] = ()):
    needed_ccy = set(asset_currency(t) for t in tickers)
    needed_ccy.add(base_currency)
    needed_ccy.add("USD")
    needed_ccy.update(extra_currencies)

    fx_tickers = set()
    for a in needed_ccy:
        for b in needed_ccy:
            if a != b:
                fx_tickers.add(f"{a}{b}=X")

    fx_tickers = sorted(fx_tickers)
    fx_prices = get_prices(fx_tickers) if fx_tickers else {}
    fx_hist = get_historical_data(fx_tickers, period=period) if fx_tickers else pd.DataFrame()

    return fx_prices, fx_hist, fx_tickers


@st.cache_data(ttl=900, show_spinner=False)
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


@st.cache_data(ttl=900, show_spinner=False)
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


@st.cache_data(ttl=900, show_spinner=False)
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
            st.warning(f"⚠️ FX rate unavailable for {ccy} → {base_currency}. Cash balance shown as 0.")
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
    fx_fallback: dict | None = None,
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
            cached = (fx_fallback or {}).get(f"{native_currency}_{base_currency}")
            if cached is not None:
                st.warning(
                    f"⚠️ Live FX rate unavailable for {ticker} ({native_currency} → {base_currency}). "
                    f"Using last known rate {cached:.4f}."
                )
                fx_rate = cached
            else:
                st.warning(
                    f"⚠️ FX rate unavailable for {ticker} ({native_currency} → {base_currency}). "
                    "Position excluded from portfolio totals."
                )
                continue

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
            # Use total current shares × avg cost so that pre-existing shares
            # not recorded as transactions don't create phantom unrealized PnL.
            invested_native = shares * avg_cost_native
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
            # Use current value weights so tickers with 0 shares get 0 target
            # instead of misleading equal-weight across all registered tickers.
            total_val = df["Value"].sum() if "Value" in df.columns else 0.0
            if total_val > 0:
                df["Target Weight"] = df["Value"] / total_val
            else:
                df["Target Weight"] = 0.0
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


@st.cache_data(ttl=900, show_spinner=False)
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


@st.cache_data(ttl=900, show_spinner=False)
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
            st.warning(f"⚠️ FX rate unavailable for dividend currency {ccy} → {base_currency}. Dividend excluded from totals.")
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


def _per_ticker_bounds_list(asset_names: list[str], constraints: dict) -> list[tuple]:
    """Return a scipy bounds list respecting per-ticker weight rules.

    Each element is (lo, hi).  Fixed-weight tickers get (w, w); free tickers
    get (0.0, max_single_asset); custom-range tickers get (lo, hi).
    """
    max_single = float(constraints["max_single_asset"])
    ptb = constraints.get("per_ticker_bounds", {})
    return [ptb.get(t, (0.0, max_single)) for t in asset_names]


_BOND_ASSETS = {"BND", "AGG", "IEF", "TLT", "VGIT", "BNDX"}
_GOLD_ASSETS = {"IGLN.L", "GLD", "IAU", "SGLN.L"}


def classify_assets(asset_names):
    bond_idx = [i for i, t in enumerate(asset_names) if t in _BOND_ASSETS]
    gold_idx = [i for i, t in enumerate(asset_names) if t in _GOLD_ASSETS]
    return bond_idx, gold_idx


def bucket_for_ticker(ticker: str):
    if ticker in _BOND_ASSETS:
        return "Bonds"
    if ticker in _GOLD_ASSETS:
        return "Gold"
    return "Equities"


def _shrunk_cov(returns_df: pd.DataFrame, annualize: bool = True) -> np.ndarray:
    """Ledoit-Wolf shrinkage covariance estimator.

    Produces a better-conditioned covariance matrix than the raw sample
    estimate, especially when the number of assets is large relative to
    the number of observations.  Falls back to the sample covariance if
    sklearn is unavailable or the estimator fails.
    """
    r = returns_df.dropna()
    try:
        from sklearn.covariance import LedoitWolf
        cov = LedoitWolf(assume_centered=False).fit(r.values).covariance_
    except Exception:
        cov = r.cov().values
    return cov * (252 if annualize else 1)


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
    _cov_arr = _shrunk_cov(asset_returns)
    cov_matrix = pd.DataFrame(_cov_arr, index=asset_returns.columns, columns=asset_returns.columns)

    n_assets = len(mean_returns)
    max_single_asset = float(constraints["max_single_asset"])
    min_bonds = float(constraints["min_bonds"])
    min_gold = float(constraints["min_gold"])

    if min_bonds + min_gold > 1:
        return pd.DataFrame()

    bond_idx, gold_idx = classify_assets(asset_names)

    rng = np.random.default_rng(42)
    per_ticker_bounds = constraints.get("per_ticker_bounds", {})

    # Separate fixed tickers (lo == hi) from free tickers
    fixed = {}   # {col_idx: weight}
    for i, ticker in enumerate(asset_names):
        if ticker in per_ticker_bounds:
            lo, hi = per_ticker_bounds[ticker]
            if abs(lo - hi) < 1e-8:
                fixed[i] = lo

    if fixed:
        # Generate portfolios with fixed portions; randomise the rest
        fixed_sum = sum(fixed.values())
        free_idx = [i for i in range(n_assets) if i not in fixed]
        if not free_idx or fixed_sum >= 1.0 - 1e-8:
            return pd.DataFrame()
        remaining = 1.0 - fixed_sum
        n_free = len(free_idx)
        raw_free = rng.random((n_portfolios * 6, n_free))
        raw_free = np.clip(raw_free, 0.0, max_single_asset)
        row_sums = raw_free.sum(axis=1, keepdims=True)
        valid = row_sums.squeeze() > 1e-12
        raw_free, row_sums = raw_free[valid], row_sums[valid]
        free_w = raw_free / row_sums * remaining
        weights = np.zeros((len(raw_free), n_assets))
        for col, w in fixed.items():
            weights[:, col] = w
        for j, col in enumerate(free_idx):
            weights[:, col] = free_w[:, j]
        mask = np.ones(len(weights), dtype=bool)
    else:
        raw = rng.random((n_portfolios * 6, n_assets))
        weights = raw / raw.sum(axis=1, keepdims=True)
        mask = weights.max(axis=1) <= max_single_asset
        # Apply non-fixed per-ticker bounds as a filter
        for i, ticker in enumerate(asset_names):
            if ticker in per_ticker_bounds:
                lo, hi = per_ticker_bounds[ticker]
                mask &= (weights[:, i] >= lo - 1e-6) & (weights[:, i] <= hi + 1e-6)

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


@st.cache_data(ttl=86400, show_spinner=False)
def optimize_max_sharpe(
    asset_returns: pd.DataFrame,
    asset_names: list[str],
    constraints: dict,
    risk_free_rate: float = 0.02,
) -> "pd.Series | None":
    """Exact maximum-Sharpe portfolio via SLSQP (scipy).

    Uses 32 starting points (equal weight + random Dirichlet) for robustness
    against local optima.  Returns a Series with keys Weights, Return,
    Volatility, Sharpe — same interface as a frontier row.
    """
    from scipy.optimize import minimize

    n = asset_returns.shape[1]
    mean_ret = asset_returns.mean().values * 252
    cov = _shrunk_cov(asset_returns)

    bond_idx, gold_idx = classify_assets(asset_names)
    max_single = float(constraints["max_single_asset"])
    min_bonds  = float(constraints["min_bonds"])
    min_gold   = float(constraints["min_gold"])

    # Infeasible when the required asset class is absent
    if min_bonds > 0 and not bond_idx:
        return None
    if min_gold > 0 and not gold_idx:
        return None

    def neg_sharpe(w):
        ret = float(w @ mean_ret)
        var = float(w @ cov @ w)
        vol = np.sqrt(max(var, 1e-20))
        return -(ret - risk_free_rate) / vol

    cons = [{"type": "eq", "fun": lambda w: float(np.sum(w)) - 1.0}]
    if bond_idx and min_bonds > 0:
        _bi = bond_idx
        cons.append({"type": "ineq", "fun": lambda w, i=_bi: float(np.sum(w[i])) - min_bonds})
    if gold_idx and min_gold > 0:
        _gi = gold_idx
        cons.append({"type": "ineq", "fun": lambda w, i=_gi: float(np.sum(w[i])) - min_gold})

    bounds = _per_ticker_bounds_list(asset_names, constraints)
    lo_arr = np.array([b[0] for b in bounds])
    hi_arr = np.array([b[1] for b in bounds])
    rng = np.random.default_rng(7)

    starts = []
    w0 = np.clip(np.full(n, 1.0 / n), lo_arr, hi_arr)
    if w0.sum() > 0:
        w0 /= w0.sum()
    starts.append(w0)
    for _ in range(31):
        raw = rng.dirichlet(np.ones(n))
        raw = np.clip(raw, lo_arr, hi_arr)
        if raw.sum() > 0:
            raw /= raw.sum()
        starts.append(raw)

    best_w, best_val = None, np.inf
    for w0 in starts:
        try:
            res = minimize(
                neg_sharpe, w0, method="SLSQP",
                bounds=bounds, constraints=cons,
                options={"maxiter": 2000, "ftol": 1e-14},
            )
            if res.success and res.fun < best_val:
                best_val = res.fun
                best_w   = res.x.copy()
        except Exception:
            continue

    if best_w is None:
        return None

    best_w = np.clip(best_w, 0.0, None)
    best_w /= best_w.sum()
    ret  = float(best_w @ mean_ret)
    vol  = float(np.sqrt(best_w @ cov @ best_w))
    shrp = (ret - risk_free_rate) / vol if vol > 0 else 0.0

    return pd.Series({"Weights": best_w, "Return": ret, "Volatility": vol, "Sharpe": shrp})


@st.cache_data(ttl=86400, show_spinner=False)
def optimize_min_vol(
    asset_returns: pd.DataFrame,
    asset_names: list[str],
    constraints: dict,
    risk_free_rate: float = 0.02,
) -> "pd.Series | None":
    """Exact minimum-volatility portfolio via SLSQP (scipy).

    The objective (portfolio variance) is quadratic-convex so a single
    equal-weight starting point is sufficient.  Returns a Series with
    keys Weights, Return, Volatility, Sharpe.
    """
    from scipy.optimize import minimize

    n = asset_returns.shape[1]
    mean_ret = asset_returns.mean().values * 252
    cov = _shrunk_cov(asset_returns)

    bond_idx, gold_idx = classify_assets(asset_names)
    max_single = float(constraints["max_single_asset"])
    min_bonds  = float(constraints["min_bonds"])
    min_gold   = float(constraints["min_gold"])

    if min_bonds > 0 and not bond_idx:
        return None
    if min_gold > 0 and not gold_idx:
        return None

    def port_vol(w):
        return float(np.sqrt(np.maximum(w @ cov @ w, 0.0)))

    cons = [{"type": "eq", "fun": lambda w: float(np.sum(w)) - 1.0}]
    if bond_idx and min_bonds > 0:
        _bi = bond_idx
        cons.append({"type": "ineq", "fun": lambda w, i=_bi: float(np.sum(w[i])) - min_bonds})
    if gold_idx and min_gold > 0:
        _gi = gold_idx
        cons.append({"type": "ineq", "fun": lambda w, i=_gi: float(np.sum(w[i])) - min_gold})

    bounds = _per_ticker_bounds_list(asset_names, constraints)
    lo_arr = np.array([b[0] for b in bounds])
    hi_arr = np.array([b[1] for b in bounds])
    w0 = np.clip(np.full(n, 1.0 / n), lo_arr, hi_arr)
    if w0.sum() > 0:
        w0 /= w0.sum()

    try:
        res = minimize(
            port_vol, w0, method="SLSQP",
            bounds=bounds, constraints=cons,
            options={"maxiter": 2000, "ftol": 1e-14},
        )
    except Exception:
        return None

    if not res.success:
        return None

    best_w = np.clip(res.x, 0.0, None)
    best_w /= best_w.sum()
    ret  = float(best_w @ mean_ret)
    vol  = float(np.sqrt(best_w @ cov @ best_w))
    shrp = (ret - risk_free_rate) / vol if vol > 0 else 0.0

    return pd.Series({"Weights": best_w, "Return": ret, "Volatility": vol, "Sharpe": shrp})


@st.cache_data(ttl=86400, show_spinner=False)
def optimize_min_cvar(
    asset_returns: pd.DataFrame,
    asset_names: list[str],
    constraints: dict,
    confidence_level: float = 0.95,
    risk_free_rate: float = 0.02,
) -> "pd.Series | None":
    """Minimum-CVaR portfolio via Rockafellar-Uryasev linear programming.

    Directly minimises the Conditional Value-at-Risk (Expected Shortfall) of
    the portfolio at a given confidence level.  Unlike min-vol optimisation,
    this objective is a coherent risk measure and naturally penalises fat-tail
    losses even when the return distribution is non-normal.

    LP variables: w (n weights), v (scalar VaR), z (T aux variables ≥ 0)
    Objective: min  v + 1 / (T * (1 - α)) * Σ z_t
    Subject to: z_t ≥ -r_t @ w - v,  z_t ≥ 0,  Σ w = 1,  bounds
    """
    from scipy.optimize import linprog

    if asset_returns is None or asset_returns.empty or len(asset_returns) < 30:
        return None
    if len(asset_names) < 2:
        return None

    r = asset_returns[asset_names].dropna().values   # T × n
    T, n = r.shape
    alpha = confidence_level

    bond_idx, gold_idx = classify_assets(asset_names)
    max_single = float(constraints.get("max_single_asset", 1.0))
    min_bonds  = float(constraints.get("min_bonds", 0.0))
    min_gold   = float(constraints.get("min_gold", 0.0))

    # Objective vector: [0]*n + [1 (VaR)] + [1/(T*(1-α))]*T
    c_obj = np.zeros(n + 1 + T)
    c_obj[n]   = 1.0
    c_obj[n+1:] = 1.0 / (T * (1 - alpha))

    # Inequality: -r_t @ w - v - z_t ≤ 0  →  A_ub x ≤ b_ub
    A_ub = np.zeros((T, n + 1 + T))
    for t in range(T):
        A_ub[t, :n]     = -r[t]   # -r_t @ w
        A_ub[t, n]      = -1.0    # -v
        A_ub[t, n+1+t]  = -1.0   # -z_t
    b_ub = np.zeros(T)

    # Equality: Σ w = 1
    A_eq = np.zeros((1, n + 1 + T))
    A_eq[0, :n] = 1.0
    b_eq = np.array([1.0])

    # Bounds on w
    per_ticker_bounds = constraints.get("per_ticker_bounds", {})
    w_bounds = []
    for i, ticker in enumerate(asset_names):
        if ticker in per_ticker_bounds:
            lo, hi = per_ticker_bounds[ticker]
        else:
            lo, hi = 0.0, max_single
        w_bounds.append((lo, hi))

    # Add min_bonds / min_gold as additional inequality rows: -Σ w_bonds ≤ -min_bonds
    extra_rows, extra_b = [], []
    if bond_idx and min_bonds > 0:
        row = np.zeros(n + 1 + T)
        for i in bond_idx:
            row[i] = -1.0
        extra_rows.append(row)
        extra_b.append(-min_bonds)
    if gold_idx and min_gold > 0:
        row = np.zeros(n + 1 + T)
        for i in gold_idx:
            row[i] = -1.0
        extra_rows.append(row)
        extra_b.append(-min_gold)
    if extra_rows:
        A_ub = np.vstack([A_ub, extra_rows])
        b_ub = np.concatenate([b_ub, extra_b])

    bounds = w_bounds + [(None, None)] + [(0.0, None)] * T   # v unbounded, z ≥ 0

    try:
        res = linprog(c_obj, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                      bounds=bounds, method="highs")
        if not res.success:
            return None
    except Exception:
        return None

    best_w = np.clip(res.x[:n], 0.0, None)
    if best_w.sum() <= 0:
        return None
    best_w /= best_w.sum()

    mean_ret = asset_returns[asset_names].mean().values * 252
    cov      = _shrunk_cov(asset_returns[asset_names])
    ret  = float(best_w @ mean_ret)
    vol  = float(np.sqrt(max(best_w @ cov @ best_w, 0.0)))
    shrp = (ret - risk_free_rate) / vol if vol > 0 else 0.0

    # Realised CVaR of the solution
    port_r = r @ best_w
    threshold = np.percentile(port_r, (1 - alpha) * 100)
    tail = port_r[port_r <= threshold]
    cvar = float(-tail.mean()) if len(tail) > 0 else 0.0

    return pd.Series({"Weights": best_w, "Return": ret, "Volatility": vol,
                       "Sharpe": shrp, "CVaR": cvar})


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


@st.cache_data(ttl=900, show_spinner=False)
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
# INSTITUTIONAL CONSTANTS
# =========================

HISTORICAL_SCENARIOS: dict = {
    "2008 GFC":       {"Equities": -0.50, "Bonds":  0.05, "Gold":  0.05},
    "2020 COVID":     {"Equities": -0.34, "Bonds":  0.08, "Gold":  0.06},
    "2022 Rate Hike": {"Equities": -0.19, "Bonds": -0.13, "Gold": -0.02},
    "2001 Dot-com":   {"Equities": -0.49, "Bonds":  0.10, "Gold":  0.08},
    "2018 Q4 Selloff":{"Equities": -0.20, "Bonds":  0.02, "Gold":  0.03},
}

BOND_DURATION_MAP: dict = {
    "BND": 6.5, "AGG": 6.3, "IEF": 7.5,
    "TLT": 17.0, "VGIT": 5.4, "BNDX": 8.2,
}


# =========================
# INSTITUTIONAL RISK METRICS
# =========================

def compute_var_cvar(
    portfolio_returns: pd.Series,
    confidence_levels: list | None = None,
) -> dict:
    """Historical, parametric, and Cornish-Fisher modified VaR/CVaR at 95% and 99%.

    Cornish-Fisher expansion adjusts the normal z-score for the observed
    skewness and excess kurtosis of the return distribution, producing a
    better tail-risk estimate when returns are non-normal (fat tails, negative
    skew).  Keys added: cf_var_95, cf_cvar_95, cf_var_99, cf_cvar_99,
    skewness, excess_kurtosis.
    """
    from scipy import stats as _scipy_stats

    if confidence_levels is None:
        confidence_levels = [0.95, 0.99]

    result: dict = {}
    if portfolio_returns is None or portfolio_returns.empty:
        return result

    r = pd.to_numeric(portfolio_returns, errors="coerce").dropna()
    if len(r) < 30:
        return result

    mu = float(r.mean())
    sigma = float(r.std())
    _Z = {0.95: 1.6449, 0.99: 2.3263}

    skew = float(_scipy_stats.skew(r.values))
    kurt = float(_scipy_stats.kurtosis(r.values))  # excess kurtosis

    for c in confidence_levels:
        lbl = int(c * 100)
        # Historical
        hist_var = -float(np.percentile(r, (1 - c) * 100))
        tail = r[r <= -hist_var]
        hist_cvar = -float(tail.mean()) if not tail.empty else hist_var
        # Parametric (normal)
        z = _Z.get(c, 1.6449)
        param_var = float(-(mu - z * sigma))
        # Parametric CVaR: E[loss | loss > VaR] = -mu + sigma * phi(z) / (1-c)
        phi_z = float(np.exp(-0.5 * z ** 2) / np.sqrt(2 * np.pi))
        param_cvar = float(-(mu - sigma * phi_z / (1 - c)))

        # Cornish-Fisher modified VaR — adjusts z for skewness and kurtosis
        z_cf = (
            z
            + (z ** 2 - 1) * skew / 6
            + (z ** 3 - 3 * z) * kurt / 24
            - (2 * z ** 3 - 5 * z) * skew ** 2 / 36
        )
        cf_var = float(-(mu - z_cf * sigma))
        cf_tail = r[r <= -cf_var]
        cf_cvar = -float(cf_tail.mean()) if not cf_tail.empty else cf_var

        result[f"hist_var_{lbl}"] = hist_var
        result[f"hist_cvar_{lbl}"] = hist_cvar
        result[f"param_var_{lbl}"] = param_var
        result[f"param_cvar_{lbl}"] = param_cvar
        result[f"cf_var_{lbl}"] = cf_var
        result[f"cf_cvar_{lbl}"] = cf_cvar

    result["n_observations"] = len(r)
    result["skewness"] = skew
    result["excess_kurtosis"] = kurt
    return result


def build_correlation_heatmap(asset_returns: pd.DataFrame) -> go.Figure | None:
    """Correlation heatmap for all assets."""
    if asset_returns is None or asset_returns.empty or asset_returns.shape[1] < 2:
        return None

    corr = asset_returns.corr().round(2)
    tickers = corr.columns.tolist()
    z = corr.values

    fig = go.Figure(go.Heatmap(
        z=z,
        x=tickers,
        y=tickers,
        zmin=-1,
        zmax=1,
        colorscale="RdBu",
        text=[[f"{v:.2f}" for v in row] for row in z],
        texttemplate="%{text}",
        hovertemplate="%{y} / %{x}: %{z:.2f}<extra></extra>",
        showscale=True,
    ))
    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=420,
        margin=dict(t=20, b=80, l=80, r=20),
    )
    return fig


def compute_extended_ratios(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series | None,
    risk_free_rate: float,
    max_drawdown: float,
) -> dict:
    """Sortino, Calmar, Upside/Downside Capture, Omega."""
    result = {
        "sortino": None,
        "calmar": None,
        "upside_capture": None,
        "downside_capture": None,
        "omega": None,
    }

    if portfolio_returns is None or portfolio_returns.empty:
        return result

    r = pd.to_numeric(portfolio_returns, errors="coerce").dropna()
    if len(r) < 30:
        return result

    ann_return = float((1 + r).prod() ** (252 / len(r)) - 1)

    # Sortino
    downside = r[r < 0]
    if not downside.empty:
        ds_std = float(downside.std() * np.sqrt(252))
        if ds_std > 0:
            result["sortino"] = (ann_return - risk_free_rate) / ds_std

    # Calmar
    if max_drawdown < 0:
        result["calmar"] = ann_return / abs(max_drawdown)

    # Upside / Downside Capture
    if benchmark_returns is not None and not benchmark_returns.empty:
        aligned = (
            r.rename("P")
            .to_frame()
            .join(pd.to_numeric(benchmark_returns, errors="coerce").rename("B"), how="inner")
            .dropna()
        )
        if not aligned.empty:
            up = aligned[aligned["B"] > 0]
            dn = aligned[aligned["B"] < 0]
            if not up.empty and float(up["B"].mean()) != 0:
                result["upside_capture"] = float(up["P"].mean() / up["B"].mean() * 100)
            if not dn.empty and float(dn["B"].mean()) != 0:
                result["downside_capture"] = float(dn["P"].mean() / dn["B"].mean() * 100)

    # Omega
    threshold = risk_free_rate / 252
    gains = float((r - threshold).clip(lower=0).sum())
    losses = float((threshold - r).clip(lower=0).sum())
    if losses > 0:
        result["omega"] = gains / losses

    return result


def compute_mwr(transactions_df: pd.DataFrame, current_value: float) -> dict:
    """Money-Weighted Return (IRR) from transaction cash flows."""
    result: dict = {"mwr": None, "n_transactions": 0}

    if transactions_df is None or transactions_df.empty or current_value <= 0:
        return result

    tx = transactions_df.copy()
    tx["date"] = pd.to_datetime(tx["date"], errors="coerce")
    tx["shares"] = pd.to_numeric(tx["shares"], errors="coerce").fillna(0.0)
    tx["price"] = pd.to_numeric(tx["price"], errors="coerce").fillna(0.0)
    tx["fees"] = pd.to_numeric(tx["fees"], errors="coerce").fillna(0.0)
    tx = tx.dropna(subset=["date"]).sort_values("date")

    cash_flows: list[tuple] = []
    for _, row in tx.iterrows():
        gross = float(row["shares"]) * float(row["price"]) + float(row["fees"])
        tx_type = str(row.get("type", "")).upper()
        if tx_type == "BUY":
            cash_flows.append((row["date"], -gross))
        elif tx_type == "SELL":
            cash_flows.append((row["date"], gross))

    if not cash_flows:
        return result

    result["n_transactions"] = len(cash_flows)
    today = pd.Timestamp.now().normalize()
    cash_flows.append((today, float(current_value)))

    start = cash_flows[0][0]
    offsets = [int((d - start).days) for d, _ in cash_flows]
    amounts = [a for _, a in cash_flows]
    max_days = max(offsets) if offsets else 1

    # Require at least 30 days of history — annualizing a daily rate over a
    # shorter period produces misleading numbers.
    if max_days < 30:
        return result

    def npv(daily_rate: float) -> float:
        return sum(a / (1 + daily_rate) ** t for a, t in zip(amounts, offsets))

    try:
        # Bounds derived from annual rate limits so annualization can never overflow.
        # lo ≈ daily rate for -99.99% annual  |  hi ≈ daily rate for +500% annual
        lo = (1.0 - 0.9999) ** (1.0 / 252.0) - 1.0   # ≈ -0.0346 / day
        hi = (1.0 + 5.0)    ** (1.0 / 252.0) - 1.0   # ≈  0.0071 / day
        npv_lo, npv_hi = npv(lo), npv(hi)
        if npv_lo * npv_hi > 0:
            return result
        for _ in range(150):
            mid = (lo + hi) / 2.0
            if npv(mid) * npv_lo < 0:
                hi = mid
            else:
                lo = mid
                npv_lo = npv(lo)
        daily_irr = (lo + hi) / 2.0
        annualized = float((1 + daily_irr) ** 252 - 1)
        if np.isfinite(annualized) and -1.0 < annualized <= 5.0:
            result["mwr"] = annualized
    except Exception:
        pass

    return result


def compute_twr(
    snapshots_df: pd.DataFrame,
    transactions_df: pd.DataFrame | None = None,
) -> dict:
    """Time-Weighted Return chained across saved portfolio snapshots."""
    result: dict = {"twr": None, "n_periods": 0, "start_date": None, "end_date": None}

    if snapshots_df is None or snapshots_df.empty or len(snapshots_df) < 2:
        return result

    work = snapshots_df.sort_values("timestamp").copy()
    work["total_portfolio_value"] = pd.to_numeric(work["total_portfolio_value"], errors="coerce")
    work = work.dropna(subset=["total_portfolio_value"]).reset_index(drop=True)

    if len(work) < 2:
        return result

    # Build per-period net external cash flows from transactions
    cf_map: dict[int, float] = {}
    if transactions_df is not None and not transactions_df.empty:
        tx = transactions_df.copy()
        tx["date"] = pd.to_datetime(tx["date"], errors="coerce")
        tx["shares"] = pd.to_numeric(tx["shares"], errors="coerce").fillna(0.0)
        tx["price"] = pd.to_numeric(tx["price"], errors="coerce").fillna(0.0)
        tx["fees"] = pd.to_numeric(tx["fees"], errors="coerce").fillna(0.0)
        tx = tx.dropna(subset=["date"])

        for i in range(1, len(work)):
            t0 = work["timestamp"].iloc[i - 1]
            t1 = work["timestamp"].iloc[i]
            period_tx = tx[(tx["date"] > t0) & (tx["date"] <= t1)]
            net = 0.0
            for _, row in period_tx.iterrows():
                gross = float(row["shares"]) * float(row["price"]) + float(row["fees"])
                if str(row.get("type", "")).upper() == "BUY":
                    net += gross
                elif str(row.get("type", "")).upper() == "SELL":
                    net -= gross
            cf_map[i] = net

    compound = 1.0
    for i in range(1, len(work)):
        v0 = float(work["total_portfolio_value"].iloc[i - 1])
        v1 = float(work["total_portfolio_value"].iloc[i])
        cf = cf_map.get(i, 0.0)
        denominator = v0 + cf
        if denominator > 0:
            compound *= v1 / denominator

    result["twr"] = float(compound - 1)
    result["n_periods"] = len(work) - 1
    result["start_date"] = str(pd.to_datetime(work["timestamp"].iloc[0]).date())
    result["end_date"] = str(pd.to_datetime(work["timestamp"].iloc[-1]).date())
    return result


def compute_brinson_attribution(
    df: pd.DataFrame,
    asset_returns: pd.DataFrame,
    policy_target_map: dict,
    benchmark_returns: pd.Series | None,
) -> pd.DataFrame | None:
    """Brinson-Hood-Beebower single-period attribution at the asset level."""
    if df is None or df.empty:
        return None
    if benchmark_returns is None or benchmark_returns.empty:
        return None

    bench_total = float((1 + pd.to_numeric(benchmark_returns, errors="coerce").dropna()).prod() - 1)

    rows = []
    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        w_p = float(row.get("Weight", 0.0))
        w_b = float(policy_target_map.get(ticker, 0.0))

        if asset_returns is not None and ticker in asset_returns.columns:
            r_p = float((1 + pd.to_numeric(asset_returns[ticker], errors="coerce").dropna()).prod() - 1)
        else:
            r_p = 0.0

        # BHB decomposition (R_bi = bench_total for all assets)
        allocation = (w_p - w_b) * bench_total
        selection = w_b * (r_p - bench_total)
        interaction = (w_p - w_b) * (r_p - bench_total)
        total = allocation + selection + interaction

        rows.append({
            "Ticker": ticker,
            "Portfolio W%": round(w_p * 100, 2),
            "Target W%": round(w_b * 100, 2),
            "Asset Return": round(r_p * 100, 2),
            "Benchmark Return": round(bench_total * 100, 2),
            "Allocation Effect": round(allocation * 100, 2),
            "Selection Effect": round(selection * 100, 2),
            "Interaction Effect": round(interaction * 100, 2),
            "Total Attribution": round(total * 100, 2),
        })

    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False)
def run_monte_carlo_projection(
    portfolio_returns: pd.Series,
    current_value: float,
    horizons_years: tuple = (1, 3, 5, 10),
    monthly_contribution: float = 0.0,
    n_sims: int = 500,
    seed: int = 42,
) -> dict:
    """Bootstrap Monte Carlo projection for multiple time horizons."""
    result: dict = {}
    if portfolio_returns is None or portfolio_returns.empty or len(portfolio_returns) < 60:
        return result

    rng = np.random.default_rng(seed)
    r = pd.to_numeric(portfolio_returns, errors="coerce").dropna().values

    for h in horizons_years:
        n_months = h * 12
        paths = np.zeros((n_sims, n_months + 1))
        paths[:, 0] = current_value

        for m in range(n_months):
            sampled = rng.choice(r, size=(n_sims, 21), replace=True)
            monthly_r = (1 + sampled).prod(axis=1) - 1
            paths[:, m + 1] = paths[:, m] * (1 + monthly_r) + monthly_contribution

        pcts = np.percentile(paths, [10, 25, 50, 75, 90], axis=0)
        result[h] = pd.DataFrame(
            {"p10": pcts[0], "p25": pcts[1], "p50": pcts[2], "p75": pcts[3], "p90": pcts[4]},
            index=range(n_months + 1),
        )

    return result


def compute_risk_budget(
    asset_returns: pd.DataFrame,
    weights: pd.Series,
    confidence_level: float = 0.95,
) -> pd.DataFrame | None:
    """Component VaR / Marginal VaR / Risk Contribution per asset."""
    if asset_returns is None or asset_returns.empty or weights is None or weights.empty:
        return None

    tickers = [t for t in weights.index if t in asset_returns.columns]
    if len(tickers) < 2:
        return None

    w = weights.loc[tickers].values.astype(float)
    total_w = w.sum()
    if total_w <= 0:
        return None
    w = w / total_w

    cov = _shrunk_cov(asset_returns[tickers])
    port_var = float(w @ cov @ w)
    port_vol = float(np.sqrt(max(port_var, 1e-12)))

    _Z = {0.95: 1.6449, 0.99: 2.3263}
    z = _Z.get(confidence_level, 1.6449)

    port_var_daily = port_var / 252
    port_vol_daily = float(np.sqrt(max(port_var_daily, 1e-12)))

    marginal_var = (cov @ w) / port_vol * z / np.sqrt(252)
    component_var = w * marginal_var
    total_cvar = component_var.sum()
    risk_contribution = component_var / total_cvar if total_cvar > 0 else np.ones(len(w)) / len(w)

    rows = []
    for i, ticker in enumerate(tickers):
        rows.append({
            "Ticker": ticker,
            "Weight %": round(w[i] * 100, 2),
            "Marginal VaR (daily)": round(float(marginal_var[i]), 4),
            "Component VaR (daily)": round(float(component_var[i]), 4),
            "Risk Contribution %": round(float(risk_contribution[i]) * 100, 2),
        })
    return pd.DataFrame(rows).sort_values("Risk Contribution %", ascending=False).reset_index(drop=True)


def run_historical_scenarios(
    df: pd.DataFrame,
    current_total_value: float,
) -> pd.DataFrame:
    """Apply hardcoded historical crisis shocks to the current portfolio."""
    if df is None or df.empty or current_total_value <= 0:
        return pd.DataFrame()

    rows = []
    for scenario_name, shocks in HISTORICAL_SCENARIOS.items():
        shocked_value = 0.0
        for _, row in df.iterrows():
            ticker = str(row["Ticker"])
            value = float(row.get("Value", 0.0))
            bucket = bucket_for_ticker(ticker)
            shock = shocks.get(bucket, 0.0)
            shocked_value += value * (1 + shock)

        pnl = shocked_value - current_total_value
        ret = pnl / current_total_value if current_total_value > 0 else 0.0
        rows.append({
            "Scenario": scenario_name,
            "Current Value": round(current_total_value, 2),
            "Shocked Value": round(shocked_value, 2),
            "Scenario PnL": round(pnl, 2),
            "Scenario Return %": round(ret * 100, 2),
        })
    return pd.DataFrame(rows)


def compute_fixed_income_analytics(
    df: pd.DataFrame,
    base_currency: str,
) -> pd.DataFrame | None:
    """Duration, DV01 and rate sensitivity for bond ETFs in portfolio."""
    if df is None or df.empty:
        return None

    rows = []
    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        if bucket_for_ticker(ticker) != "Bonds":
            continue
        duration = BOND_DURATION_MAP.get(ticker)
        if duration is None:
            continue
        value = float(row.get("Value", 0.0))
        dv01 = duration / 10000 * value
        rate_1pct_abs = -duration / 100 * value
        rate_1pct_pct = -duration / 100
        rows.append({
            "Ticker": ticker,
            "Name": str(row.get("Name", "")),
            f"Value ({base_currency})": round(value, 2),
            "Duration (yrs)": duration,
            f"DV01 ({base_currency})": round(dv01, 2),
            f"Rate +1% Impact ({base_currency})": round(rate_1pct_abs, 2),
            "Rate +1% Impact %": round(rate_1pct_pct * 100, 2),
        })

    return pd.DataFrame(rows) if rows else None


@st.cache_data(ttl=900, show_spinner=False)
def build_blended_benchmark_returns(
    base_currency: str,
    fx_hist: pd.DataFrame,
    voo_weight: float = 0.60,
    bnd_weight: float = 0.40,
) -> pd.Series:
    """Blended benchmark = voo_weight * VOO + bnd_weight * BND, in base currency."""
    tickers = []
    if voo_weight > 0:
        tickers.append("VOO")
    if bnd_weight > 0:
        tickers.append("BND")
    if not tickers:
        return pd.Series(dtype=float)

    raw = get_historical_data(tickers, period="2y")
    if raw.empty:
        return pd.Series(dtype=float)

    frames = {}
    for t in tickers:
        if t not in raw.columns:
            continue
        s = pd.to_numeric(raw[t], errors="coerce").dropna()
        if base_currency != "USD":
            fx = get_fx_series("USD", base_currency, fx_hist)
            if fx is not None:
                aligned = pd.concat([s, fx.rename("FX")], axis=1).dropna()
                s = (aligned.iloc[:, 0] * aligned["FX"])
        frames[t] = s.pct_change().dropna()

    if not frames:
        return pd.Series(dtype=float)

    combined = pd.concat(frames, axis=1).dropna()
    blended = pd.Series(0.0, index=combined.index)
    if "VOO" in combined.columns:
        blended += combined["VOO"] * voo_weight
    if "BND" in combined.columns:
        blended += combined["BND"] * bnd_weight
    return blended.dropna()


@st.cache_data(ttl=86400, show_spinner=False)
def compute_ff3_exposure(
    portfolio_returns: pd.Series,
    risk_free_rate: float = 0.02,
) -> dict | None:
    """Carhart 4-factor OLS regression using ETF proxies.

    Factors:
      Mkt-RF  Market excess return          proxy: IVV - rf
      SMB     Small minus Big (size)        proxy: IWM - IVV
      HML     High minus Low (value)        proxy: IVE - IVW
      UMD     Up minus Down (momentum)      proxy: MTUM - IVV

    UMD is added when MTUM data is available (launched 2013); the function
    gracefully falls back to 3-factor if MTUM cannot be fetched.  Backward-
    compatible: all existing keys are preserved; umd_beta / umd_tstat are
    added when the 4th factor is present.
    """
    if portfolio_returns is None or portfolio_returns.empty or len(portfolio_returns) < 60:
        return None

    try:
        proxy_tickers = ["IVV", "IWM", "IVE", "IVW", "MTUM"]
        proxy_data = get_historical_data(proxy_tickers, period="2y")
        if proxy_data.empty or proxy_data.shape[1] < 3:
            return None

        rets = proxy_data.pct_change().dropna()
        required = ["IVV", "IWM", "IVE", "IVW"]
        if not all(c in rets.columns for c in required):
            return None

        rf_daily = risk_free_rate / 252
        mkt_rf = rets["IVV"] - rf_daily
        smb = rets["IWM"] - rets["IVV"]
        hml = rets["IVE"] - rets["IVW"]

        use_umd = "MTUM" in rets.columns
        if use_umd:
            umd = rets["MTUM"] - rets["IVV"]
            factors = pd.concat(
                [mkt_rf.rename("Mkt_RF"), smb.rename("SMB"), hml.rename("HML"), umd.rename("UMD")],
                axis=1,
            )
        else:
            factors = pd.concat(
                [mkt_rf.rename("Mkt_RF"), smb.rename("SMB"), hml.rename("HML")],
                axis=1,
            )

        aligned = pd.concat([portfolio_returns.rename("Port"), factors], axis=1).dropna()

        if len(aligned) < 60:
            return None

        y = aligned["Port"].values - rf_daily
        factor_cols = ["Mkt_RF", "SMB", "HML"] + (["UMD"] if use_umd else [])
        X = np.column_stack([np.ones(len(y))] + [aligned[f].values for f in factor_cols])

        betas, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        y_hat = X @ betas
        residuals = y - y_hat
        n, k = len(y), X.shape[1]
        s2 = float(np.dot(residuals, residuals) / (n - k))
        XtX_inv = np.linalg.pinv(X.T @ X)
        se = np.sqrt(np.maximum(np.diag(XtX_inv) * s2, 0))
        t_stats = betas / np.where(se > 0, se, np.nan)
        ss_res = float(np.dot(residuals, residuals))
        ss_tot = float(np.dot(y - y.mean(), y - y.mean()))
        r_sq = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        result = {
            "alpha": float(betas[0] * 252),
            "alpha_tstat": float(t_stats[0]),
            "mkt_beta": float(betas[1]),
            "mkt_tstat": float(t_stats[1]),
            "smb_beta": float(betas[2]),
            "smb_tstat": float(t_stats[2]),
            "hml_beta": float(betas[3]),
            "hml_tstat": float(t_stats[3]),
            "r_squared": float(r_sq),
            "n_obs": n,
            "source": "ETF Proxy (IVV/IWM/IVE/IVW" + ("/MTUM)" if use_umd else ")"),
        }
        if use_umd:
            result["umd_beta"] = float(betas[4])
            result["umd_tstat"] = float(t_stats[4])
        return result
    except Exception:
        return None


def compute_black_litterman(
    asset_returns: pd.DataFrame,
    current_weights: np.ndarray,
    tickers: list,
    views: list,
    risk_free_rate: float = 0.02,
    risk_aversion: float = 2.5,
    tau: float = 0.05,
) -> dict | None:
    """Black-Litterman posterior expected returns given investor views."""
    if asset_returns is None or asset_returns.empty or len(tickers) < 2:
        return None
    try:
        sigma = _shrunk_cov(asset_returns[tickers])
        w = np.array(current_weights, dtype=float)
        if w.sum() <= 0:
            w = np.ones(len(tickers)) / len(tickers)
        else:
            w = w / w.sum()

        pi = risk_aversion * sigma @ w  # equilibrium excess returns

        if not views:
            posterior = pi + risk_free_rate
            return {
                "posterior_returns": pd.Series(posterior, index=tickers),
                "equilibrium_returns": pd.Series(pi + risk_free_rate, index=tickers),
                "sigma": pd.DataFrame(sigma, index=tickers, columns=tickers),
                "tickers": tickers,
            }

        n_assets = len(tickers)
        n_views = len(views)
        ticker_idx = {t: i for i, t in enumerate(tickers)}

        P = np.zeros((n_views, n_assets))
        Q = np.zeros(n_views)
        omega_diag = np.zeros(n_views)

        for i, view in enumerate(views):
            t = view["ticker"]
            if t not in ticker_idx:
                continue
            P[i, ticker_idx[t]] = 1.0
            Q[i] = float(view["expected_return"]) - risk_free_rate
            conf = float(view.get("confidence", 0.5))
            conf = max(0.01, min(0.99, conf))
            p_row = P[i:i+1]
            omega_diag[i] = float((1 - conf) / conf * (p_row @ (tau * sigma) @ p_row.T)[0, 0])

        omega = np.diag(omega_diag)
        tau_sigma_inv = np.linalg.pinv(tau * sigma)
        P_T_omega_inv = P.T @ np.linalg.pinv(omega)
        M_inv = tau_sigma_inv + P_T_omega_inv @ P
        M = np.linalg.pinv(M_inv)
        mu_bl = M @ (tau_sigma_inv @ pi + P_T_omega_inv @ Q)
        posterior = mu_bl + risk_free_rate

        return {
            "posterior_returns": pd.Series(posterior, index=tickers),
            "equilibrium_returns": pd.Series(pi + risk_free_rate, index=tickers),
            "sigma": pd.DataFrame(sigma, index=tickers, columns=tickers),
            "tickers": tickers,
        }
    except Exception:
        return None


def compute_monthly_returns_calendar(portfolio_returns: pd.Series) -> pd.DataFrame | None:
    """Monthly returns grid: rows=years, cols=months (Jan-Dec) + YTD."""
    if portfolio_returns is None or portfolio_returns.empty or len(portfolio_returns) < 20:
        return None

    returns = portfolio_returns.copy()
    returns.index = pd.to_datetime(returns.index)

    monthly = returns.resample("ME").apply(lambda r: float((1 + r).prod() - 1))

    years = sorted(monthly.index.year.unique())
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    records = []
    for yr in years:
        row: dict = {"Year": yr}
        ytd = 1.0
        for m in range(1, 13):
            mask = (monthly.index.year == yr) & (monthly.index.month == m)
            val = float(monthly[mask].iloc[0]) if mask.any() else None
            row[month_names[m - 1]] = val
            if val is not None:
                ytd *= (1 + val)
        row["YTD"] = float(ytd - 1)
        records.append(row)

    return pd.DataFrame(records)


def compute_drawdown_episodes(portfolio_returns: pd.Series) -> pd.DataFrame | None:
    """All historical drawdown episodes with peak/trough/recovery dates and durations."""
    if portfolio_returns is None or portfolio_returns.empty or len(portfolio_returns) < 10:
        return None

    cum = (1 + portfolio_returns).cumprod()
    cum.index = pd.to_datetime(cum.index)

    episodes = []
    in_drawdown = False
    peak_date = cum.index[0]
    peak_val = float(cum.iloc[0])
    trough_date = peak_date
    trough_val = peak_val

    for dt, val in cum.items():
        val = float(val)
        if val >= peak_val:
            if in_drawdown:
                # Recovery
                dd_pct = (trough_val - peak_val) / peak_val
                episodes.append({
                    "Peak Date": peak_date.date(),
                    "Trough Date": trough_date.date(),
                    "Recovery Date": dt.date(),
                    "Max Drawdown %": round(dd_pct * 100, 2),
                    "Duration (days)": (trough_date - peak_date).days,
                    "Recovery (days)": (dt - trough_date).days,
                })
                in_drawdown = False
            peak_date = dt
            peak_val = val
            trough_date = dt
            trough_val = val
        else:
            in_drawdown = True
            if val < trough_val:
                trough_date = dt
                trough_val = val

    # Open drawdown (no recovery yet)
    if in_drawdown:
        dd_pct = (trough_val - peak_val) / peak_val
        episodes.append({
            "Peak Date": peak_date.date(),
            "Trough Date": trough_date.date(),
            "Recovery Date": None,
            "Max Drawdown %": round(dd_pct * 100, 2),
            "Duration (days)": (trough_date - peak_date).days,
            "Recovery (days)": None,
        })

    if not episodes:
        return pd.DataFrame()

    df = pd.DataFrame(episodes).sort_values("Max Drawdown %").reset_index(drop=True)
    return df


def compute_risk_parity_weights(
    asset_returns: pd.DataFrame,
    max_iter: int = 1000,
    tol: float = 1e-8,
) -> dict | None:
    """Equal Risk Contribution (ERC) weights via iterative normalization."""
    if asset_returns is None or asset_returns.empty or len(asset_returns.columns) < 2:
        return None

    returns_clean = asset_returns.dropna(how="all").fillna(0)
    if len(returns_clean) < 30:
        return None

    tickers = list(returns_clean.columns)
    n = len(tickers)
    cov = _shrunk_cov(returns_clean)

    # Iterative ERC: w_i ∝ 1 / (Cov @ w)_i until risk contributions are equal
    w = np.ones(n) / n
    for _ in range(max_iter):
        sigma_p = float(np.sqrt(max(w @ cov @ w, 1e-12)))
        marginal = (cov @ w) / sigma_p
        w_new = w / marginal
        w_new = w_new / w_new.sum()
        if float(np.max(np.abs(w_new - w))) < tol:
            w = w_new
            break
        w = w_new

    # Compute risk contributions
    sigma_p = float(np.sqrt(max(w @ cov @ w, 1e-12)))
    rc = w * (cov @ w) / sigma_p

    return {
        "tickers": tickers,
        "weights": {t: float(w[i]) for i, t in enumerate(tickers)},
        "risk_contributions": {t: float(rc[i] / rc.sum()) for i, t in enumerate(tickers)},
        "portfolio_vol": sigma_p,
    }


def compute_hrp_weights(asset_returns: pd.DataFrame) -> dict | None:
    """Hierarchical Risk Parity (Lopez de Prado 2016).

    Builds weights via single-linkage hierarchical clustering on a
    correlation-distance matrix, then allocates capital through recursive
    bisection using inverse-variance weighting.  Unlike ERC / mean-variance,
    HRP never inverts the covariance matrix, making it robust when assets are
    highly correlated or the matrix is near-singular.

    Returns the same interface as compute_risk_parity_weights so results can
    be used interchangeably downstream.
    """
    from scipy.cluster.hierarchy import linkage, leaves_list
    from scipy.spatial.distance import squareform

    if asset_returns is None or asset_returns.empty or asset_returns.shape[1] < 2:
        return None

    r = asset_returns.dropna(how="all")
    if len(r) < 30:
        return None

    tickers = list(r.columns)
    n = len(tickers)
    cov = _shrunk_cov(r)                   # annualised shrunk covariance
    corr_mat = r.corr().values

    # Distance matrix: d_ij = sqrt((1 - rho_ij) / 2)
    dist = np.sqrt(np.clip((1 - corr_mat) / 2, 0, 1))
    np.fill_diagonal(dist, 0.0)
    condensed = squareform(dist, checks=False)

    # Single-linkage clustering → leaf ordering
    link = linkage(condensed, method="single")
    sort_ix = list(leaves_list(link))      # reordered asset indices

    # Inverse-variance weight for a sub-cluster
    def _cluster_var(idx_list):
        sub = cov[np.ix_(idx_list, idx_list)]
        ivp = 1.0 / np.maximum(np.diag(sub), 1e-12)
        ivp /= ivp.sum()
        return float(ivp @ sub @ ivp)

    # Recursive bisection: split each cluster and scale weights proportionally
    weights = np.ones(n)
    cluster_list = [sort_ix]

    while cluster_list:
        next_list = []
        for c in cluster_list:
            if len(c) <= 1:
                continue
            mid = len(c) // 2
            c_l, c_r = c[:mid], c[mid:]
            v_l = _cluster_var(c_l)
            v_r = _cluster_var(c_r)
            alpha = 1 - v_l / (v_l + v_r + 1e-12)
            weights[c_l] *= alpha
            weights[c_r] *= 1 - alpha
            if len(c_l) > 1:
                next_list.append(c_l)
            if len(c_r) > 1:
                next_list.append(c_r)
        cluster_list = next_list

    weights /= weights.sum()

    sigma_p = float(np.sqrt(max(weights @ cov @ weights, 1e-12)))
    rc = weights * (cov @ weights) / sigma_p

    return {
        "tickers": tickers,
        "weights": {tickers[i]: float(weights[i]) for i in range(n)},
        "risk_contributions": {tickers[i]: float(rc[i] / rc.sum()) for i in range(n)},
        "portfolio_vol": sigma_p,
    }


# =============================================================================
# QUANT ENGINE v2 — ADVANCED EXECUTION, RISK & VALIDATION
# Covers features #1-#40 from the advanced roadmap.
# All functions are pure-computation (no Streamlit calls) so they can be
# used independently or wired into app_context_runtime.
# =============================================================================


def compute_rebalancing_bands(
    df: pd.DataFrame,
    target_weights: dict,
    total_value: float,
    band_tolerance: float = 0.02,
    min_trade_pct: float = 0.005,
    min_notional: float = 100.0,
    max_turnover: float = 0.30,
    tc_bps: float = 10.0,
) -> dict:
    """Band-based rebalancing with turnover cap, notional floor, and order efficiency.

    Implements: band rebalancing (#3), min execution threshold (#2/#13),
    turnover control (#9), trade batching / cash accumulation (#14),
    gross vs executable-net weight comparison (#32), order prioritisation
    by edge-to-cost ratio (#38), friction threshold (#39).

    Returns
    -------
    dict with keys:
      'trades'       : DataFrame — per-ticker decision table
      'turnover'     : float    — expected one-way turnover fraction
      'n_executable' : int      — trades that passed all filters
      'suppressed'   : list     — tickers blocked by filters
    """
    empty = {"trades": pd.DataFrame(), "turnover": 0.0, "n_executable": 0, "suppressed": []}
    if df is None or df.empty or not target_weights or total_value <= 0:
        return empty

    rows = []
    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        cur_val = float(row.get("Value", 0.0))
        cur_w = cur_val / total_value
        tgt_w = float(target_weights.get(ticker, 0.0))
        drift = cur_w - tgt_w                           # + = overweight
        delta_val = (tgt_w - cur_w) * total_value       # + = need to buy
        tc_cost = abs(delta_val) * tc_bps / 10000

        in_band = abs(drift) <= band_tolerance
        below_min = abs(delta_val) / total_value < min_trade_pct
        below_notional = abs(delta_val) < min_notional
        filtered = in_band or below_min or below_notional

        # Priority = drift magnitude adjusted by TC cost (edge-to-friction ratio)
        priority = abs(drift) / max(tc_bps / 10000, 1e-9) if not filtered else 0.0

        if in_band:
            action = "HOLD (in band)"
        elif below_notional or below_min:
            action = "HOLD (min size)"
        else:
            action = "BUY" if delta_val > 0 else "SELL"

        rows.append({
            "Ticker": ticker,
            "Current W%": round(cur_w * 100, 2),
            "Target W%": round(tgt_w * 100, 2),
            "Drift W%": round(drift * 100, 2),
            "Gross Δ": round(delta_val, 2),
            "Filtered": filtered,
            "Action": action,
            "Est. TC": round(tc_cost, 2),
            "Priority": round(priority, 4),
        })

    trades = pd.DataFrame(rows).sort_values("Priority", ascending=False).reset_index(drop=True)
    trades["Net Δ"] = 0.0

    # Apply max-turnover cap: execute highest-priority trades first
    cum_to = 0.0
    for i in trades.index:
        if trades.at[i, "Filtered"]:
            continue
        to_i = abs(trades.at[i, "Gross Δ"]) / total_value
        if cum_to + to_i > max_turnover:
            trades.at[i, "Filtered"] = True
            trades.at[i, "Action"] = "HOLD (turnover cap)"
        else:
            trades.at[i, "Net Δ"] = trades.at[i, "Gross Δ"]
            cum_to += to_i

    # Executable weight: what we'd actually reach after all filters
    trades["Executable W%"] = trades.apply(
        lambda r: r["Target W%"] if not r["Filtered"] else r["Current W%"], axis=1
    )

    return {
        "trades": trades,
        "turnover": round(cum_to, 4),
        "n_executable": int((~trades["Filtered"]).sum()),
        "suppressed": trades[trades["Filtered"]]["Ticker"].tolist(),
    }


def compute_net_alpha_after_costs(
    expected_returns: pd.Series,
    current_weights: pd.Series,
    target_weights: pd.Series,
    total_value: float,
    tc_bps: float = 10.0,
    holding_period_days: int = 252,
    min_edge_bps: float = 5.0,
) -> pd.DataFrame:
    """Net alpha after transaction costs with automatic trade suppression.

    Implements: alpha-net-of-costs estimation (#10), auto-suppression of
    trades with negative net alpha (#4), no-trade rule when edge is
    insufficient (#25).

    The TC drag is annualised by spreading the one-way cost over the
    assumed holding period.  Trades where net alpha < min_edge_bps are
    flagged 'Trade=False' so upstream code can skip them.
    """
    if expected_returns is None or expected_returns.empty:
        return pd.DataFrame()

    rows = []
    for t in expected_returns.index:
        er = float(expected_returns[t])
        cw = float(current_weights[t]) if t in current_weights.index else 0.0
        tw = float(target_weights[t]) if t in target_weights.index else 0.0
        trade_val = abs(tw - cw) * total_value

        # Annualise TC: one-way cost amortised over holding period
        tc_annual_frac = (trade_val * tc_bps / 10000) / max(total_value, 1) * (252 / max(holding_period_days, 1))
        gross_bps = er * 10000
        tc_bps_val = tc_annual_frac * 10000
        net_bps = gross_bps - tc_bps_val

        rows.append({
            "Ticker": t,
            "Expected Return": round(er, 4),
            "Gross Alpha (bps)": round(gross_bps, 1),
            "TC Drag (bps)": round(tc_bps_val, 1),
            "Net Alpha (bps)": round(net_bps, 1),
            "Has Edge": net_bps >= min_edge_bps,
            "Trade": net_bps >= min_edge_bps and abs(tw - cw) > 1e-4,
        })

    return pd.DataFrame(rows).sort_values("Net Alpha (bps)", ascending=False).reset_index(drop=True)


def compute_after_tax_drag(
    portfolio_returns: pd.Series,
    transactions_df: pd.DataFrame,
    current_prices: dict,
    st_rate: float = 0.35,
    lt_rate: float = 0.15,
    dividend_rate: float = 0.15,
) -> dict:
    """After-tax return drag from capital gains and dividends.

    Implements: tax drag module (#11).

    Computes cost basis and holding period per ticker from the transactions
    log, then estimates the tax liability on unrealised gains and
    expected dividend income.  Short-term (< 365 days) vs long-term
    rates are applied automatically.
    """
    if portfolio_returns is None or portfolio_returns.empty:
        return {}
    if transactions_df is None or transactions_df.empty:
        return {}

    r = pd.to_numeric(portfolio_returns, errors="coerce").dropna()
    ann_return = float((1 + r).prod() ** (252 / max(len(r), 1)) - 1)

    tx = transactions_df.copy()
    tx["date"] = pd.to_datetime(tx["date"], errors="coerce")
    tx["shares"] = pd.to_numeric(tx["shares"], errors="coerce").fillna(0)
    tx["price"] = pd.to_numeric(tx["price"], errors="coerce").fillna(0)
    tx = tx.dropna(subset=["date"])
    today = pd.Timestamp.now().normalize()

    cost_basis: dict[str, float] = {}
    shares_held: dict[str, float] = {}
    first_buy: dict[str, pd.Timestamp] = {}

    for _, row in tx.sort_values("date").iterrows():
        t = str(row.get("ticker", row.get("Ticker", "")))
        typ = str(row.get("type", "")).upper()
        sh = float(row["shares"])
        px = float(row["price"])
        if typ == "BUY":
            cost_basis[t] = cost_basis.get(t, 0) + sh * px
            shares_held[t] = shares_held.get(t, 0) + sh
            if t not in first_buy:
                first_buy[t] = row["date"]
        elif typ == "SELL":
            held = shares_held.get(t, 0)
            if held > 0:
                basis_per_share = cost_basis.get(t, 0) / held
                cost_basis[t] = max(0, cost_basis.get(t, 0) - sh * basis_per_share)
                shares_held[t] = max(0, held - sh)

    tax_on_gains = 0.0
    total_unrealised = 0.0
    lt_tickers, st_tickers = [], []

    for t, sh in shares_held.items():
        if sh <= 0:
            continue
        px = float((current_prices or {}).get(t, 0))
        if px <= 0:
            continue
        cur_val = sh * px
        basis = cost_basis.get(t, 0)
        gain = cur_val - basis
        days = (today - first_buy[t]).days if t in first_buy else 0
        rate = lt_rate if days >= 365 else st_rate
        if gain > 0:
            tax_on_gains += gain * rate
        total_unrealised += gain
        (lt_tickers if days >= 365 else st_tickers).append(t)

    effective_tax_drag = tax_on_gains / max(abs(total_unrealised), 1.0) if total_unrealised != 0 else 0.0
    after_tax_return = ann_return - effective_tax_drag

    return {
        "gross_annual_return": round(ann_return, 4),
        "after_tax_return": round(after_tax_return, 4),
        "estimated_tax_liability": round(tax_on_gains, 2),
        "total_unrealised_gain": round(total_unrealised, 2),
        "effective_tax_drag": round(effective_tax_drag, 4),
        "lt_eligible": lt_tickers,
        "st_exposure": st_tickers,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def compute_liquidity_score(
    tickers: list,
    position_values: dict,
    adv_participation_cap: float = 0.10,
    min_notional: float = 500.0,
) -> pd.DataFrame:
    """ADV-based liquidity scoring and market-depth filter.

    Implements: liquidity and market-depth filter (#12), minimum
    notional per asset (#13).

    Scores each position by days-to-liquidate (position / (ADV * cap))
    and flags positions that fail the min-notional floor.
    """
    import yfinance as yf

    if not tickers:
        return pd.DataFrame()

    rows = []
    for ticker in tickers:
        pos_val = float((position_values or {}).get(ticker, 0))
        try:
            hist = yf.Ticker(ticker).history(period="30d")
            if hist.empty:
                adv = 0.0
            else:
                adv = float((hist["Close"] * hist["Volume"]).mean())
        except Exception:
            adv = 0.0

        daily_capacity = adv * adv_participation_cap
        days_to_liquidate = pos_val / daily_capacity if daily_capacity > 0 else float("inf")
        liquidity_score = max(0.0, 1.0 - min(days_to_liquidate / 5, 1.0))  # 1=liquid, 0=illiquid

        rows.append({
            "Ticker": ticker,
            "Position Value": round(pos_val, 2),
            "30d ADV ($)": round(adv, 0),
            "Daily Capacity ($)": round(daily_capacity, 0),
            "Days to Liquidate": round(days_to_liquidate, 1) if np.isfinite(days_to_liquidate) else None,
            "Liquidity Score": round(liquidity_score, 3),
            "Passes Min Notional": pos_val >= min_notional,
            "Flag": "OK" if (np.isfinite(days_to_liquidate) and days_to_liquidate <= 5 and pos_val >= min_notional) else "REVIEW",
        })

    return pd.DataFrame(rows).sort_values("Liquidity Score", ascending=False).reset_index(drop=True)


def compute_model_agreement_score(
    optimizer_weights: dict,
    asset_returns: pd.DataFrame,
    risk_free_rate: float = 0.045,
) -> dict:
    """Signal agreement, collinearity detection, and fail-safe conflict rules.

    Implements: model agreement / signal dispersion (#20), collinearity
    detection between signals (#18), model complexity penalty (#19),
    fail-safe rules when signals conflict (#37).

    Compares weight vectors from multiple optimizers (Max Sharpe, Min Vol,
    Min CVaR, HRP, ERC).  Outputs a dispersion score and per-ticker
    consensus weight.  High dispersion → reduce position size or hold.
    """
    if not optimizer_weights or asset_returns is None or asset_returns.empty:
        return {}

    models = {k: v for k, v in optimizer_weights.items() if v is not None}
    if len(models) < 2:
        return {"agreement_score": 1.0, "consensus_weights": {}, "high_conflict_tickers": []}

    tickers = list(asset_returns.columns)
    weight_matrix = []
    for name, w in models.items():
        if isinstance(w, np.ndarray):
            vec = dict(zip(tickers, w))
        elif isinstance(w, dict):
            vec = w
        else:
            continue
        weight_matrix.append([float(vec.get(t, 0)) for t in tickers])

    if not weight_matrix:
        return {}

    wm = np.array(weight_matrix)                     # n_models × n_assets
    mean_w = wm.mean(axis=0)
    std_w = wm.std(axis=0)

    # Agreement score: 1 = full consensus, 0 = maximum disagreement
    # Measured as 1 - mean(coefficient of variation across tickers)
    cv = std_w / np.where(mean_w > 1e-6, mean_w, 1.0)
    agreement_score = float(max(0.0, 1.0 - cv.mean()))

    # Collinearity check: pairwise correlation of weight vectors
    corr_pairs = {}
    model_names = list(models.keys())
    for i in range(len(model_names)):
        for j in range(i + 1, len(model_names)):
            c = float(np.corrcoef(wm[i], wm[j])[0, 1])
            corr_pairs[f"{model_names[i]} / {model_names[j]}"] = round(c, 3)

    # High-conflict tickers: CV > 0.5 (signals disagree strongly)
    high_conflict = [tickers[i] for i, v in enumerate(cv) if v > 0.5]

    # Complexity penalty: reward models that use fewer non-trivial positions
    complexity_penalties = {}
    for name, row in zip(model_names, wm):
        n_significant = int((row > 0.02).sum())
        complexity_penalties[name] = round(n_significant / max(len(tickers), 1), 3)

    # Consensus: mean weight, zeroed where conflict is too high
    consensus = {tickers[i]: round(float(mean_w[i]), 4) for i in range(len(tickers))}
    for t in high_conflict:
        consensus[t] = round(consensus[t] * 0.5, 4)   # halve weight under conflict

    return {
        "agreement_score": round(agreement_score, 3),
        "consensus_weights": consensus,
        "weight_std_by_ticker": {tickers[i]: round(float(std_w[i]), 4) for i in range(len(tickers))},
        "model_correlations": corr_pairs,
        "high_conflict_tickers": high_conflict,
        "complexity_penalties": complexity_penalties,
        "n_models": len(models),
    }


def compute_expected_return_bands(
    asset_returns: pd.DataFrame,
    n_bootstrap: int = 500,
    seed: int = 42,
    confidence: float = 0.90,
) -> pd.DataFrame:
    """Bootstrap confidence bands on expected returns and Sharpe ratios.

    Implements: parameter uncertainty in MC (#17), confidence bands on
    expected returns (#21), robust optimization sensitivity (#34).

    Resamples the return history to produce (lower, median, upper) bounds
    on annualised expected return and Sharpe per asset.  Wide bands signal
    unreliable estimates — downstream code should apply shrinkage or
    reduce position sizing accordingly.
    """
    if asset_returns is None or asset_returns.empty or len(asset_returns) < 30:
        return pd.DataFrame()

    rng = np.random.default_rng(seed)
    r = asset_returns.dropna(how="all").values
    T, n = r.shape
    alpha = (1 - confidence) / 2

    boot_means = np.zeros((n_bootstrap, n))
    boot_vols = np.zeros((n_bootstrap, n))
    for b in range(n_bootstrap):
        idx = rng.integers(0, T, size=T)
        sample = r[idx]
        boot_means[b] = sample.mean(axis=0) * 252
        boot_vols[b] = sample.std(axis=0) * np.sqrt(252)

    boot_sharpe = np.where(boot_vols > 0, boot_means / boot_vols, 0.0)

    rows = []
    for i, t in enumerate(asset_returns.columns):
        lo_r, med_r, hi_r = np.percentile(boot_means[:, i], [alpha * 100, 50, (1 - alpha) * 100])
        lo_s, med_s, hi_s = np.percentile(boot_sharpe[:, i], [alpha * 100, 50, (1 - alpha) * 100])
        band_width = hi_r - lo_r
        # Reliability flag: wide band relative to median estimate = unreliable
        reliable = band_width < abs(med_r) * 2 if med_r != 0 else False
        rows.append({
            "Ticker": t,
            "E[Return] Low": round(lo_r, 4),
            "E[Return] Median": round(med_r, 4),
            "E[Return] High": round(hi_r, 4),
            "Band Width": round(band_width, 4),
            "Sharpe Low": round(lo_s, 3),
            "Sharpe Median": round(med_s, 3),
            "Sharpe High": round(hi_s, 3),
            "Reliable": reliable,
        })

    return pd.DataFrame(rows).sort_values("E[Return] Median", ascending=False).reset_index(drop=True)


def explain_bl_posterior(
    bl_result: dict,
    views: list,
) -> pd.DataFrame:
    """Decompose Black-Litterman posterior into prior vs view contributions.

    Implements: BL explainability (#26).

    For each asset, shows how much the posterior expected return is pulled
    away from the equilibrium (prior) by the investor views.  The 'View Pull'
    column measures the absolute shift attributable to views.
    """
    if bl_result is None or not bl_result:
        return pd.DataFrame()

    posterior = bl_result.get("posterior_returns")
    equilibrium = bl_result.get("equilibrium_returns")
    if posterior is None or equilibrium is None:
        return pd.DataFrame()

    tickers = bl_result.get("tickers", list(posterior.index))
    view_map = {v["ticker"]: v for v in (views or [])}

    rows = []
    for t in tickers:
        eq = float(equilibrium.get(t, 0))
        post = float(posterior.get(t, 0))
        pull = post - eq
        has_view = t in view_map
        view_ret = float(view_map[t]["expected_return"]) if has_view else None
        view_conf = float(view_map[t].get("confidence", 0.5)) if has_view else None

        rows.append({
            "Ticker": t,
            "Equilibrium Return": round(eq, 4),
            "Posterior Return": round(post, 4),
            "View Pull": round(pull, 4),
            "Has View": has_view,
            "View Expected Return": round(view_ret, 4) if view_ret is not None else None,
            "View Confidence": round(view_conf, 2) if view_conf is not None else None,
            "Dominant": "VIEW" if abs(pull) > abs(eq) * 0.5 else "PRIOR",
        })

    return pd.DataFrame(rows).sort_values("View Pull", key=abs, ascending=False).reset_index(drop=True)


def compute_tracking_error_budget(
    asset_returns: pd.DataFrame,
    portfolio_weights: pd.Series,
    benchmark_returns: pd.Series,
    te_budget: float = 0.10,
) -> dict:
    """Tracking error budget allocation across assets.

    Implements: tracking error budget (#27).

    Decomposes total active risk (tracking error) into per-asset
    contributions, then reports each asset's share of the TE budget
    and whether the total is within the policy limit.
    """
    if asset_returns is None or asset_returns.empty or portfolio_weights is None:
        return {}

    tickers = [t for t in portfolio_weights.index if t in asset_returns.columns]
    if not tickers:
        return {}

    w = portfolio_weights[tickers].values.astype(float)
    if w.sum() <= 0:
        return {}
    w = w / w.sum()

    cov = _shrunk_cov(asset_returns[tickers])
    port_r = (asset_returns[tickers] * w).sum(axis=1)

    if benchmark_returns is not None and not benchmark_returns.empty:
        aligned = pd.concat([port_r.rename("P"), benchmark_returns.rename("B")], axis=1).dropna()
        active_r = aligned["P"] - aligned["B"]
    else:
        active_r = port_r.dropna()

    te = float(active_r.std() * np.sqrt(252)) if len(active_r) > 1 else 0.0

    # Marginal contribution to active variance per asset (simplified: uses cov matrix)
    port_vol = float(np.sqrt(max(w @ cov @ w, 1e-12)))
    marginal = (cov @ w) / port_vol
    component_te = w * marginal
    total_component = component_te.sum()
    te_share = component_te / max(total_component, 1e-12)

    budget_used = te / te_budget if te_budget > 0 else 0.0

    return {
        "total_te": round(te, 4),
        "te_budget": te_budget,
        "budget_used_pct": round(budget_used * 100, 1),
        "within_budget": te <= te_budget,
        "per_asset": {
            tickers[i]: {
                "te_contribution": round(float(component_te[i]), 4),
                "te_share_pct": round(float(te_share[i]) * 100, 2),
            }
            for i in range(len(tickers))
        },
    }


def compute_walk_forward_metrics(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series | None,
    risk_free_rate: float = 0.045,
    n_folds: int = 4,
) -> dict:
    """Walk-forward (out-of-sample) Sharpe and alpha validation.

    Implements: walk-forward validation and out-of-sample backtesting (#8).

    Splits the return history into n_folds equal windows and reports
    Sharpe ratio and annualised alpha for each fold plus the OOS mean.
    Consistent out-of-sample Sharpe > 0 suggests the strategy has
    genuine edge; fold-to-fold variance measures robustness.
    """
    if portfolio_returns is None or len(portfolio_returns) < 60:
        return {}

    r = pd.to_numeric(portfolio_returns, errors="coerce").dropna()
    fold_size = len(r) // n_folds
    if fold_size < 10:
        return {}

    folds = []
    for i in range(n_folds):
        start = i * fold_size
        end = start + fold_size if i < n_folds - 1 else len(r)
        fold_r = r.iloc[start:end]
        ann_ret = float((1 + fold_r).prod() ** (252 / max(len(fold_r), 1)) - 1)
        vol = float(fold_r.std() * np.sqrt(252))
        sharpe = (ann_ret - risk_free_rate) / vol if vol > 0 else 0.0

        alpha = ann_ret
        if benchmark_returns is not None and not benchmark_returns.empty:
            b = pd.to_numeric(benchmark_returns, errors="coerce").dropna()
            b_fold = b.reindex(fold_r.index).dropna()
            if len(b_fold) > 2:
                b_ret = float((1 + b_fold).prod() ** (252 / max(len(b_fold), 1)) - 1)
                cov_arr = np.cov(fold_r.reindex(b_fold.index).dropna().values,
                                 b_fold.reindex(fold_r.index).dropna().values)
                beta = float(cov_arr[0, 1] / max(cov_arr[1, 1], 1e-12))
                alpha = ann_ret - (risk_free_rate + beta * (b_ret - risk_free_rate))

        folds.append({
            "fold": i + 1,
            "start": str(fold_r.index[0].date()) if hasattr(fold_r.index[0], "date") else str(fold_r.index[0]),
            "end": str(fold_r.index[-1].date()) if hasattr(fold_r.index[-1], "date") else str(fold_r.index[-1]),
            "ann_return": round(ann_ret, 4),
            "volatility": round(vol, 4),
            "sharpe": round(sharpe, 3),
            "alpha": round(alpha, 4),
        })

    sharpes = [f["sharpe"] for f in folds]
    alphas = [f["alpha"] for f in folds]
    return {
        "folds": folds,
        "oos_mean_sharpe": round(float(np.mean(sharpes)), 3),
        "oos_sharpe_std": round(float(np.std(sharpes)), 3),
        "oos_mean_alpha": round(float(np.mean(alphas)), 4),
        "consistent_edge": all(s > 0 for s in sharpes),
        "n_positive_folds": sum(1 for s in sharpes if s > 0),
    }


def compute_regime_probabilities(
    portfolio_returns: pd.Series,
    ewma_lambda: float = 0.94,
    flip_damping: int = 5,
) -> dict:
    """Bayesian-smoothed regime probabilities with false-flip suppression.

    Implements: regime probability calibration (#5), strategic/tactical/
    execution layer separation (#6), false regime-flip monitoring (#29).

    Uses EWMA volatility to estimate the current regime, then applies
    a Bayesian update to compute the probability of being in each regime.
    A flip-damping window suppresses transient regime changes.

    Returns strategic layer (regime + probability), tactical layer
    (suggested allocation tilt), and execution flags.
    """
    if portfolio_returns is None or len(portfolio_returns) < 21:
        return {}

    r = pd.to_numeric(portfolio_returns, errors="coerce").dropna()
    r2 = r.values ** 2
    n = len(r2)
    ewma_var = np.empty(n)
    ewma_var[0] = r2[0]
    for i in range(1, n):
        ewma_var[i] = ewma_lambda * ewma_var[i - 1] + (1 - ewma_lambda) * r2[i]
    ann_vol = np.sqrt(ewma_var) * np.sqrt(252)

    # Regime thresholds (annualised vol)
    REGIMES = [("LOW", 0, 0.10), ("NORMAL", 0.10, 0.20), ("HIGH", 0.20, 0.35), ("CRISIS", 0.35, 9)]
    current_vol = float(ann_vol[-1])

    # Compute rolling regime labels with damping
    labels = []
    for v in ann_vol:
        for name, lo, hi in REGIMES:
            if lo <= v < hi:
                labels.append(name)
                break

    # Flip suppression: require flip_damping consecutive days before accepting
    smoothed = list(labels)
    for i in range(flip_damping, n):
        window = labels[i - flip_damping: i + 1]
        if len(set(window)) > 1:
            smoothed[i] = smoothed[i - 1]   # hold previous regime

    current_regime = smoothed[-1]

    # Empirical regime probabilities (last 126 days)
    recent = smoothed[-126:]
    probs = {name: round(recent.count(name) / len(recent), 3) for name, _, _ in REGIMES}

    # Regime flip detection: did regime change in last flip_damping days?
    recent_flip = len(set(smoothed[-flip_damping:])) > 1

    # Strategic layer: target allocation tilt by regime
    equity_tilt = {"LOW": 0.10, "NORMAL": 0.0, "HIGH": -0.10, "CRISIS": -0.20}[current_regime]
    bond_tilt   = {"LOW": -0.05, "NORMAL": 0.0, "HIGH": 0.05, "CRISIS": 0.15}[current_regime]

    # Tactical layer: confidence in regime signal
    regime_confidence = probs.get(current_regime, 0.5)
    tactical_active = regime_confidence > 0.60   # only act if high confidence

    # Execution layer: suppress trades during regime transitions
    execution_hold = recent_flip and regime_confidence < 0.70

    return {
        "current_regime": current_regime,
        "current_vol": round(current_vol, 4),
        "regime_probabilities": probs,
        "regime_confidence": round(regime_confidence, 3),
        "recent_flip": recent_flip,
        # Strategic layer
        "strategic": {
            "equity_tilt": equity_tilt,
            "bond_tilt": bond_tilt,
        },
        # Tactical layer
        "tactical": {
            "active": tactical_active,
            "rationale": f"{current_regime} regime at {regime_confidence:.0%} confidence",
        },
        # Execution layer
        "execution": {
            "hold_trades": execution_hold,
            "reason": "Regime transition in progress — wait for stabilisation" if execution_hold else "OK to execute",
        },
    }


def compute_dynamic_weight_caps(
    asset_returns: pd.DataFrame,
    current_weights: pd.Series,
    base_max_weight: float = 0.40,
    correlation_penalty: float = 0.10,
    top_n_threshold: float = 0.50,
) -> dict:
    """Adaptive per-asset weight caps based on correlation and concentration.

    Implements: dynamic weight caps by concentration (#22), control of
    excessive dependence on top holdings (#24).

    Assets that are highly correlated with others get a tighter cap
    (adding one adds redundant risk).  If the top-N holdings already
    exceed top_n_threshold of the portfolio, their caps are further
    reduced to limit key-person-equivalent risk.
    """
    if asset_returns is None or asset_returns.empty:
        return {}

    tickers = list(asset_returns.columns)
    corr = asset_returns.corr().values
    n = len(tickers)

    # Mean absolute pairwise correlation for each asset (proxy for redundancy)
    mean_pairwise_corr = np.array([
        np.mean(np.abs(corr[i, [j for j in range(n) if j != i]]))
        for i in range(n)
    ])

    # Top-N concentration check
    sorted_w = sorted([(float(current_weights.get(t, 0)), t) for t in tickers], reverse=True)
    cumulative = 0.0
    top_heavy_tickers = set()
    for w, t in sorted_w:
        if cumulative >= top_n_threshold:
            break
        cumulative += w
        top_heavy_tickers.add(t)

    caps = {}
    for i, t in enumerate(tickers):
        cap = base_max_weight
        # Penalise highly correlated assets
        cap -= mean_pairwise_corr[i] * correlation_penalty
        # Further reduce cap for top-heavy tickers if concentration is already high
        if t in top_heavy_tickers and cumulative >= top_n_threshold:
            cap *= 0.85
        caps[t] = round(max(cap, 0.05), 4)   # floor at 5%

    return {
        "caps": caps,
        "top_heavy_tickers": list(top_heavy_tickers),
        "top_n_concentration": round(cumulative, 4),
        "mean_pairwise_corr": {tickers[i]: round(float(mean_pairwise_corr[i]), 3) for i in range(n)},
    }


def compute_expected_drawdown_profile(
    portfolio_returns: pd.Series,
    current_value: float,
    horizons_years: tuple = (1, 3, 5),
    n_sims: int = 1000,
    seed: int = 42,
) -> dict:
    """Expected max drawdown and recovery time from Monte Carlo paths.

    Implements: drawdown report with expected drawdown and recovery time (#40).

    Runs bootstrap simulations and computes, for each horizon:
      - Expected (median) max drawdown
      - 95th-percentile worst drawdown
      - Median recovery time in months (months from trough to new ATH)
    """
    if portfolio_returns is None or len(portfolio_returns) < 60 or current_value <= 0:
        return {}

    rng = np.random.default_rng(seed)
    r = pd.to_numeric(portfolio_returns, errors="coerce").dropna().values
    result = {}

    for h in horizons_years:
        n_months = h * 12
        n_days = h * 252
        paths = np.zeros((n_sims, n_days + 1))
        paths[:, 0] = current_value

        sampled_days = rng.choice(r, size=(n_sims, n_days), replace=True)
        for d in range(n_days):
            paths[:, d + 1] = paths[:, d] * (1 + sampled_days[:, d])

        # Max drawdown per path
        max_dds = np.zeros(n_sims)
        recovery_months = np.zeros(n_sims)
        for s in range(n_sims):
            path = paths[s]
            peak = path[0]
            max_dd = 0.0
            trough_idx = 0
            for d in range(1, len(path)):
                if path[d] > peak:
                    peak = path[d]
                dd = (path[d] - peak) / peak
                if dd < max_dd:
                    max_dd = dd
                    trough_idx = d
            max_dds[s] = max_dd

            # Recovery: months from trough to new ATH
            if trough_idx > 0 and max_dd < -0.01:
                trough_val = path[trough_idx]
                peak_at_trough = path[:trough_idx + 1].max()
                recovered = False
                for d in range(trough_idx + 1, len(path)):
                    if path[d] >= peak_at_trough:
                        recovery_months[s] = (d - trough_idx) / 21  # trading days → months
                        recovered = True
                        break
                if not recovered:
                    recovery_months[s] = n_months  # still in drawdown at horizon

        result[h] = {
            "expected_max_dd": round(float(np.median(max_dds)), 4),
            "worst_dd_p95": round(float(np.percentile(max_dds, 95)), 4),
            "median_recovery_months": round(float(np.median(recovery_months)), 1),
            "p90_recovery_months": round(float(np.percentile(recovery_months, 90)), 1),
            "prob_drawdown_gt_10pct": round(float((max_dds < -0.10).mean()), 3),
            "prob_drawdown_gt_20pct": round(float((max_dds < -0.20).mean()), 3),
        }

    return result


def compute_model_drift_score(
    asset_returns: pd.DataFrame,
    risk_free_rate: float = 0.045,
    short_window: int = 63,
    long_window: int = 252,
) -> dict:
    """Rolling parameter drift monitoring and experiment tracking.

    Implements: model drift alerts (#28), false regime-flip monitoring (#29),
    lightweight signal versioning / experiment tracking (#35).

    Compares short-window vs long-window estimates of mean return,
    volatility, and Sharpe for each asset.  Large deviations flag
    parameter instability.  Returns a drift score per asset and an
    overall engine-health flag.
    """
    if asset_returns is None or asset_returns.empty or len(asset_returns) < long_window:
        return {}

    r = asset_returns.dropna(how="all")
    tickers = list(r.columns)

    rows = {}
    for t in tickers:
        s = r[t].dropna()
        if len(s) < short_window:
            continue

        short_ret = s.iloc[-short_window:]
        long_ret = s.iloc[-long_window:]

        mu_s = float(short_ret.mean() * 252)
        mu_l = float(long_ret.mean() * 252)
        vol_s = float(short_ret.std() * np.sqrt(252))
        vol_l = float(long_ret.std() * np.sqrt(252))
        sr_s = (mu_s - risk_free_rate) / vol_s if vol_s > 0 else 0.0
        sr_l = (mu_l - risk_free_rate) / vol_l if vol_l > 0 else 0.0

        return_drift = abs(mu_s - mu_l)
        vol_drift = abs(vol_s - vol_l)
        sharpe_drift = abs(sr_s - sr_l)

        # Composite drift score: normalised by long-window estimates
        drift_score = (
            return_drift / max(abs(mu_l), 0.01) * 0.4
            + vol_drift / max(vol_l, 0.01) * 0.3
            + sharpe_drift / max(abs(sr_l), 0.01) * 0.3
        )

        rows[t] = {
            "mu_short": round(mu_s, 4),
            "mu_long": round(mu_l, 4),
            "vol_short": round(vol_s, 4),
            "vol_long": round(vol_l, 4),
            "sharpe_short": round(sr_s, 3),
            "sharpe_long": round(sr_l, 3),
            "drift_score": round(drift_score, 3),
            "alert": drift_score > 0.50,
        }

    if not rows:
        return {}

    # Portfolio-level engine health
    scores = [v["drift_score"] for v in rows.values()]
    n_alerts = sum(1 for v in rows.values() if v["alert"])

    return {
        "per_asset": rows,
        "mean_drift_score": round(float(np.mean(scores)), 3),
        "n_alerts": n_alerts,
        "engine_healthy": n_alerts == 0,
        "snapshot_ts": str(pd.Timestamp.now().date()),  # lightweight versioning stamp
    }


def benchmark_naive_portfolios(
    asset_returns: pd.DataFrame,
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series | None,
    risk_free_rate: float = 0.045,
) -> pd.DataFrame:
    """Compare portfolio vs naive model portfolios and simple benchmarks.

    Implements: benchmarking against simple portfolios and model baselines (#7).

    Models compared:
      1/N          Equal-weight buy-and-hold
      Min-Vol      Minimum variance (unconstrained)
      Max-Sharpe   Maximum Sharpe (unconstrained)
      60/40        60% first asset + 40% last asset (equity/bond proxy)
      Benchmark    Supplied benchmark (e.g. VOO)
      Portfolio    Actual portfolio
    """
    if asset_returns is None or asset_returns.empty or portfolio_returns is None:
        return pd.DataFrame()

    r = asset_returns.dropna(how="all")
    tickers = list(r.columns)
    n = len(tickers)
    if n < 2:
        return pd.DataFrame()

    def _stats(ret_series: pd.Series, name: str) -> dict:
        s = pd.to_numeric(ret_series, errors="coerce").dropna()
        if len(s) < 20:
            return {}
        ann_r = float((1 + s).prod() ** (252 / len(s)) - 1)
        vol = float(s.std() * np.sqrt(252))
        sr = (ann_r - risk_free_rate) / vol if vol > 0 else 0.0
        cum = (1 + s).prod() - 1
        rolling_peak = (1 + s).cumprod().cummax()
        dd = ((1 + s).cumprod() / rolling_peak - 1).min()
        return {"Model": name, "Ann. Return": round(ann_r, 4), "Volatility": round(vol, 4),
                "Sharpe": round(sr, 3), "Cum. Return": round(cum, 4), "Max DD": round(dd, 4)}

    results = []

    # 1/N
    eq_w = np.ones(n) / n
    eq_r = (r * eq_w).sum(axis=1)
    stats = _stats(eq_r, "1/N Equal Weight")
    if stats:
        results.append(stats)

    # Min-Vol (unconstrained, closed-form inverse covariance)
    try:
        cov = _shrunk_cov(r)
        cov_inv = np.linalg.pinv(cov)
        ones = np.ones(n)
        w_mv = (cov_inv @ ones) / (ones @ cov_inv @ ones)
        w_mv = np.clip(w_mv, 0, None); w_mv /= w_mv.sum()
        mv_r = (r * w_mv).sum(axis=1)
        stats = _stats(mv_r, "Min-Vol (unconstrained)")
        if stats:
            results.append(stats)
    except Exception:
        pass

    # Max-Sharpe (unconstrained Markowitz tangency)
    try:
        mu = r.mean().values * 252
        excess = mu - risk_free_rate
        w_ms = (cov_inv @ excess) / (ones @ cov_inv @ excess)
        w_ms = np.clip(w_ms, 0, None)
        if w_ms.sum() > 0:
            w_ms /= w_ms.sum()
            ms_r = (r * w_ms).sum(axis=1)
            stats = _stats(ms_r, "Max-Sharpe (unconstrained)")
            if stats:
                results.append(stats)
    except Exception:
        pass

    # Actual portfolio
    stats = _stats(portfolio_returns, "Your Portfolio")
    if stats:
        results.append(stats)

    # Benchmark
    if benchmark_returns is not None and not benchmark_returns.empty:
        stats = _stats(benchmark_returns, "Benchmark")
        if stats:
            results.append(stats)

    if not results:
        return pd.DataFrame()

    df_out = pd.DataFrame(results).set_index("Model")
    return df_out


def compute_factor_risk_decomposition(
    asset_returns: pd.DataFrame,
    portfolio_weights: pd.Series,
    risk_free_rate: float = 0.045,
) -> dict:
    """Factor-level and position-level risk decomposition.

    Implements: attribution waterfall by model (#1), risk decomposition
    by factor and position (#15), contribution-to-return dashboard (#30).

    Decomposes portfolio variance into:
      - Systematic (factor) risk via FF3 factor proxies
      - Idiosyncratic (residual) risk
      - Per-asset contribution to total portfolio volatility
    """
    if asset_returns is None or asset_returns.empty or portfolio_weights is None:
        return {}

    tickers = [t for t in portfolio_weights.index if t in asset_returns.columns]
    if len(tickers) < 2:
        return {}

    w = portfolio_weights[tickers].values.astype(float)
    if w.sum() <= 0:
        return {}
    w = w / w.sum()

    cov = _shrunk_cov(asset_returns[tickers])
    port_var = float(w @ cov @ w)
    port_vol = float(np.sqrt(max(port_var, 1e-12)))

    # Per-asset contribution to portfolio volatility
    marginal_contrib = (cov @ w) / port_vol
    component_contrib = w * marginal_contrib
    pct_contrib = component_contrib / port_vol

    # Factor risk decomposition via FF3 proxies
    try:
        from utils import get_historical_data as _get_hist
        proxy_data = _get_hist(["IVV", "IWM", "IVE", "IVW"], period="2y")
        factor_risk: dict = {}
        if not proxy_data.empty:
            pret = proxy_data.pct_change().dropna()
            rf_d = risk_free_rate / 252
            factors = pd.concat([
                (pret["IVV"] - rf_d).rename("Mkt_RF"),
                (pret["IWM"] - pret["IVV"]).rename("SMB"),
                (pret["IVE"] - pret["IVW"]).rename("HML"),
            ], axis=1)

            port_r = (asset_returns[tickers] * w).sum(axis=1)
            aligned = pd.concat([port_r.rename("Port"), factors], axis=1).dropna()
            if len(aligned) >= 60:
                y = aligned["Port"].values - rf_d
                X = np.column_stack([np.ones(len(y)),
                                     aligned["Mkt_RF"].values,
                                     aligned["SMB"].values,
                                     aligned["HML"].values])
                betas, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
                y_hat = X @ betas
                residuals = y - y_hat
                systematic_var = float(np.var(y_hat, ddof=1)) * 252
                idio_var = float(np.var(residuals, ddof=1)) * 252
                total_var = systematic_var + idio_var
                factor_risk = {
                    "systematic_vol": round(float(np.sqrt(max(systematic_var, 0))), 4),
                    "idiosyncratic_vol": round(float(np.sqrt(max(idio_var, 0))), 4),
                    "systematic_pct": round(systematic_var / max(total_var, 1e-12), 3),
                    "idiosyncratic_pct": round(idio_var / max(total_var, 1e-12), 3),
                    "mkt_beta": round(float(betas[1]), 3),
                    "smb_beta": round(float(betas[2]), 3),
                    "hml_beta": round(float(betas[3]), 3),
                }
    except Exception:
        factor_risk = {}

    return {
        "portfolio_vol": round(port_vol, 4),
        "per_asset": {
            tickers[i]: {
                "weight": round(float(w[i]), 4),
                "vol_contribution": round(float(component_contrib[i]), 4),
                "vol_contribution_pct": round(float(pct_contrib[i]) * 100, 2),
                "marginal_risk": round(float(marginal_contrib[i]), 4),
            }
            for i in range(len(tickers))
        },
        "factor_decomposition": factor_risk,
    }


def check_mandate_compliance(
    df: pd.DataFrame,
    max_drawdown: float,
    tracking_error: float,
    var_cvar: dict,
    constraints: dict,
) -> list[dict]:
    """IPS constraint checks — returns list of PASS/FAIL rule results."""
    results = []

    def rule(name: str, description: str, value_str: str, passed: bool, threshold_str: str):
        results.append({
            "Rule": name,
            "Description": description,
            "Value": value_str,
            "Threshold": threshold_str,
            "Status": "PASS" if passed else "FAIL",
        })

    if df is not None and not df.empty:
        max_weight = float(df["Weight"].max()) if "Weight" in df.columns else 0.0
        max_conc_limit = float(constraints.get("max_single_asset", 0.40))
        rule(
            "Max Concentration",
            "No single asset may exceed the concentration limit",
            f"{max_weight * 100:.1f}%",
            max_weight <= max_conc_limit,
            f"≤ {max_conc_limit * 100:.0f}%",
        )

        bonds_weight = 0.0
        for _, row in df.iterrows():
            ticker = str(row.get("Ticker", ""))
            if bucket_for_ticker(ticker) == "Bonds":
                bonds_weight += float(row.get("Weight", 0.0))
        min_bonds_limit = float(constraints.get("min_bonds", 0.05))
        rule(
            "Min Bonds Allocation",
            "Portfolio must maintain minimum fixed income exposure",
            f"{bonds_weight * 100:.1f}%",
            bonds_weight >= min_bonds_limit,
            f"≥ {min_bonds_limit * 100:.0f}%",
        )

    # Max drawdown
    max_dd_limit = 0.25  # 25% max drawdown policy limit
    rule(
        "Max Drawdown",
        "Portfolio drawdown must remain within policy limits",
        f"{abs(max_drawdown) * 100:.1f}%",
        abs(max_drawdown) <= max_dd_limit,
        f"≤ {max_dd_limit * 100:.0f}%",
    )

    # Tracking error
    te_limit = 0.15  # 15% annualized
    rule(
        "Tracking Error",
        "Active risk relative to benchmark must be within tolerance",
        f"{tracking_error * 100:.1f}%" if tracking_error > 0 else "N/A",
        tracking_error <= te_limit or tracking_error == 0.0,
        f"≤ {te_limit * 100:.0f}%",
    )

    # VaR limit
    if var_cvar:
        var_95 = abs(float(var_cvar.get("hist_var_95", 0.0)))
        var_limit = 0.03  # 3% daily VaR 95%
        rule(
            "Daily VaR 95%",
            "One-day Value at Risk must remain within policy limits",
            f"{var_95 * 100:.2f}%",
            var_95 <= var_limit,
            f"≤ {var_limit * 100:.1f}%",
        )

    return results


# =========================
# BLOOMBERG FEATURES — ECONOMIC CALENDAR
# =========================

def get_macro_calendar() -> pd.DataFrame:
    """Return hardcoded 2026 macro events."""
    events = []
    # Fed meetings 2026
    fed_dates = [
        "2026-01-29", "2026-03-19", "2026-05-07", "2026-06-18",
        "2026-07-30", "2026-09-17", "2026-11-05", "2026-12-17",
    ]
    for d in fed_dates:
        events.append({"Date": pd.Timestamp(d), "Event": "FOMC Meeting", "Type": "Fed"})

    # CPI releases — roughly 2nd week each month
    cpi_dates = [
        "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-10",
        "2026-05-13", "2026-06-10", "2026-07-14", "2026-08-12",
        "2026-09-11", "2026-10-14", "2026-11-12", "2026-12-10",
    ]
    for d in cpi_dates:
        events.append({"Date": pd.Timestamp(d), "Event": "CPI Release", "Type": "CPI"})

    # NFP — first Friday each month (approximate)
    nfp_dates = [
        "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03",
        "2026-05-01", "2026-06-05", "2026-07-10", "2026-08-07",
        "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
    ]
    for d in nfp_dates:
        events.append({"Date": pd.Timestamp(d), "Event": "Non-Farm Payrolls", "Type": "NFP"})

    df = pd.DataFrame(events).sort_values("Date").reset_index(drop=True)
    today = pd.Timestamp.today().normalize()
    df = df[df["Date"] >= today]
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def get_upcoming_earnings(tickers: list) -> pd.DataFrame:
    """Fetch upcoming earnings dates for held tickers via yfinance."""
    import yfinance as yf
    rows = []
    for ticker in tickers:
        try:
            cal = yf.Ticker(ticker).calendar
            if cal is None:
                continue
            if isinstance(cal, dict):
                earnings_dates = cal.get("Earnings Date")
                if earnings_dates is None:
                    continue
                if isinstance(earnings_dates, (list, tuple)):
                    for ed in earnings_dates:
                        try:
                            rows.append({"Date": pd.Timestamp(ed), "Event": f"Earnings: {ticker}", "Type": "Earnings", "Ticker": ticker})
                        except Exception:
                            pass
                else:
                    try:
                        rows.append({"Date": pd.Timestamp(earnings_dates), "Event": f"Earnings: {ticker}", "Type": "Earnings", "Ticker": ticker})
                    except Exception:
                        pass
            elif isinstance(cal, pd.DataFrame):
                for col in ["Earnings Date", "earnings date"]:
                    if col in cal.index:
                        dates_val = cal.loc[col]
                        if hasattr(dates_val, "__iter__") and not isinstance(dates_val, str):
                            for ed in dates_val:
                                try:
                                    rows.append({"Date": pd.Timestamp(ed), "Event": f"Earnings: {ticker}", "Type": "Earnings", "Ticker": ticker})
                                except Exception:
                                    pass
                        else:
                            try:
                                rows.append({"Date": pd.Timestamp(dates_val), "Event": f"Earnings: {ticker}", "Type": "Earnings", "Ticker": ticker})
                            except Exception:
                                pass
        except Exception:
            pass
    if not rows:
        return pd.DataFrame(columns=["Date", "Event", "Type", "Ticker"])
    df = pd.DataFrame(rows).sort_values("Date").reset_index(drop=True)
    today = pd.Timestamp.today().normalize()
    df = df[df["Date"] >= today]
    return df


# =========================
# BLOOMBERG FEATURES — SECTOR HEATMAP
# =========================

SECTOR_ETF_MAP = {
    "XLK": "Technology",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLY": "Consumer Discr.",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLU": "Utilities",
    "XLC": "Communication",
}


@st.cache_data(ttl=300, show_spinner=False)
def build_sector_heatmap_data() -> pd.DataFrame:
    """Fetch 1-day and 5-day returns for sector ETFs."""
    import yfinance as yf
    etfs = list(SECTOR_ETF_MAP.keys())
    try:
        raw = yf.download(etfs, period="10d", auto_adjust=True, progress=False)
        if raw.empty:
            return pd.DataFrame(columns=["ETF", "Sector", "return_1d", "return_5d"])
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw.xs("Close", axis=1, level=0)
        else:
            close = raw[["Close"]] if "Close" in raw.columns else raw
        close = close.dropna(how="all")
        rows = []
        for etf in etfs:
            if etf not in close.columns:
                continue
            s = close[etf].dropna()
            if len(s) < 2:
                continue
            r1d = float(s.iloc[-1] / s.iloc[-2] - 1) if len(s) >= 2 else 0.0
            r5d = float(s.iloc[-1] / s.iloc[0] - 1) if len(s) >= 2 else 0.0
            rows.append({"ETF": etf, "Sector": SECTOR_ETF_MAP[etf], "return_1d": r1d, "return_5d": r5d})
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame(columns=["ETF", "Sector", "return_1d", "return_5d"])


# =========================
# BLOOMBERG FEATURES — NEWS FEED
# =========================

@st.cache_data(ttl=900, show_spinner=False)
def fetch_ticker_news(tickers: list, max_per_ticker: int = 3) -> list:
    """Fetch Yahoo Finance RSS headlines for each ticker."""
    import urllib.request
    import xml.etree.ElementTree as ET
    results = []
    for ticker in tickers:
        try:
            url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                content = resp.read()
            root = ET.fromstring(content)
            ns = {"dc": "http://purl.org/dc/elements/1.1/"}
            items = root.findall(".//item")
            count = 0
            for item in items:
                if count >= max_per_ticker:
                    break
                title_el = item.find("title")
                link_el = item.find("link")
                pub_el = item.find("pubDate")
                title = title_el.text.strip() if title_el is not None and title_el.text else ""
                link = link_el.text.strip() if link_el is not None and link_el.text else ""
                pub = pub_el.text.strip() if pub_el is not None and pub_el.text else ""
                if title:
                    results.append({"ticker": ticker, "title": title, "link": link, "pubDate": pub})
                    count += 1
        except Exception:
            pass
    return results


# =========================
# BLOOMBERG FEATURES — VOLATILITY REGIME
# =========================

def compute_volatility_regime(portfolio_returns: pd.Series) -> dict:
    """
    Compute EWMA vol, rolling vols, and classify regime.
    EWMA: sigma^2_t = lambda * sigma^2_{t-1} + (1-lambda) * r^2_t (RiskMetrics, lambda=0.94)
    """
    empty = {
        "ewma_vol_series": pd.Series(dtype=float),
        "current_regime": "UNKNOWN",
        "current_ewma_vol": float("nan"),
        "rolling_21d": pd.Series(dtype=float),
        "rolling_63d": pd.Series(dtype=float),
    }
    if portfolio_returns is None or len(portfolio_returns) < 5:
        return empty

    r = portfolio_returns.dropna()
    if len(r) < 5:
        return empty

    lam = 0.94
    r2 = r.values ** 2
    n = len(r2)
    ewma_var = np.empty(n)
    ewma_var[0] = r2[0]
    for i in range(1, n):
        ewma_var[i] = lam * ewma_var[i - 1] + (1 - lam) * r2[i]

    ewma_vol_daily = np.sqrt(ewma_var)
    ewma_vol_annual = ewma_vol_daily * np.sqrt(252)
    ewma_series = pd.Series(ewma_vol_annual, index=r.index, name="EWMA Vol (Ann.)")

    rolling_21 = r.rolling(21).std() * np.sqrt(252)
    rolling_63 = r.rolling(63).std() * np.sqrt(252)

    current_ewma = float(ewma_series.iloc[-1])
    if current_ewma < 0.10:
        regime = "LOW"
    elif current_ewma < 0.20:
        regime = "NORMAL"
    elif current_ewma < 0.35:
        regime = "HIGH"
    else:
        regime = "CRISIS"

    return {
        "ewma_vol_series": ewma_series,
        "current_regime": regime,
        "current_ewma_vol": current_ewma,
        "rolling_21d": rolling_21,
        "rolling_63d": rolling_63,
    }


# =========================
# BLOOMBERG FEATURES — FX EXPOSURE
# =========================

def build_fx_exposure_summary(df: pd.DataFrame, base_currency: str) -> pd.DataFrame:
    """
    Group portfolio holdings by native currency.
    Returns: Currency | Exposure | Weight % | Impact of 1% FX Move
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["Currency", "Exposure", "Weight %", "1% FX Move Impact"])

    required = {"Native Currency", "Value"}
    if not required.issubset(df.columns):
        return pd.DataFrame(columns=["Currency", "Exposure", "Weight %", "1% FX Move Impact"])

    sub = df[df["Value"] > 0][["Native Currency", "Value"]].copy()
    if sub.empty:
        return pd.DataFrame(columns=["Currency", "Exposure", "Weight %", "1% FX Move Impact"])

    grouped = sub.groupby("Native Currency")["Value"].sum().reset_index()
    grouped.columns = ["Currency", "Exposure"]
    total = grouped["Exposure"].sum()
    if total > 0:
        grouped["Weight %"] = (grouped["Exposure"] / total * 100).round(2)
    else:
        grouped["Weight %"] = 0.0

    grouped["1% FX Move Impact"] = grouped.apply(
        lambda row: 0.0 if row["Currency"] == base_currency else row["Exposure"] * 0.01,
        axis=1,
    )
    grouped = grouped.sort_values("Exposure", ascending=False).reset_index(drop=True)
    return grouped


# =========================
# BLOOMBERG FEATURES — MULTI-BENCHMARK COMPARISON
# =========================

@st.cache_data(ttl=900, show_spinner=False)
def build_multi_benchmark_comparison(
    portfolio_returns: pd.Series,
    base_currency: str,
    _fx_hist: pd.DataFrame,
    risk_free_rate: float,
) -> dict:
    """
    Build cumulative return chart + summary table comparing portfolio vs SPY, ACWI, BND, and blended 60/40.
    _fx_hist is prefixed with _ so Streamlit won't hash it (unhashable DataFrame).
    """
    import yfinance as yf

    empty = {"fig": go.Figure(), "summary_df": pd.DataFrame()}

    if portfolio_returns is None or portfolio_returns.empty:
        return empty

    benchmarks = {"SPY": "S&P 500", "ACWI": "MSCI World", "BND": "Bonds"}
    bench_tickers = list(benchmarks.keys())

    try:
        raw = yf.download(bench_tickers, period="2y", auto_adjust=True, progress=False)
        if raw.empty:
            return empty
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
        else:
            close = raw[["Close"]] if "Close" in raw.columns else raw
        close = close.dropna(how="all")
    except Exception:
        return empty

    # FX-adjust if base currency is not USD
    fx_adj: dict[str, pd.Series] = {}
    if base_currency != "USD" and _fx_hist is not None and not _fx_hist.empty:
        fx_col = f"{base_currency}=X"
        alt_col = f"USD{base_currency}=X"
        if fx_col in _fx_hist.columns:
            fx_adj_series = _fx_hist[fx_col].reindex(close.index, method="ffill")
        elif alt_col in _fx_hist.columns:
            fx_adj_series = (1.0 / _fx_hist[alt_col]).reindex(close.index, method="ffill")
        else:
            fx_adj_series = None
        if fx_adj_series is not None:
            for t in bench_tickers:
                if t in close.columns:
                    fx_adj[t] = fx_adj_series

    bench_returns: dict[str, pd.Series] = {}
    for t in bench_tickers:
        if t not in close.columns:
            continue
        s = close[t].dropna()
        if t in fx_adj:
            fx_s = fx_adj[t].reindex(s.index, method="ffill")
            s = s * fx_s
        r = s.pct_change().dropna()
        bench_returns[t] = r

    # Blended 60/40
    if "SPY" in bench_returns and "BND" in bench_returns:
        spy_r = bench_returns["SPY"]
        bnd_r = bench_returns["BND"]
        aligned_blend = pd.concat([spy_r.rename("SPY"), bnd_r.rename("BND")], axis=1).dropna()
        if not aligned_blend.empty:
            blend_r = aligned_blend["SPY"] * 0.60 + aligned_blend["BND"] * 0.40
            bench_returns["Blend 60/40"] = blend_r

    fig = go.Figure()
    colors = {"Portfolio": "#f3a712", "SPY": "#00c8ff", "ACWI": "#00e676", "BND": "#ce93d8", "Blend 60/40": "#ff7043"}

    p_cum = (1 + portfolio_returns).cumprod() - 1
    fig.add_scatter(x=p_cum.index, y=p_cum, mode="lines", name=f"Portfolio ({p_cum.iloc[-1]:.2%})",
                    line=dict(color=colors["Portfolio"], width=2),
                    hovertemplate="%{x|%Y-%m-%d}<br>Portfolio: %{y:.2%}<extra></extra>")

    bench_labels = {"SPY": "S&P 500 (SPY)", "ACWI": "MSCI World (ACWI)", "BND": "Bonds (BND)", "Blend 60/40": "Blend 60/40"}
    for key, r in bench_returns.items():
        aligned = pd.concat([portfolio_returns.rename("P"), r.rename(key)], axis=1).dropna()
        if aligned.empty:
            continue
        b_cum = (1 + aligned[key]).cumprod() - 1
        label = bench_labels.get(key, key)
        fig.add_scatter(x=b_cum.index, y=b_cum, mode="lines", name=f"{label} ({b_cum.iloc[-1]:.2%})",
                        line=dict(color=colors.get(key, "#aaa"), width=1.5, dash="dot"),
                        hovertemplate=f"%{{x|%Y-%m-%d}}<br>{label}: %{{y:.2%}}<extra></extra>")

    fig.update_layout(
        paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"), height=430,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Date", yaxis_title="Cumulative Return",
        yaxis=dict(tickformat=".0%"),
        legend=dict(orientation="h", y=1.10, x=0.0),
    )

    # Summary table
    def _stats(r_series: pd.Series, name: str, p_total: float) -> dict:
        if r_series.empty:
            return {}
        cum = float((1 + r_series).prod() - 1)
        vol = float(r_series.std() * np.sqrt(252))
        sharpe_v = float((r_series.mean() * 252 - risk_free_rate) / vol) if vol > 0 else float("nan")
        cum_s = (1 + r_series).cumprod()
        dd = float((cum_s / cum_s.cummax() - 1).min())
        vs_portfolio = cum - p_total
        return {
            "Benchmark": name, "Return": f"{cum:.2%}", "Volatility": f"{vol:.2%}",
            "Sharpe": f"{sharpe_v:.2f}", "Max DD": f"{dd:.2%}",
            "vs Portfolio": f"{vs_portfolio:+.2%}",
        }

    p_cum_total = float((1 + portfolio_returns).prod() - 1)
    p_vol = float(portfolio_returns.std() * np.sqrt(252))
    p_sharpe = float((portfolio_returns.mean() * 252 - risk_free_rate) / p_vol) if p_vol > 0 else float("nan")
    p_cum_s = (1 + portfolio_returns).cumprod()
    p_dd = float((p_cum_s / p_cum_s.cummax() - 1).min())

    summary_rows = [{"Benchmark": "Portfolio", "Return": f"{p_cum_total:.2%}", "Volatility": f"{p_vol:.2%}",
                     "Sharpe": f"{p_sharpe:.2f}", "Max DD": f"{p_dd:.2%}", "vs Portfolio": "—"}]

    bench_name_map = {"SPY": "S&P 500 (SPY)", "ACWI": "MSCI World (ACWI)", "BND": "Bonds (BND)", "Blend 60/40": "Blend 60/40"}
    for key, r in bench_returns.items():
        aligned = pd.concat([portfolio_returns.rename("P"), r.rename(key)], axis=1).dropna()
        if aligned.empty:
            continue
        row = _stats(aligned[key], bench_name_map.get(key, key), p_cum_total)
        if row:
            summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)
    return {"fig": fig, "summary_df": summary_df}


# =========================
# BLOOMBERG FEATURES — TICKER DEEP DIVE
# =========================

@st.cache_data(ttl=60, show_spinner=False)
def fetch_ticker_deep_dive(ticker: str) -> dict:
    """Fetch comprehensive ticker data from yfinance."""
    import yfinance as yf
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        hist = t.history(period="6mo")
        return {
            "info": info,
            "hist": hist,
            "ticker": ticker.upper(),
        }
    except Exception as e:
        return {"info": {}, "hist": pd.DataFrame(), "ticker": ticker.upper(), "error": str(e)}


# =========================
# BLOOMBERG FEATURES — ORDER BLOTTER
# =========================

ORDER_BLOTTER_HEADERS = [
    "id", "date", "ticker", "direction", "quantity",
    "limit_price", "status", "filled_price", "filled_qty", "notes",
]


def connect_order_blotter_worksheet():
    return _connect_named_worksheet("order_blotter", ORDER_BLOTTER_HEADERS)


@st.cache_data(ttl=GOOGLE_SHEETS_CACHE_TTL, show_spinner=False)
def load_order_blotter_from_sheets() -> pd.DataFrame:
    sheet_id, sheet_url = _get_private_positions_sheet_locator()
    try:
        connect_order_blotter_worksheet()
        records = _get_worksheet_records_cached(sheet_id, sheet_url, "order_blotter")
    except Exception:
        return pd.DataFrame(columns=ORDER_BLOTTER_HEADERS)

    if not records:
        return pd.DataFrame(columns=ORDER_BLOTTER_HEADERS)

    df = pd.DataFrame(records)
    df.columns = [str(c).strip().lower() for c in df.columns]
    for col in ORDER_BLOTTER_HEADERS:
        if col not in df.columns:
            df[col] = ""
    for col in ["quantity", "limit_price", "filled_price", "filled_qty"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"].apply(_parse_gsheets_date), errors="coerce")
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["direction"] = df["direction"].astype(str).str.strip().str.upper()
    df["status"] = df["status"].astype(str).str.strip()
    return df[ORDER_BLOTTER_HEADERS].reset_index(drop=True)


def append_order_to_blotter(order: dict):
    ws = connect_order_blotter_worksheet()
    row = [
        str(order.get("id", "")),
        str(order.get("date", "")),
        str(order.get("ticker", "")).upper().strip(),
        str(order.get("direction", "")).upper().strip(),
        float(order.get("quantity", 0.0)),
        float(order.get("limit_price", 0.0)) if order.get("limit_price") else "",
        str(order.get("status", "Pending")).strip(),
        float(order.get("filled_price", 0.0)) if order.get("filled_price") else "",
        float(order.get("filled_qty", 0.0)) if order.get("filled_qty") else "",
        str(order.get("notes", "")).strip(),
    ]
    ws.append_row(row, value_input_option="RAW")
    _clear_google_sheets_cache()


def update_order_status(order_id: str, updates: dict):
    """Update an existing order blotter row by its id column."""
    ws = connect_order_blotter_worksheet()
    records = ws.get_all_values()
    if len(records) < 2:
        return
    header = [str(h).strip().lower() for h in records[0]]
    id_col = header.index("id") + 1 if "id" in header else None
    if id_col is None:
        return
    for i, row in enumerate(records[1:], start=2):
        if len(row) >= id_col and str(row[id_col - 1]).strip() == str(order_id).strip():
            for field, value in updates.items():
                if field in header:
                    col_idx = header.index(field) + 1
                    ws.update_cell(i, col_idx, str(value))
            break
    _clear_google_sheets_cache()


def compute_goal_contribution(
    current_value: float,
    target_value: float,
    years: int,
    expected_annual_return: float,
) -> float:
    """Required monthly contribution to reach target_value in given years."""
    if years <= 0 or target_value <= 0:
        return 0.0
    n = years * 12
    r = (1 + expected_annual_return) ** (1.0 / 12) - 1
    fv_pv = current_value * (1 + r) ** n
    if fv_pv >= target_value:
        return 0.0
    if r == 0:
        return (target_value - fv_pv) / n
    return float((target_value - fv_pv) * r / ((1 + r) ** n - 1))


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


# =========================
# TELEGRAM + CUSTOM ALERTS
# =========================

ALERTS_HEADERS = [
    "id", "ticker", "alert_type", "condition",
    "threshold", "active", "created_at", "last_triggered", "notes",
]


def send_telegram_message(text: str) -> bool:
    """Send a plain-text or HTML message via Telegram Bot API. Returns True on success."""
    import json
    import urllib.request
    import urllib.error

    tg = st.secrets.get("telegram", {})
    bot_token = str(tg.get("bot_token", "")).strip()
    chat_id = str(tg.get("chat_id", "")).strip()
    if not bot_token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False


def connect_alerts_worksheet():
    return _connect_named_worksheet("custom_alerts", ALERTS_HEADERS)


@st.cache_data(ttl=GOOGLE_SHEETS_CACHE_TTL, show_spinner=False)
def load_alerts_from_sheets() -> pd.DataFrame:
    sheet_id, sheet_url = _get_private_positions_sheet_locator()
    try:
        connect_alerts_worksheet()
        records = _get_worksheet_records_cached(sheet_id, sheet_url, "custom_alerts")
    except Exception:
        return pd.DataFrame(columns=ALERTS_HEADERS)

    if not records:
        return pd.DataFrame(columns=ALERTS_HEADERS)

    df = pd.DataFrame(records)
    df.columns = [str(c).strip().lower() for c in df.columns]
    for col in ALERTS_HEADERS:
        if col not in df.columns:
            df[col] = ""
    df["threshold"] = pd.to_numeric(df["threshold"], errors="coerce").fillna(0.0)
    df["active"] = df["active"].astype(str).str.upper().map(
        lambda v: v == "TRUE"
    )
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    return df[ALERTS_HEADERS].reset_index(drop=True)


def append_alert_to_sheets(alert: dict):
    ws = connect_alerts_worksheet()
    row = [str(alert.get(h, "")) for h in ALERTS_HEADERS]
    ws.append_row(row, value_input_option="RAW")
    _clear_google_sheets_cache()


def update_alert_field(alert_id: str, field: str, value: str):
    """Single-cell update — cheapest possible write."""
    ws = connect_alerts_worksheet()
    records = ws.get_all_values()
    if len(records) < 2:
        return
    header = [str(h).strip().lower() for h in records[0]]
    if "id" not in header or field not in header:
        return
    id_col = header.index("id")
    field_col = header.index(field) + 1  # 1-based for gspread
    for i, row in enumerate(records[1:], start=2):
        if len(row) > id_col and str(row[id_col]).strip() == str(alert_id).strip():
            ws.update_cell(i, field_col, str(value))
            break
    _clear_google_sheets_cache()


# =============================================================================
# CONTRIBUTION & GOALS UTILITIES
# =============================================================================

@st.cache_data(ttl=300, show_spinner=False)
def fetch_day_change_for_tickers(tickers: tuple[str, ...]) -> dict[str, float]:
    """Return last-session % change for tickers not necessarily in the portfolio.
    Uses yfinance 5d download and computes close-to-close return for the latest day.
    Returns {ticker: return} where return is a decimal (e.g. -0.06 = -6%).
    """
    import yfinance as yf
    result: dict[str, float] = {}
    try:
        raw = yf.download(list(tickers), period="5d", auto_adjust=True, progress=False)
        if raw.empty:
            return result
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        if isinstance(close, pd.Series):
            close = close.to_frame(name=list(tickers)[0])
        close = close.dropna(how="all")
        if len(close) < 2:
            return result
        for ticker in tickers:
            if ticker in close.columns:
                col = close[ticker].dropna()
                if len(col) >= 2:
                    result[ticker] = float(col.iloc[-1] / col.iloc[-2] - 1)
    except Exception:
        pass
    return result


def simulate_etf_dilution(
    df: "pd.DataFrame",
    monthly_contribution: float,
    semi_annual_contribution: float,
    horizon_months: int,
    expected_annual_return: float,
) -> "pd.DataFrame":
    """Project ETF weight evolution over time with buy-only rebalancing.

    Each month the portfolio grows by expected_annual_return/12.
    Monthly cash is added; every 6 months an extra lump sum is added.
    Cash is deployed to the most underweight ticker (vs Target Weight).
    Returns a DataFrame with columns: Month, Ticker, Weight, PortfolioValue.
    """
    if df.empty or monthly_contribution < 0:
        return pd.DataFrame(columns=["Month", "Ticker", "Weight", "PortfolioValue"])

    tickers = df["Ticker"].tolist()
    values = {t: float(df.loc[df["Ticker"] == t, "Value"].iloc[0]) for t in tickers}
    target_w = {t: float(df.loc[df["Ticker"] == t, "Target Weight"].iloc[0])
                if "Target Weight" in df.columns else 1.0 / len(tickers)
                for t in tickers}

    monthly_rate = (1 + max(expected_annual_return, 0.0)) ** (1 / 12) - 1
    records = []

    # Record month 0 (current state)
    total0 = sum(values.values()) or 1.0
    for t in tickers:
        records.append({"Month": 0, "Ticker": t, "Weight": values[t] / total0, "PortfolioValue": total0})

    for m in range(1, horizon_months + 1):
        # Grow all positions
        for t in tickers:
            values[t] *= (1 + monthly_rate)

        # Cash to deploy
        cash = monthly_contribution
        if m % 6 == 0:
            cash += semi_annual_contribution

        if cash > 0:
            total = sum(values.values()) or 1.0
            weights = {t: values[t] / total for t in tickers}
            gaps = {t: target_w.get(t, 1.0 / len(tickers)) - weights[t] for t in tickers}
            buy_t = max(gaps, key=gaps.get)
            values[buy_t] += cash

        total = sum(values.values()) or 1.0
        for t in tickers:
            records.append({"Month": m, "Ticker": t, "Weight": values[t] / total, "PortfolioValue": total})

    return pd.DataFrame(records)


def compute_return_attribution(
    asset_returns: "pd.DataFrame",
    historical_base: "pd.DataFrame",
    df: "pd.DataFrame",
    period_label: str,
) -> "pd.DataFrame":
    """Compute each ETF's contribution to total portfolio return in a given period.

    Contribution = average_weight_in_period × ETF_cumulative_return_in_period.
    Uses historical_base prices and current Shares to derive daily weights.
    """
    if asset_returns is None or asset_returns.empty or df.empty:
        return pd.DataFrame()

    period_map = {"1M": 21, "3M": 63, "6M": 126, "YTD": None, "1Y": 252}
    tickers = [t for t in df["Ticker"].tolist() if t in asset_returns.columns]
    if not tickers:
        return pd.DataFrame()

    ret_slice = asset_returns[tickers].dropna(how="all")
    if period_label == "YTD":
        start = pd.Timestamp(ret_slice.index[-1].year, 1, 1) if not ret_slice.empty else None
        if start:
            ret_slice = ret_slice[ret_slice.index >= start]
    else:
        days = period_map.get(period_label, 21)
        ret_slice = ret_slice.iloc[-days:] if len(ret_slice) >= days else ret_slice

    if ret_slice.empty:
        return pd.DataFrame()

    shares_map = df.set_index("Ticker")["Shares"].to_dict()
    rows = []
    for t in tickers:
        etf_ret = float((1 + ret_slice[t].dropna()).prod() - 1) if not ret_slice[t].dropna().empty else 0.0

        # Compute avg weight using historical prices if available
        avg_w = float(df.loc[df["Ticker"] == t, "Weight"].iloc[0]) if "Weight" in df.columns else 0.0
        if historical_base is not None and t in historical_base.columns:
            hist_slice = historical_base[tickers].loc[ret_slice.index[0]:ret_slice.index[-1]].dropna(how="all")
            if not hist_slice.empty:
                ticker_vals = {tk: hist_slice[tk] * shares_map.get(tk, 0.0) for tk in tickers if tk in hist_slice.columns}
                if ticker_vals:
                    val_df = pd.DataFrame(ticker_vals)
                    total_vals = val_df.sum(axis=1).replace(0, np.nan)
                    if t in val_df.columns:
                        avg_w = float((val_df[t] / total_vals).mean())

        contribution = avg_w * etf_ret
        name = str(df.loc[df["Ticker"] == t, "Name"].iloc[0]) if "Name" in df.columns else t
        rows.append({
            "Ticker": t,
            "Name": name,
            "ETF Return": etf_ret,
            "Avg Weight": avg_w,
            "Contribution": contribution,
        })

    out = pd.DataFrame(rows).sort_values("Contribution", ascending=False).reset_index(drop=True)
    return out


def compute_rolling_pair_correlations(
    asset_returns: "pd.DataFrame",
    windows: tuple = (126, 252),
) -> "dict[int, pd.DataFrame]":
    """Compute rolling Pearson correlation for each pair of tickers.

    Returns {window_days: DataFrame} where DataFrame columns are 'TickerA/TickerB'
    pair labels and index is date.
    """
    if asset_returns is None or asset_returns.shape[1] < 2:
        return {}

    tickers = asset_returns.columns.tolist()
    result: dict[int, pd.DataFrame] = {}
    for w in windows:
        pairs: dict[str, "pd.Series"] = {}
        for i, t1 in enumerate(tickers):
            for t2 in tickers[i + 1:]:
                label = f"{t1}/{t2}"
                pairs[label] = asset_returns[t1].rolling(w).corr(asset_returns[t2])
        if pairs:
            result[w] = pd.DataFrame(pairs).dropna(how="all")
    return result


def compute_milestone_eta(
    current_value: float,
    target: float,
    monthly_contribution: float,
    monthly_return: float,
) -> float:
    """Estimate months to reach a portfolio target via contributions + growth.

    Uses the geometric series formula. Returns float months, or inf if unreachable.
    """
    if current_value >= target:
        return 0.0
    gap = target - current_value
    monthly_growth = current_value * monthly_return
    monthly_inflow = monthly_contribution + monthly_growth
    if monthly_inflow <= 0:
        return float("inf")
    # Simple linear approximation (conservative — ignores compounding of contributions)
    return gap / monthly_inflow


# =============================================================================
# END CONTRIBUTION & GOALS UTILITIES
# =============================================================================


def delete_alert(alert_id: str):
    ws = connect_alerts_worksheet()
    records = ws.get_all_values()
    if len(records) < 2:
        return
    header = [str(h).strip().lower() for h in records[0]]
    if "id" not in header:
        return
    id_col = header.index("id")
    for i, row in enumerate(records[1:], start=2):
        if len(row) > id_col and str(row[id_col]).strip() == str(alert_id).strip():
            ws.delete_rows(i)
            break
    _clear_google_sheets_cache()