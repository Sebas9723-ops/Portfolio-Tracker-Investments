import textwrap
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from app_core import (
    render_page_title,
    render_status_bar,
    render_private_dashboard_logo,
    info_section,
    info_metric,
)


@st.fragment(run_every="1s")
def _render_market_clocks_block():
    markets = [
        {"name": "New York", "exchange": "NYSE / Nasdaq", "tz": "America/New_York"},
        {"name": "London", "exchange": "LSE", "tz": "Europe/London"},
        {"name": "Frankfurt", "exchange": "Xetra", "tz": "Europe/Berlin"},
        {"name": "Zurich", "exchange": "SIX", "tz": "Europe/Zurich"},
        {"name": "Tokyo", "exchange": "TSE", "tz": "Asia/Tokyo"},
        {"name": "Shanghai", "exchange": "SSE", "tz": "Asia/Shanghai"},
        {"name": "Singapore", "exchange": "SGX", "tz": "Asia/Singapore"},
        {"name": "Bogotá", "exchange": "BVC", "tz": "America/Bogota"},
        {"name": "Sydney", "exchange": "ASX", "tz": "Australia/Sydney"},
    ]

    cards = []
    for market in markets:
        now = datetime.now(ZoneInfo(market["tz"]))
        time_val = now.strftime("%H:%M:%S")
        date_val = now.strftime("%a %d %b")

        cards.append(
            f"""
            <div class="pm-clock-card">
                <div class="pm-clock-name">{market["name"]}</div>
                <div class="pm-clock-exchange">{market["exchange"]}</div>
                <div class="pm-clock-time">{time_val}</div>
                <div class="pm-clock-date">{date_val}</div>
            </div>
            """
        )

    html_block = textwrap.dedent(
        f"""
        <style>
        .pm-clock-wrapper {{
            border: 1px solid #2b3340;
            border-left: 4px solid #f3a712;
            border-radius: 6px;
            padding: 12px;
            background: #111821;
            width: 100%;
            box-sizing: border-box;
            margin-bottom: 1rem;
        }}

        .pm-clock-title {{
            color: #f3a712;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 10px;
            font-size: 15px;
        }}

        .pm-clock-grid {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
            width: 100%;
        }}

        .pm-clock-card {{
            background: #0f141b;
            border: 1px solid #2d3642;
            border-radius: 6px;
            padding: 10px;
            min-height: 94px;
            box-sizing: border-box;
            overflow: hidden;
        }}

        .pm-clock-name {{
            color: #f3a712;
            font-weight: 800;
            font-size: 13px;
            text-transform: uppercase;
            line-height: 1.1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .pm-clock-exchange {{
            color: #9fb0c3;
            font-size: 11px;
            margin-top: 2px;
            line-height: 1.05;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .pm-clock-time {{
            color: #f8f8f8;
            font-size: 18px;
            font-weight: 800;
            margin-top: 8px;
            line-height: 1.05;
            white-space: nowrap;
        }}

        .pm-clock-date {{
            color: #7fb3ff;
            font-size: 11px;
            margin-top: 4px;
            line-height: 1.05;
            white-space: nowrap;
        }}

        @media (max-width: 900px) {{
            .pm-clock-grid {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 8px;
            }}

            .pm-clock-card {{
                padding: 8px 10px;
                min-height: 82px;
            }}

            .pm-clock-name {{
                font-size: 12px;
            }}

            .pm-clock-exchange {{
                font-size: 10px;
            }}

            .pm-clock-time {{
                font-size: 16px;
                margin-top: 6px;
            }}

            .pm-clock-date {{
                font-size: 10px;
            }}
        }}

        @media (max-width: 360px) {{
            .pm-clock-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        </style>

        <div class="pm-clock-wrapper">
            <div class="pm-clock-title">Live Market Clocks</div>
            <div class="pm-clock-grid">
                {''.join(cards)}
            </div>
        </div>
        """
    )

    st.markdown(html_block, unsafe_allow_html=True)


def render_dashboard(ctx):
    render_page_title("Dashboard")

    render_private_dashboard_logo(
        mode=ctx["mode"],
        authenticated=ctx["authenticated"],
    )

    render_status_bar(
        mode=ctx["mode"],
        base_currency=ctx["base_currency"],
        profile=ctx["profile"],
        tc_model=ctx["tc_model"],
        sheets_ok=(ctx["positions_sheet_available"] if ctx["mode"] == "Private" else True),
    )

    _render_market_clocks_block()

    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    info_metric(
        r1c1,
        f"Total Portfolio ({ctx['base_currency']})",
        f"{ctx['base_currency']} {ctx['total_portfolio_value']:,.2f}",
        "Total portfolio value including invested assets and cash balances.",
    )
    info_metric(
        r1c2,
        "Invested Assets",
        f"{ctx['base_currency']} {ctx['holdings_value']:,.2f}",
        "Current market value of invested positions only.",
    )
    info_metric(
        r1c3,
        "Cash",
        f"{ctx['base_currency']} {ctx['cash_total_value']:,.2f}",
        "Cash balances converted into the selected base currency.",
    )
    info_metric(
        r1c4,
        "Unrealized PnL",
        f"{ctx['base_currency']} {ctx['unrealized_pnl']:,.2f}",
        "Profit or loss on current open positions.",
    )

    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    info_metric(
        r2c1,
        "Return",
        f"{ctx['total_return']:.2%}",
        "Cumulative portfolio return over the historical sample.",
    )
    info_metric(
        r2c2,
        "Volatility",
        f"{ctx['volatility']:.2%}",
        "Annualized standard deviation of portfolio returns.",
    )
    info_metric(
        r2c3,
        "Sharpe Ratio",
        f"{ctx['sharpe']:.2f}",
        "Risk-adjusted return using the selected risk-free rate.",
    )
    info_metric(
        r2c4,
        "Realized PnL",
        f"{ctx['base_currency']} {ctx['realized_pnl']:,.2f}",
        "Realized profit or loss from historical sell transactions.",
    )

    c_left, c_right = st.columns([1.15, 1])

    with c_left:
        info_section("Top Holdings", "Largest portfolio positions by current market value.")
        top_holdings = ctx["display_df"].sort_values("Value", ascending=False).head(5)[
            ["Ticker", "Name", "Shares", "Value", "Weight %", "Unrealized PnL"]
        ]
        st.dataframe(top_holdings, use_container_width=True, height=245)

    with c_right:
        info_section("Portfolio Allocation", "Portfolio composition by market value, including cash when available.")
        st.plotly_chart(ctx["fig_pie"], use_container_width=True)

    if ctx["mode"] == "Private":
        info_section("Cash Balances", "Cash balances stored in Google Sheets and converted to the selected base currency.")
        st.dataframe(ctx["cash_display_df"], use_container_width=True, height=220)

    if ctx["fig_perf"] is not None:
        info_section("Performance vs Benchmark", "Cumulative growth of the portfolio versus VOO.")
        st.plotly_chart(ctx["fig_perf"], use_container_width=True)