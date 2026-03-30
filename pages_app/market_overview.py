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

    tab1, tab2, tab3 = st.tabs(["Economic Calendar", "Sector Heatmap", "News Feed"])

    with tab1:
        try:
            _render_economic_calendar(ctx)
        except Exception as e:
            st.error(f"Economic calendar error: {e}")

    with tab2:
        try:
            _render_sector_heatmap()
        except Exception as e:
            st.error(f"Sector heatmap error: {e}")

    with tab3:
        try:
            _render_news_feed(ctx)
        except Exception as e:
            st.error(f"News feed error: {e}")
