"""
Sector Heat Map page — S&P 500 sector ETF performance visualisation.
Uses SPDR Select Sector ETFs for 11 GICS sectors.
"""

import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import info_section, render_page_title

# ── Constants ──────────────────────────────────────────────────────────────────

SECTORS = {
    "XLK":  "Technology",
    "XLF":  "Financials",
    "XLV":  "Health Care",
    "XLY":  "Cons. Discret.",
    "XLP":  "Cons. Staples",
    "XLE":  "Energy",
    "XLI":  "Industrials",
    "XLC":  "Comm. Services",
    "XLRE": "Real Estate",
    "XLU":  "Utilities",
    "XLB":  "Materials",
}

_BLOOMBERG_BG = "#0b0f14"
_GOLD = "#f3a712"
_GREEN = "#4dff4d"
_RED = "#ff4d4d"


# ── Data fetching ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=900, show_spinner=False)
def _fetch_sector_history() -> pd.DataFrame:
    """Download 3M of daily Close prices for all sector ETFs."""
    import yfinance as yf
    tickers = list(SECTORS.keys())
    try:
        raw = yf.download(tickers, period="3mo", auto_adjust=True, progress=False, threads=True)
        if raw.empty:
            return pd.DataFrame()
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
        else:
            close = raw[["Close"]]
        return close.dropna(how="all")
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_ytd_history() -> pd.DataFrame:
    """Download YTD Close prices for all sector ETFs."""
    import yfinance as yf
    tickers = list(SECTORS.keys())
    today = datetime.date.today()
    start = datetime.date(today.year, 1, 1).isoformat()
    try:
        raw = yf.download(tickers, start=start, auto_adjust=True, progress=False, threads=True)
        if raw.empty:
            return pd.DataFrame()
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
        else:
            close = raw[["Close"]]
        return close.dropna(how="all")
    except Exception:
        return pd.DataFrame()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _pct_change(prices: pd.Series, n_days: int) -> float | None:
    """Return percentage change over the last n_days bars."""
    s = prices.dropna()
    if len(s) < 2:
        return None
    idx = max(0, len(s) - n_days - 1)
    start_price = float(s.iloc[idx])
    end_price = float(s.iloc[-1])
    if start_price == 0:
        return None
    return (end_price - start_price) / start_price * 100


def _pct_since_start(prices: pd.Series) -> float | None:
    """Return % change from first valid price to last."""
    s = prices.dropna()
    if len(s) < 2:
        return None
    start_price = float(s.iloc[0])
    end_price = float(s.iloc[-1])
    if start_price == 0:
        return None
    return (end_price - start_price) / start_price * 100


def _change_to_color(pct: float | None) -> str:
    """Map a percentage change to a hex color (dark red → dark green)."""
    if pct is None:
        return "#1a1f2e"
    # Clamp to ±5%
    clamped = max(-5.0, min(5.0, pct))
    if clamped >= 0:
        # 0→#1a3a1a, 5→#0d5e0d
        intensity = int(30 + clamped / 5.0 * 60)
        return f"#0d{intensity:02x}0d"
    else:
        intensity = int(30 + abs(clamped) / 5.0 * 60)
        return f"#{intensity:02x}0d0d"


def _text_color(pct: float | None) -> str:
    if pct is None:
        return "#888888"
    return _GREEN if pct >= 0 else _RED


# ── Heat map tile renderer ─────────────────────────────────────────────────────

def _render_heatmap_grid(day_changes: dict[str, float | None]):
    """Render the 11-sector heat map grid as HTML tiles."""
    tickers = list(SECTORS.keys())
    n_cols = 4
    rows = [tickers[i:i + n_cols] for i in range(0, len(tickers), n_cols)]

    for row_tickers in rows:
        cols = st.columns(n_cols)
        for col, ticker in zip(cols, row_tickers):
            pct = day_changes.get(ticker)
            bg = _change_to_color(pct)
            txt_color = _text_color(pct)
            pct_str = f"{pct:+.2f}%" if pct is not None else "—"
            col.markdown(
                f"""<div style='background:{bg};border:1px solid #2a2f3e;border-radius:8px;
                padding:14px 10px;text-align:center;margin-bottom:6px;min-height:90px;'>
                <div style='color:#aaa;font-size:10px;font-family:monospace;
                    text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;'>
                    {SECTORS[ticker]}</div>
                <div style='color:#e6e6e6;font-size:13px;font-family:monospace;
                    font-weight:bold;margin-bottom:4px;'>{ticker}</div>
                <div style='color:{txt_color};font-size:18px;font-family:monospace;
                    font-weight:bold;'>{pct_str}</div>
                </div>""",
                unsafe_allow_html=True,
            )
        # Fill remaining columns in last row
        for _ in range(n_cols - len(row_tickers)):
            cols[len(row_tickers) + _].empty()


# ── Charts ─────────────────────────────────────────────────────────────────────

def _bar_chart(day_changes: dict[str, float | None]) -> go.Figure:
    """Horizontal bar chart of sector day performance, sorted ascending."""
    items = [(t, v) for t, v in day_changes.items() if v is not None]
    items.sort(key=lambda x: x[1])
    tickers = [SECTORS[t] for t, _ in items]
    values = [v for _, v in items]
    colors = [_GREEN if v >= 0 else _RED for v in values]

    fig = go.Figure(go.Bar(
        x=values, y=tickers,
        orientation="h",
        marker_color=colors,
        text=[f"{v:+.2f}%" for v in values],
        textposition="outside",
        hovertemplate="%{y}: %{x:.2f}%<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor=_BLOOMBERG_BG, plot_bgcolor=_BLOOMBERG_BG,
        font=dict(color="#e6e6e6", size=12),
        height=380,
        margin=dict(t=40, b=20, l=140, r=60),
        xaxis=dict(gridcolor="#1a1f2e", title="Day Change (%)"),
        yaxis=dict(gridcolor="#1a1f2e"),
        title=dict(text="Sector Performance — Today", font=dict(color=_GOLD, size=13)),
    )
    return fig


# ── Main render ────────────────────────────────────────────────────────────────

def render_sector_heatmap_page(ctx):
    render_page_title("Sector Heat Map")

    with st.spinner("Fetching sector ETF data..."):
        hist = _fetch_sector_history()
        ytd_hist = _fetch_ytd_history()

    if hist.empty:
        st.error("Unable to fetch sector data. Try again later.")
        return

    # Compute day changes
    day_changes: dict[str, float | None] = {}
    vol_30d: dict[str, float | None] = {}
    for ticker in SECTORS:
        if ticker not in hist.columns:
            day_changes[ticker] = None
            vol_30d[ticker] = None
            continue
        s = hist[ticker].dropna()
        day_changes[ticker] = _pct_change(s, 1)
        # 30-day vol = std of daily returns * sqrt(252)
        if len(s) >= 21:
            returns = s.pct_change().dropna().tail(21)
            vol_30d[ticker] = float(returns.std() * (252 ** 0.5) * 100)
        else:
            vol_30d[ticker] = None

    # Best / worst sector today
    valid = {k: v for k, v in day_changes.items() if v is not None}
    best_ticker = max(valid, key=lambda k: valid[k]) if valid else None
    worst_ticker = min(valid, key=lambda k: valid[k]) if valid else None
    most_vol_ticker = max({k: v for k, v in vol_30d.items() if v is not None},
                          key=lambda k: vol_30d[k], default=None)

    # ── Top metrics ───────────────────────────────────────────────────────────
    info_section("Sector Snapshot", "Live sector ETF performance overview.")
    col1, col2, col3 = st.columns(3)
    if best_ticker:
        col1.metric(f"Best Today — {SECTORS[best_ticker]}",
                    f"{valid[best_ticker]:+.2f}%", f"{best_ticker}")
    else:
        col1.metric("Best Today", "—")
    if worst_ticker:
        col2.metric(f"Worst Today — {SECTORS[worst_ticker]}",
                    f"{valid[worst_ticker]:+.2f}%", f"{worst_ticker}")
    else:
        col2.metric("Worst Today", "—")
    if most_vol_ticker and vol_30d[most_vol_ticker]:
        col3.metric(f"Most Volatile — {SECTORS[most_vol_ticker]}",
                    f"{vol_30d[most_vol_ticker]:.1f}% ann.", "30-day realized vol")
    else:
        col3.metric("Most Volatile", "—")

    st.markdown("")

    # ── Heat map grid ─────────────────────────────────────────────────────────
    info_section("Heat Map", "Color intensity indicates magnitude of today's move.")
    _render_heatmap_grid(day_changes)

    st.markdown("")

    # ── Bar chart ─────────────────────────────────────────────────────────────
    info_section("Performance Bar Chart", "Sorted by today's return.")
    st.plotly_chart(_bar_chart(day_changes), use_container_width=True, key="sector_bar")

    # ── Historical performance table ──────────────────────────────────────────
    info_section("Historical Performance", "Returns across multiple time horizons.")
    perf_rows = []
    for ticker in SECTORS:
        row = {"Ticker": ticker, "Sector": SECTORS[ticker]}
        if ticker in hist.columns:
            s = hist[ticker].dropna()
            row["1D %"] = round(_pct_change(s, 1) or 0, 2)
            row["5D %"] = round(_pct_change(s, 5) or 0, 2)
            row["1M %"] = round(_pct_change(s, 21) or 0, 2)
            row["3M %"] = round(_pct_since_start(s) or 0, 2)
        else:
            row["1D %"] = row["5D %"] = row["1M %"] = row["3M %"] = None

        if not ytd_hist.empty and ticker in ytd_hist.columns:
            row["YTD %"] = round(_pct_since_start(ytd_hist[ticker].dropna()) or 0, 2)
        else:
            row["YTD %"] = None

        perf_rows.append(row)

    perf_df = pd.DataFrame(perf_rows)

    def _color_cell(val):
        try:
            v = float(val)
            if v > 0:  return "color: #4dff4d"
            if v < 0:  return "color: #ff4d4d"
        except Exception:
            pass
        return "color: #888888"

    pct_cols = ["1D %", "5D %", "1M %", "3M %", "YTD %"]
    styled = perf_df.style.map(_color_cell, subset=pct_cols)
    st.dataframe(styled, use_container_width=True, hide_index=True)
