"""
Yield Curve page — Bloomberg Terminal style US Treasury yield curve viewer.
Fetches available Treasury yield tickers from yfinance and plots the curve.
"""

from collections import OrderedDict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import info_section, render_page_title

# ── Constants ──────────────────────────────────────────────────────────────────

YIELD_TICKERS = OrderedDict([
    ("3M",  "^IRX"),
    ("5Y",  "^FVX"),
    ("10Y", "^TNX"),
    ("30Y", "^TYX"),
])

# Map tenor label to numeric year (for x-axis ordering)
TENOR_YEARS = {"3M": 0.25, "5Y": 5.0, "10Y": 10.0, "30Y": 30.0}

_BLOOMBERG_BG = "#0b0f14"
_GOLD = "#f3a712"
_GREEN = "#4dff4d"
_RED = "#ff4d4d"


# ── Data fetching ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=900, show_spinner=False)
def _fetch_yield_history() -> pd.DataFrame:
    """Download 1Y of daily history for all yield tickers. Returns wide DataFrame."""
    import yfinance as yf
    tickers = list(YIELD_TICKERS.values())
    try:
        raw = yf.download(tickers, period="1y", auto_adjust=True, progress=False, threads=True)
        if raw.empty:
            return pd.DataFrame()
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
        else:
            close = raw[["Close"]]
        # Rename columns from ticker symbol to tenor label
        inv = {v: k for k, v in YIELD_TICKERS.items()}
        close = close.rename(columns=inv)
        return close.dropna(how="all")
    except Exception:
        return pd.DataFrame()


def _get_snapshot(hist: pd.DataFrame, lookback_days: int) -> dict:
    """Get a dict of {tenor: yield_value} for a date ~lookback_days ago."""
    if hist.empty:
        return {}
    if lookback_days == 0:
        row = hist.iloc[-1]
    else:
        idx = max(0, len(hist) - lookback_days)
        row = hist.iloc[idx]
    return {col: float(row[col]) for col in hist.columns if pd.notna(row[col])}


# ── Chart helpers ──────────────────────────────────────────────────────────────

def _yield_curve_chart(hist: pd.DataFrame) -> go.Figure:
    """Plot yield curve: current, 1-month ago, 1-year ago."""
    fig = go.Figure()

    snapshots = {
        "Today": (_get_snapshot(hist, 0), _GOLD, 3),
        "1M Ago": (_get_snapshot(hist, 21), "#00c8ff", 2),
        "1Y Ago": (_get_snapshot(hist, 252), "#888888", 1),
    }

    for label, (snap, color, width) in snapshots.items():
        if not snap:
            continue
        sorted_tenors = sorted(snap.keys(), key=lambda t: TENOR_YEARS.get(t, 0))
        x = [TENOR_YEARS[t] for t in sorted_tenors if t in TENOR_YEARS]
        y = [snap[t] for t in sorted_tenors if t in TENOR_YEARS]
        tick_labels = [t for t in sorted_tenors if t in TENOR_YEARS]
        fig.add_trace(go.Scatter(
            x=x, y=y,
            mode="lines+markers",
            name=label,
            line=dict(color=color, width=width),
            marker=dict(size=8),
            text=tick_labels,
            hovertemplate="<b>%{text}</b><br>Yield: %{y:.2f}%<extra>" + label + "</extra>",
        ))

    fig.update_layout(
        paper_bgcolor=_BLOOMBERG_BG, plot_bgcolor=_BLOOMBERG_BG,
        font=dict(color="#e6e6e6", size=12),
        height=420,
        margin=dict(t=40, b=40, l=60, r=20),
        xaxis=dict(
            title="Maturity",
            tickvals=[0.25, 5, 10, 30],
            ticktext=["3M", "5Y", "10Y", "30Y"],
            gridcolor="#1a1f2e",
        ),
        yaxis=dict(title="Yield (%)", gridcolor="#1a1f2e"),
        legend=dict(orientation="h", y=1.05, x=0.0, font=dict(size=11)),
        hovermode="x unified",
        title=dict(text="US Treasury Yield Curve", font=dict(color=_GOLD, size=14)),
    )
    return fig


def _yield_history_chart(hist: pd.DataFrame) -> go.Figure:
    """Multi-line chart of all tenors over 1Y."""
    colors = {"3M": "#888888", "5Y": "#00c8ff", "10Y": _GOLD, "30Y": "#ce93d8"}
    fig = go.Figure()
    for tenor in hist.columns:
        s = hist[tenor].dropna()
        if s.empty:
            continue
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values,
            mode="lines",
            name=tenor,
            line=dict(color=colors.get(tenor, "#ffffff"), width=1.5),
            hovertemplate=f"%{{y:.2f}}%<extra>{tenor}</extra>",
        ))

    fig.update_layout(
        paper_bgcolor=_BLOOMBERG_BG, plot_bgcolor=_BLOOMBERG_BG,
        font=dict(color="#e6e6e6", size=12),
        height=380,
        margin=dict(t=40, b=40, l=60, r=20),
        xaxis=dict(gridcolor="#1a1f2e"),
        yaxis=dict(title="Yield (%)", gridcolor="#1a1f2e"),
        legend=dict(orientation="h", y=1.05, x=0.0, font=dict(size=11)),
        hovermode="x unified",
        title=dict(text="Treasury Yields — 1 Year History", font=dict(color=_GOLD, size=14)),
    )
    return fig


# ── Main render ────────────────────────────────────────────────────────────────

def render_yield_curve_page(ctx):
    render_page_title("Yield Curve")

    with st.spinner("Fetching Treasury yield data..."):
        hist = _fetch_yield_history()

    if hist.empty:
        st.error("Unable to fetch Treasury yield data. Try again later.")
        return

    today_snap = _get_snapshot(hist, 0)
    ago_1m_snap = _get_snapshot(hist, 21)

    # ── Inversion warning banner ──────────────────────────────────────────────
    tnx = today_snap.get("10Y")
    irx = today_snap.get("3M")
    if tnx is not None and irx is not None and irx > tnx:
        st.markdown(
            f"""<div style='background:#3d0d0d;border:1px solid {_RED};border-radius:6px;
            padding:12px 18px;margin-bottom:16px;font-family:monospace;color:{_RED};font-size:14px;'>
            ⚠ YIELD CURVE INVERTED — 3M ({irx:.2f}%) > 10Y ({tnx:.2f}%) — Recession signal active
            </div>""",
            unsafe_allow_html=True,
        )

    # ── Top metrics ───────────────────────────────────────────────────────────
    info_section("Key Rates", "Current US Treasury yields and key spread indicators.")

    spread_3m10y = (tnx - irx) if (tnx is not None and irx is not None) else None
    fvx = today_snap.get("5Y")
    tyx = today_snap.get("30Y")
    spread_5y10y = (tnx - fvx) if (tnx is not None and fvx is not None) else None

    def _delta(tenor: str) -> str | None:
        now = today_snap.get(tenor)
        ago = ago_1m_snap.get(tenor)
        if now is None or ago is None:
            return None
        return f"{now - ago:+.2f}% (1M)"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("3M T-Bill",  f"{irx:.2f}%"  if irx  is not None else "—", _delta("3M"))
    col2.metric("10Y Note",   f"{tnx:.2f}%"  if tnx  is not None else "—", _delta("10Y"))
    col3.metric("30Y Bond",   f"{tyx:.2f}%"  if tyx  is not None else "—", _delta("30Y"))
    col4.metric("3M–10Y Spread",
                f"{spread_3m10y:+.2f}%" if spread_3m10y is not None else "—",
                "Inverted" if (spread_3m10y is not None and spread_3m10y < 0) else "Normal",
                delta_color="inverse" if (spread_3m10y is not None and spread_3m10y < 0) else "normal")

    st.markdown("")

    # ── Yield curve shape chart ───────────────────────────────────────────────
    info_section("Yield Curve Shape", "Current curve vs 1 month ago vs 1 year ago.")
    st.plotly_chart(_yield_curve_chart(hist), use_container_width=True, key="yc_shape_chart")

    # ── Historical yields chart ───────────────────────────────────────────────
    info_section("Historical Yields", "Each tenor's yield over the past 12 months.")
    st.plotly_chart(_yield_history_chart(hist), use_container_width=True, key="yc_history_chart")

    # ── Data table ────────────────────────────────────────────────────────────
    info_section("Yield Data Table", "Snapshot values at key lookback points.")
    rows = []
    for tenor in list(YIELD_TICKERS.keys()):
        now_v = today_snap.get(tenor)
        ago1m = ago_1m_snap.get(tenor)
        ago1y = _get_snapshot(hist, 252).get(tenor)
        rows.append({
            "Tenor": tenor,
            "Current (%)": round(now_v, 3) if now_v else None,
            "1M Ago (%)": round(ago1m, 3) if ago1m else None,
            "1Y Ago (%)": round(ago1y, 3) if ago1y else None,
            "1M Chg (bps)": round((now_v - ago1m) * 100, 1) if (now_v and ago1m) else None,
            "1Y Chg (bps)": round((now_v - ago1y) * 100, 1) if (now_v and ago1y) else None,
        })
    tbl = pd.DataFrame(rows)

    def _color_bps(val):
        try:
            v = float(val)
            if v > 0:  return "color: #ff4d4d"
            if v < 0:  return "color: #4dff4d"
        except Exception:
            pass
        return "color: #888888"

    styled = tbl.style.map(_color_bps, subset=["1M Chg (bps)", "1Y Chg (bps)"])
    st.dataframe(styled, use_container_width=True, hide_index=True)
