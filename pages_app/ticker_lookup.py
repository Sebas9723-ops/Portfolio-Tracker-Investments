import plotly.graph_objects as go
import streamlit as st

from app_core import (
    fetch_ticker_deep_dive,
    fetch_ticker_news,
    info_metric,
    info_section,
    render_page_title,
)


def _fmt_large(v) -> str:
    try:
        v = float(v)
        if v >= 1e12:
            return f"{v / 1e12:.2f}T"
        if v >= 1e9:
            return f"{v / 1e9:.2f}B"
        if v >= 1e6:
            return f"{v / 1e6:.2f}M"
        return f"{v:,.0f}"
    except Exception:
        return "—"


def _fmt(v, fmt=".2f", fallback="—") -> str:
    try:
        return format(float(v), fmt)
    except Exception:
        return fallback


def _render_price_chart(hist):
    if hist is None or hist.empty:
        st.info("No price history available.")
        return

    close = hist["Close"] if "Close" in hist.columns else hist.iloc[:, 0]
    fig = go.Figure()
    fig.add_scatter(
        x=close.index, y=close, mode="lines",
        line=dict(color="#f3a712", width=2),
        name="Price",
        hovertemplate="%{x|%Y-%m-%d}<br>Price: %{y:.2f}<extra></extra>",
    )
    fig.update_layout(
        paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"), height=360,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Date", yaxis_title="Price",
    )
    st.plotly_chart(fig, use_container_width=True, key="ticker_lookup_price_chart")


def _render_metrics_grid(info: dict, ticker: str):
    info_section("Key Metrics", f"Bloomberg-style snapshot for {ticker}.")

    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
    day_change_pct = None
    if current_price and prev_close:
        try:
            day_change_pct = (float(current_price) - float(prev_close)) / float(prev_close)
        except Exception:
            pass

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Price", f"{_fmt(current_price, '.2f')}", f"Previous close: {_fmt(prev_close, '.2f')}")
    if day_change_pct is not None:
        change_str = f"{day_change_pct:+.2%}"
        color_hint = "green" if day_change_pct >= 0 else "red"
        info_metric(c2, "Day Change %", change_str, f"Direction: {color_hint}")
    else:
        info_metric(c2, "Day Change %", "—", "N/A")

    w52_high = info.get("fiftyTwoWeekHigh")
    w52_low = info.get("fiftyTwoWeekLow")
    info_metric(c3, "52W High", _fmt(w52_high, ".2f"), "52-week high.")
    info_metric(c4, "52W Low", _fmt(w52_low, ".2f"), "52-week low.")

    c5, c6, c7, c8 = st.columns(4)
    pe_ratio = info.get("trailingPE") or info.get("forwardPE")
    mkt_cap = info.get("marketCap")
    volume = info.get("volume") or info.get("regularMarketVolume")
    avg_volume = info.get("averageVolume")

    info_metric(c5, "P/E Ratio", _fmt(pe_ratio, ".2f"), "Trailing or forward P/E.")
    info_metric(c6, "Market Cap", _fmt_large(mkt_cap), "Total market capitalization.")
    info_metric(c7, "Volume", _fmt_large(volume), "Today's volume.")
    info_metric(c8, "Avg Volume", _fmt_large(avg_volume), "Average daily volume.")


def _render_description(info: dict):
    desc = info.get("longBusinessSummary") or info.get("description", "")
    if desc:
        info_section("Company Description", "")
        st.markdown(
            f"<div style='color:#aaa;font-size:13px;line-height:1.6;padding:10px;background:#1a1f2e;border-radius:6px'>"
            f"{desc[:800]}{'...' if len(desc) > 800 else ''}"
            f"</div>",
            unsafe_allow_html=True,
        )


def _render_news(ticker: str):
    info_section("Latest News", f"Last 5 headlines for {ticker}.")
    news = fetch_ticker_news([ticker], max_per_ticker=5)
    if not news:
        st.info("No news found.")
        return
    for item in news:
        title = item.get("title", "")
        link = item.get("link", "")
        pub = item.get("pubDate", "")
        if link:
            st.markdown(
                f"<div style='padding:6px 0 6px 10px;border-left:3px solid #f3a712;margin-bottom:8px'>"
                f"<a href='{link}' target='_blank' style='color:#00c8ff;text-decoration:none;font-size:13px'>{title}</a>"
                f"<br><span style='color:#888;font-size:11px'>{pub}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='padding:6px 0 6px 10px;border-left:3px solid #f3a712;margin-bottom:8px'>"
                f"<span style='color:#e6e6e6;font-size:13px'>{title}</span>"
                f"<br><span style='color:#888;font-size:11px'>{pub}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )


def render_ticker_lookup_page(ctx):
    render_page_title("Ticker Lookup")

    st.markdown("#### Enter a ticker symbol to look up any security")

    c_input, c_btn, _ = st.columns([2, 1, 3])
    ticker_input = c_input.text_input(
        "Ticker",
        placeholder="Enter ticker symbol...",
        label_visibility="collapsed",
        key="ticker_lookup_input",
    )
    go_clicked = c_btn.button("GO", type="primary", use_container_width=True)

    # Also fire on Enter (if ticker in session state from previous run)
    ticker = st.session_state.get("ticker_lookup_last", "")
    if go_clicked and ticker_input:
        ticker = ticker_input.upper().strip()
        st.session_state["ticker_lookup_last"] = ticker

    if not ticker:
        st.info("Enter a ticker symbol above and press GO to look up any security.")
        return

    st.markdown(f"### {ticker}")

    with st.spinner(f"Loading data for {ticker}..."):
        data = fetch_ticker_deep_dive(ticker)

    if data.get("error"):
        st.error(f"Could not load data for {ticker}: {data['error']}")
        return

    info = data.get("info", {})
    hist = data.get("hist")
    name = info.get("longName") or info.get("shortName") or ticker
    exchange = info.get("exchange", "")
    sector = info.get("sector", "")
    industry = info.get("industry", "")

    meta_parts = [p for p in [name, exchange, sector, industry] if p]
    st.caption(" | ".join(meta_parts))

    try:
        _render_metrics_grid(info, ticker)
    except Exception as e:
        st.warning(f"Could not render metrics: {e}")

    try:
        info_section("6-Month Price Chart", f"Daily closing price for {ticker}.")
        _render_price_chart(hist)
    except Exception as e:
        st.warning(f"Could not render price chart: {e}")

    try:
        _render_description(info)
    except Exception as e:
        st.warning(f"Could not render description: {e}")

    try:
        _render_news(ticker)
    except Exception as e:
        st.warning(f"Could not render news: {e}")
