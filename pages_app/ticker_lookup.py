import numpy as np
import plotly.graph_objects as go
import streamlit as st

from app_core import (
    fetch_ticker_deep_dive,
    fetch_ticker_news,
    info_metric,
    info_section,
    render_page_title,
)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_deep_dive(ticker: str) -> dict:
    return fetch_ticker_deep_dive(ticker)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_news(ticker: str) -> list:
    return fetch_ticker_news([ticker], max_per_ticker=5)


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
    news = _cached_news(ticker)
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


def _run_monte_carlo(hist, n_paths: int = 1000, n_days: int = 252):
    """GBM Monte Carlo simulation from historical daily closing prices.

    Returns (paths, S0, mu_daily, sigma_daily) or None if data is insufficient.
    paths shape: (n_paths, n_days + 1).
    """
    if hist is None or hist.empty:
        return None
    close = (hist["Close"] if "Close" in hist.columns else hist.iloc[:, 0]).dropna()
    if len(close) < 10:
        return None

    log_ret = np.log(close / close.shift(1)).dropna().values
    mu = log_ret.mean()
    sigma = log_ret.std()
    S0 = float(close.iloc[-1])

    drift = mu - 0.5 * sigma ** 2
    shocks = np.random.standard_normal((n_paths, n_days))
    step = np.exp(drift + sigma * shocks)

    paths = np.empty((n_paths, n_days + 1))
    paths[:, 0] = S0
    for t in range(1, n_days + 1):
        paths[:, t] = paths[:, t - 1] * step[:, t - 1]

    return paths, S0, mu, sigma


def _render_monte_carlo_section(hist, ticker: str):
    info_section(
        "Monte Carlo Simulation",
        f"Geometric Brownian Motion price simulation for {ticker} — 1,000 paths "
        "calibrated on available price history.",
    )

    _HORIZON_LABELS = {63: "3 Months", 126: "6 Months", 252: "1 Year", 504: "2 Years"}
    col_h, col_btn, _ = st.columns([1, 1, 3])
    n_days = col_h.selectbox(
        "Horizon",
        options=list(_HORIZON_LABELS.keys()),
        index=2,
        format_func=lambda x: _HORIZON_LABELS[x],
        key="mc_ticker_horizon",
    )
    run = col_btn.button(
        "▶ Run Simulation", key="mc_ticker_run_btn", type="primary", use_container_width=True
    )

    mc_key = f"mc_result_{ticker}_{n_days}"

    if run:
        with st.spinner("Running 1,000 Monte Carlo paths..."):
            result = _run_monte_carlo(hist, n_paths=1000, n_days=n_days)
        if result is None:
            st.error("Not enough price history to run Monte Carlo.")
            return
        st.session_state[mc_key] = result

    result = st.session_state.get(mc_key)
    if result is None:
        return

    paths, S0, mu, sigma = result
    x = list(range(paths.shape[1]))

    fig = go.Figure()

    # ── faint sample paths (200 for performance) ──────────────────────────────
    sample_idx = np.random.choice(paths.shape[0], size=min(200, paths.shape[0]), replace=False)
    for i in sample_idx:
        fig.add_scatter(
            x=x, y=paths[i].tolist(),
            mode="lines",
            line=dict(color="rgba(243,167,18,0.06)", width=1),
            showlegend=False, hoverinfo="skip",
        )

    # ── percentile bands ──────────────────────────────────────────────────────
    p5  = np.percentile(paths, 5,  axis=0)
    p25 = np.percentile(paths, 25, axis=0)
    p75 = np.percentile(paths, 75, axis=0)
    p95 = np.percentile(paths, 95, axis=0)
    p50 = np.percentile(paths, 50, axis=0)

    fig.add_scatter(
        x=x + x[::-1], y=p95.tolist() + p5.tolist()[::-1],
        fill="toself", fillcolor="rgba(243,167,18,0.08)",
        line=dict(color="rgba(0,0,0,0)"), showlegend=True, name="5–95% band",
        hoverinfo="skip",
    )
    fig.add_scatter(
        x=x + x[::-1], y=p75.tolist() + p25.tolist()[::-1],
        fill="toself", fillcolor="rgba(243,167,18,0.15)",
        line=dict(color="rgba(0,0,0,0)"), showlegend=True, name="25–75% band",
        hoverinfo="skip",
    )
    fig.add_scatter(
        x=x, y=p5.tolist(), mode="lines",
        line=dict(color="rgba(220,80,80,0.5)", width=1, dash="dot"),
        name="5th pct",
        hovertemplate="Day %{x}<br>5th pct: %{y:.2f}<extra></extra>",
    )
    fig.add_scatter(
        x=x, y=p95.tolist(), mode="lines",
        line=dict(color="rgba(80,200,80,0.5)", width=1, dash="dot"),
        name="95th pct",
        hovertemplate="Day %{x}<br>95th pct: %{y:.2f}<extra></extra>",
    )
    fig.add_scatter(
        x=x, y=p50.tolist(), mode="lines",
        line=dict(color="#f3a712", width=2.5),
        name="Median",
        hovertemplate="Day %{x}<br>Median: %{y:.2f}<extra></extra>",
    )

    fig.update_layout(
        paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"), height=440,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Trading Days Ahead",
        yaxis_title="Price",
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"mc_chart_{ticker}_{n_days}")

    # ── summary metrics ───────────────────────────────────────────────────────
    final = paths[:, -1]
    p5_f  = float(np.percentile(final, 5))
    p50_f = float(np.percentile(final, 50))
    p95_f = float(np.percentile(final, 95))
    prob_up = float((final > S0).mean())

    c1, c2, c3, c4, c5 = st.columns(5)
    info_metric(c1, "Current Price",   f"{S0:.2f}",    "Last closing price used as S₀.")
    info_metric(c2, "Median (end)",    f"{p50_f:.2f}", f"{(p50_f / S0 - 1) * 100:+.1f}% vs today")
    info_metric(c3, "Bear (5th pct)",  f"{p5_f:.2f}",  f"{(p5_f  / S0 - 1) * 100:+.1f}% vs today")
    info_metric(c4, "Bull (95th pct)", f"{p95_f:.2f}", f"{(p95_f / S0 - 1) * 100:+.1f}% vs today")
    info_metric(c5, "P(end > today)",  f"{prob_up:.1%}", "Share of paths finishing above current price.")

    ann_ret = mu * 252 * 100
    ann_vol = sigma * np.sqrt(252) * 100
    n_obs = int(hist["Close"].dropna().shape[0]) if "Close" in hist.columns else "?"
    st.caption(
        f"Calibrated on {n_obs} trading days · "
        f"μ = {ann_ret:+.1f}%/yr · σ = {ann_vol:.1f}%/yr (annualized GBM parameters)"
    )


def render_ticker_lookup_page(ctx):
    render_page_title("Ticker Lookup")

    st.markdown("#### Enter a ticker symbol to look up any security")

    # Use a form so pressing Enter also triggers the search
    with st.form(key="ticker_lookup_form", border=False):
        c_input, c_btn, _ = st.columns([2, 1, 3])
        ticker_input = c_input.text_input(
            "Ticker",
            placeholder="Enter ticker symbol...",
            label_visibility="collapsed",
        )
        go_clicked = c_btn.form_submit_button("GO", type="primary", use_container_width=True)

    if go_clicked and ticker_input:
        ticker = ticker_input.upper().strip()
        st.session_state["ticker_lookup_last"] = ticker
    else:
        ticker = st.session_state.get("ticker_lookup_last", "")

    if not ticker:
        st.info("Enter a ticker symbol above and press GO to look up any security.")
        return

    st.markdown(f"### {ticker}")

    with st.spinner(f"Loading data for {ticker}..."):
        data = _cached_deep_dive(ticker)

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
        _render_monte_carlo_section(hist, ticker)
    except Exception as e:
        st.warning(f"Could not render Monte Carlo: {e}")

    try:
        _render_description(info)
    except Exception as e:
        st.warning(f"Could not render description: {e}")

    try:
        _render_news(ticker)
    except Exception as e:
        st.warning(f"Could not render news: {e}")
