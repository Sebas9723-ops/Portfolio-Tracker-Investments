import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from app_core import info_section, render_page_title


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_ohlcv(ticker: str, period: str) -> pd.DataFrame:
    import yfinance as yf
    return yf.Ticker(ticker).history(period=period)


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"]
    df = df.copy()

    # Moving averages
    df["SMA20"] = close.rolling(20).mean()
    df["SMA50"] = close.rolling(50).mean()
    df["SMA200"] = close.rolling(200).mean()

    # Bollinger Bands (20, 2σ)
    std20 = close.rolling(20).std()
    df["BB_Mid"] = close.rolling(20).mean()
    df["BB_Upper"] = df["BB_Mid"] + 2 * std20
    df["BB_Lower"] = df["BB_Mid"] - 2 * std20

    # RSI (14)
    delta = close.diff()
    avg_gain = delta.clip(lower=0).rolling(14).mean()
    avg_loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - 100 / (1 + rs)

    # MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

    return df


def _has_ohlc(df: pd.DataFrame) -> bool:
    return all(c in df.columns for c in ("Open", "High", "Low", "Close"))


def _build_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    # 4-panel layout: Price | Volume | RSI | MACD
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.50, 0.15, 0.20, 0.15],
        subplot_titles=[
            f"{ticker} · Price & Indicators",
            "Volume",
            "RSI (14)",
            "MACD (12/26/9)",
        ],
    )

    # ── Row 1: Bollinger band fill ──────────────────────────────────────────
    x_fwd = df.index.tolist()
    x_rev = x_fwd[::-1]
    fig.add_trace(go.Scatter(
        x=x_fwd + x_rev,
        y=df["BB_Upper"].tolist() + df["BB_Lower"].tolist()[::-1],
        fill="toself",
        fillcolor="rgba(100,149,237,0.07)",
        line=dict(color="rgba(0,0,0,0)"),
        name="Bollinger",
        hoverinfo="skip",
        showlegend=False,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["BB_Upper"],
        line=dict(color="#6495ed", width=1, dash="dot"),
        name="BB Upper",
        hovertemplate="%{y:.2f}<extra>BB Upper</extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["BB_Lower"],
        line=dict(color="#6495ed", width=1, dash="dot"),
        name="BB Lower",
        hovertemplate="%{y:.2f}<extra>BB Lower</extra>",
    ), row=1, col=1)

    # Candlestick (fall back to line if OHLC missing)
    if _has_ohlc(df):
        fig.add_trace(go.Candlestick(
            x=df.index,
            open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
            increasing_line_color="#00e676",
            decreasing_line_color="#f44336",
            name="Price",
        ), row=1, col=1)
    else:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["Close"],
            line=dict(color="#f3a712", width=1.5),
            name="Price",
            hovertemplate="%{y:.2f}<extra>Price</extra>",
        ), row=1, col=1)

    # Moving averages overlay
    for col_name, color, label in [
        ("SMA20", "#f3a712", "SMA 20"),
        ("SMA50", "#00c8ff", "SMA 50"),
        ("SMA200", "#ce93d8", "SMA 200"),
    ]:
        s = df[col_name].dropna()
        if not s.empty:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[col_name],
                line=dict(color=color, width=1.5),
                name=label,
                hovertemplate=f"%{{y:.2f}}<extra>{label}</extra>",
            ), row=1, col=1)

    # ── Row 2: Volume bars ──────────────────────────────────────────────────
    if "Volume" in df.columns:
        # Color volume bars by price direction
        has_open = "Open" in df.columns
        if has_open:
            vol_colors = [
                "#00e676" if c >= o else "#f44336"
                for c, o in zip(df["Close"], df["Open"])
            ]
        else:
            vol_colors = ["#f3a712"] * len(df)

        fig.add_trace(go.Bar(
            x=df.index,
            y=df["Volume"],
            marker_color=vol_colors,
            marker_opacity=0.6,
            name="Volume",
            hovertemplate="%{y:,.0f}<extra>Volume</extra>",
        ), row=2, col=1)

    # ── Row 3: RSI ──────────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df.index, y=df["RSI"],
        line=dict(color="#f3a712", width=1.5),
        name="RSI",
        hovertemplate="%{y:.1f}<extra>RSI</extra>",
    ), row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#f44336", line_width=1, row=3, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#00e676", line_width=1, row=3, col=1)
    fig.add_hrect(y0=70, y1=100, fillcolor="rgba(244,67,54,0.05)", line_width=0, row=3, col=1)
    fig.add_hrect(y0=0,  y1=30,  fillcolor="rgba(0,230,118,0.05)", line_width=0, row=3, col=1)

    # ── Row 4: MACD ─────────────────────────────────────────────────────────
    hist_colors = ["#00e676" if v >= 0 else "#f44336" for v in df["MACD_Hist"].fillna(0)]
    fig.add_trace(go.Bar(
        x=df.index, y=df["MACD_Hist"],
        marker_color=hist_colors,
        name="Histogram",
        hovertemplate="%{y:.4f}<extra>Hist</extra>",
    ), row=4, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["MACD"],
        line=dict(color="#00c8ff", width=1.5),
        name="MACD",
        hovertemplate="%{y:.4f}<extra>MACD</extra>",
    ), row=4, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["MACD_Signal"],
        line=dict(color="#f3a712", width=1.5),
        name="Signal",
        hovertemplate="%{y:.4f}<extra>Signal</extra>",
    ), row=4, col=1)

    # ── Layout ───────────────────────────────────────────────────────────────
    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6", size=12),
        height=860,
        margin=dict(t=60, b=20, l=60, r=20),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02, x=0.0, font=dict(size=11)),
        hovermode="x unified",
        bargap=0,
    )
    for i in range(1, 5):
        fig.update_xaxes(gridcolor="#1a1f2e", row=i, col=1)
        fig.update_yaxes(gridcolor="#1a1f2e", row=i, col=1)

    # RSI y-axis fixed range
    fig.update_yaxes(range=[0, 100], row=3, col=1)

    return fig


def _signal_badge(label: str, val, is_bullish) -> str:
    if is_bullish is None:
        bg, fg, text = "#1a1f2e", "#888", "NEUTRAL"
    elif is_bullish:
        bg, fg, text = "#0d3d0d", "#00e676", "BULLISH"
    else:
        bg, fg, text = "#3d0d0d", "#f44336", "BEARISH"
    try:
        val_str = f"{float(val):.2f}"
    except Exception:
        val_str = "—"
    return (
        f"<div style='background:{bg};border:1px solid {fg};border-radius:6px;"
        f"padding:10px 14px;margin:4px 6px 4px 0;display:inline-block;min-width:130px;vertical-align:top'>"
        f"<div style='color:#888;font-size:11px;font-family:monospace;margin-bottom:2px'>{label}</div>"
        f"<div style='color:{fg};font-size:15px;font-weight:bold;font-family:monospace'>{text}</div>"
        f"<div style='color:#aaa;font-size:12px;font-family:monospace'>{val_str}</div>"
        f"</div>"
    )


def render_technicals_page(ctx):
    render_page_title("Technical Analysis")

    @st.fragment(run_every=900)
    def _live():
        st.caption(f"Last refreshed: {datetime.datetime.now().strftime('%H:%M:%S')}")

        portfolio_tickers = list(ctx.get("updated_portfolio", {}).keys())

        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            use_custom = st.checkbox("Custom ticker", value=False, key="ta_use_custom")
        with c2:
            if use_custom:
                ticker = st.text_input(
                    "Ticker", placeholder="e.g. NVDA",
                    label_visibility="collapsed", key="ta_custom_input",
                ).upper().strip()
            else:
                ticker = (
                    st.selectbox("Select ticker", portfolio_tickers, key="ta_portfolio_sel")
                    if portfolio_tickers else ""
                )
        with c3:
            period = st.selectbox("Period", ["3mo", "6mo", "1y", "2y", "5y"], index=1, key="ta_period")

        if not ticker:
            st.info("Select or enter a ticker to load technical analysis.")
            return

        with st.spinner(f"Loading {ticker}..."):
            raw = _fetch_ohlcv(ticker, period)

        if raw is None or raw.empty:
            st.error(f"No price data found for {ticker}.")
            return

        df = _compute_indicators(raw)
        close = float(df["Close"].iloc[-1])

        rsi_s      = df["RSI"].dropna()
        macd_s     = df["MACD"].dropna()
        sig_s      = df["MACD_Signal"].dropna()
        sma20_s    = df["SMA20"].dropna()
        sma50_s    = df["SMA50"].dropna()
        sma200_s   = df["SMA200"].dropna()
        bb_upper_s = df["BB_Upper"].dropna()
        bb_lower_s = df["BB_Lower"].dropna()

        rsi_val  = float(rsi_s.iloc[-1])  if not rsi_s.empty  else None
        macd_val = float(macd_s.iloc[-1]) if not macd_s.empty else None
        sig_val  = float(sig_s.iloc[-1])  if not sig_s.empty  else None

        # Signal badges
        badges = []
        if rsi_val is not None:
            badges.append(_signal_badge("RSI (14)", rsi_val, rsi_val > 50))
        if macd_val is not None and sig_val is not None:
            badges.append(_signal_badge("MACD", macd_val, macd_val > sig_val))
        if not sma20_s.empty:
            badges.append(_signal_badge("vs SMA 20", float(sma20_s.iloc[-1]), close > float(sma20_s.iloc[-1])))
        if not sma50_s.empty:
            badges.append(_signal_badge("vs SMA 50", float(sma50_s.iloc[-1]), close > float(sma50_s.iloc[-1])))
        if not sma200_s.empty:
            badges.append(_signal_badge("vs SMA 200", float(sma200_s.iloc[-1]), close > float(sma200_s.iloc[-1])))

        if badges:
            info_section("Signal Summary", "Bullish/Bearish read for each indicator vs current price.")
            st.markdown("".join(badges), unsafe_allow_html=True)

        st.markdown("")
        info_section(
            "Chart",
            f"{ticker} · {period} · Candlestick · SMA 20/50/200 · Bollinger Bands · Volume · RSI · MACD",
        )
        st.plotly_chart(_build_chart(df, ticker), use_container_width=True, key=f"ta_{ticker}_{period}")

        info_section("Key Levels", "Price vs moving averages and Bollinger Bands.")
        cols = st.columns(6)
        metrics = [
            ("Price",    f"{close:.2f}"),
            ("SMA 20",   f"{float(sma20_s.iloc[-1]):.2f}"    if not sma20_s.empty    else "—"),
            ("SMA 50",   f"{float(sma50_s.iloc[-1]):.2f}"    if not sma50_s.empty    else "—"),
            ("SMA 200",  f"{float(sma200_s.iloc[-1]):.2f}"   if not sma200_s.empty   else "—"),
            ("BB Upper", f"{float(bb_upper_s.iloc[-1]):.2f}" if not bb_upper_s.empty else "—"),
            ("BB Lower", f"{float(bb_lower_s.iloc[-1]):.2f}" if not bb_lower_s.empty else "—"),
        ]
        for col, (label, val) in zip(cols, metrics):
            col.metric(label, val)

    _live()
