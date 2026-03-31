import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app_core import (
    fetch_ticker_news,
    build_sector_heatmap_data,
    get_macro_calendar,
    get_upcoming_earnings,
    info_section,
    render_page_title,
)


_SECTOR_ETFS = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Healthcare": "XLV",
    "Energy": "XLE",
    "Consumer Disc.": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication": "XLC",
}

_ROTATION_PERIODS = {"1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252}


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_sector_rotation() -> pd.DataFrame:
    import yfinance as yf
    etfs = list(_SECTOR_ETFS.values())
    try:
        raw = yf.download(etfs, period="1y", auto_adjust=True, progress=False)
        close = raw["Close"] if "Close" in raw.columns else raw
    except Exception:
        return pd.DataFrame()

    rows = []
    for sector, etf in _SECTOR_ETFS.items():
        row = {"Sector": sector, "ETF": etf}
        if etf not in close.columns:
            for p in _ROTATION_PERIODS:
                row[p] = None
        else:
            s = close[etf].dropna()
            for period_label, n_days in _ROTATION_PERIODS.items():
                if len(s) >= n_days + 1:
                    row[period_label] = round(float(s.iloc[-1] / s.iloc[-n_days - 1] - 1), 4)
                elif len(s) >= 2:
                    row[period_label] = round(float(s.iloc[-1] / s.iloc[0] - 1), 4)
                else:
                    row[period_label] = None
        rows.append(row)
    return pd.DataFrame(rows)


def _render_sector_rotation():
    info_section(
        "Sector Rotation",
        "Performance of S&P 500 sector ETFs across multiple time horizons. "
        "Green = outperformance, Red = underperformance. Sorted by 1-month return.",
    )
    with st.spinner("Loading sector data..."):
        df = _fetch_sector_rotation()

    if df.empty:
        st.info("Could not load sector rotation data.")
        return

    periods = list(_ROTATION_PERIODS.keys())
    df_sorted = df.sort_values("1M", ascending=False).reset_index(drop=True)

    # Plotly heatmap
    z = df_sorted[periods].values.tolist()
    y_labels = [f"{row['Sector']} ({row['ETF']})" for _, row in df_sorted.iterrows()]
    text = [[f"{v:.2%}" if v is not None else "—" for v in row] for row in z]

    fig = go.Figure(go.Heatmap(
        z=z,
        x=periods,
        y=y_labels,
        text=text,
        texttemplate="%{text}",
        colorscale=[[0.0, "#8b0000"], [0.5, "#1a1f2e"], [1.0, "#006400"]],
        zmid=0,
        showscale=True,
        colorbar=dict(tickformat=".1%", title="Return"),
        hoverongaps=False,
        hovertemplate="%{y}<br>%{x}: %{text}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6", size=12),
        height=440,
        margin=dict(t=20, b=20, l=200, r=20),
        xaxis=dict(side="top"),
    )
    st.plotly_chart(fig, use_container_width=True, key="sector_rotation_heatmap")

    # Table with conditional formatting
    st.markdown("##### Returns Table")
    display = df_sorted.copy()
    for p in periods:
        display[p] = display[p].apply(lambda v: f"{v:.2%}" if v is not None else "—")
    st.dataframe(display[["Sector", "ETF"] + periods], use_container_width=True, hide_index=True)


_TYPE_COLORS = {
    "Earnings": "#f3a712",
    "Fed": "#00c8ff",
    "CPI": "#00e676",
    "NFP": "#ce93d8",
}


def _render_economic_calendar(ctx):
    info_section(
        "Economic Calendar",
        "Upcoming earnings for held tickers and 2026 macro events. Color-coded by event type.",
    )

    tickers = list(ctx.get("updated_portfolio", {}).keys())

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.markdown("##### Macro Events")
        macro_df = get_macro_calendar()
        if macro_df.empty:
            st.info("No upcoming macro events.")
        else:
            macro_display = macro_df.copy()
            macro_display["Date"] = macro_display["Date"].dt.strftime("%Y-%m-%d")
            for _, row in macro_display.iterrows():
                color = _TYPE_COLORS.get(row["Type"], "#aaa")
                st.markdown(
                    f"<div style='display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #1a1f2e'>"
                    f"<span style='color:{color};font-size:11px;font-weight:bold;min-width:60px'>{row['Type']}</span>"
                    f"<span style='color:#f3a712;font-family:monospace;font-size:12px;min-width:90px'>{row['Date']}</span>"
                    f"<span style='color:#e6e6e6;font-size:12px'>{row['Event']}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    with col_right:
        st.markdown("##### Earnings Dates")
        if not tickers:
            st.info("No tickers in portfolio.")
        else:
            with st.spinner("Loading earnings..."):
                earnings_df = get_upcoming_earnings(tickers)
            if earnings_df.empty:
                st.info("No upcoming earnings found for held tickers.")
            else:
                earnings_display = earnings_df.copy()
                earnings_display["Date"] = earnings_display["Date"].dt.strftime("%Y-%m-%d")
                for _, row in earnings_display.iterrows():
                    color = _TYPE_COLORS["Earnings"]
                    ticker_str = row.get("Ticker", "")
                    st.markdown(
                        f"<div style='display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #1a1f2e'>"
                        f"<span style='color:{color};font-size:11px;font-weight:bold;min-width:60px'>EARNINGS</span>"
                        f"<span style='color:#f3a712;font-family:monospace;font-size:12px;min-width:90px'>{row['Date']}</span>"
                        f"<span style='color:#e6e6e6;font-size:12px'>{ticker_str}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )


def _render_sector_heatmap():
    info_section(
        "Sector Heatmap",
        "1-day and 5-day returns for S&P 500 sector ETFs. Green = positive, Red = negative.",
    )
    sector_df = build_sector_heatmap_data()
    if sector_df.empty:
        st.info("Could not load sector data.")
        return

    fig = px.treemap(
        sector_df,
        path=["Sector"],
        values=[1] * len(sector_df),
        color="return_1d",
        color_continuous_scale=["#d32f2f", "#1a1f2e", "#00c853"],
        color_continuous_midpoint=0,
        custom_data=["ETF", "return_1d", "return_5d"],
    )
    fig.update_traces(
        texttemplate="<b>%{label}</b><br>%{customdata[0]}<br>1d: %{customdata[1]:.2%}",
        hovertemplate="<b>%{label}</b><br>ETF: %{customdata[0]}<br>1-day: %{customdata[1]:.2%}<br>5-day: %{customdata[2]:.2%}<extra></extra>",
    )
    fig.update_layout(
        paper_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=500,
        margin=dict(t=20, b=20, l=10, r=10),
        coloraxis_colorbar=dict(tickformat=".1%", title="1d Return"),
    )
    st.plotly_chart(fig, use_container_width=True, key="market_overview_heatmap")

    st.markdown("##### Sector Returns Table")
    display = sector_df.copy()
    display["return_1d"] = display["return_1d"].map(lambda v: f"{v:.2%}")
    display["return_5d"] = display["return_5d"].map(lambda v: f"{v:.2%}")
    display.columns = ["ETF", "Sector", "1-Day Return", "5-Day Return"]
    st.dataframe(display, use_container_width=True, hide_index=True)


def _render_news_feed(ctx):
    info_section(
        "News Feed",
        "Latest Yahoo Finance headlines for held tickers (15-min cache).",
    )
    tickers = list(ctx.get("updated_portfolio", {}).keys())
    if not tickers:
        st.info("No tickers in portfolio.")
        return

    with st.spinner("Loading news..."):
        news_items = fetch_ticker_news(tickers, max_per_ticker=3)

    if not news_items:
        st.info("No news found for portfolio tickers.")
        return

    # Group by ticker
    by_ticker: dict[str, list] = {}
    for item in news_items:
        t = item.get("ticker", "")
        by_ticker.setdefault(t, []).append(item)

    for ticker, items in by_ticker.items():
        st.markdown(f"**{ticker}**")
        for item in items:
            title = item.get("title", "")
            link = item.get("link", "")
            pub = item.get("pubDate", "")
            if link:
                st.markdown(
                    f"<div style='padding:4px 0 4px 8px;border-left:3px solid #f3a712;margin-bottom:6px'>"
                    f"<a href='{link}' target='_blank' style='color:#00c8ff;text-decoration:none;font-size:13px'>{title}</a>"
                    f"<br><span style='color:#888;font-size:11px'>{pub}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div style='padding:4px 0 4px 8px;border-left:3px solid #f3a712;margin-bottom:6px'>"
                    f"<span style='color:#e6e6e6;font-size:13px'>{title}</span>"
                    f"<br><span style='color:#888;font-size:11px'>{pub}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        st.markdown("---")


def render_market_overview_page(ctx):
    render_page_title("Market Overview")
    tab1, tab2, tab3, tab4 = st.tabs(["Economic Calendar", "Sector Heatmap", "Sector Rotation", "News Feed"])
    with tab1:
        try: _render_economic_calendar(ctx)
        except Exception as e: st.error(f"Economic calendar error: {e}")
    with tab2:
        try: _render_sector_heatmap()
        except Exception as e: st.error(f"Sector heatmap error: {e}")
    with tab3:
        try: _render_sector_rotation()
        except Exception as e: st.error(f"Sector rotation error: {e}")
    with tab4:
        try: _render_news_feed(ctx)
        except Exception as e: st.error(f"News feed error: {e}")
