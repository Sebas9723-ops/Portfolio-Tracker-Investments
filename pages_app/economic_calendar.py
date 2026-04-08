"""
Macro Dashboard page — key macro indicators with charts.
Section A: upcoming known economic events (hardcoded for 2025/2026).
Section B: live macro indicator grid using yfinance.
"""

import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import info_section, render_page_title

_BLOOMBERG_BG = "#0b0f14"
_GOLD = "#f3a712"
_GREEN = "#4dff4d"
_RED = "#ff4d4d"


# ── Section A: Economic Calendar ──────────────────────────────────────────────

# Recurring events for 2025 and 2026 (approximate dates — typical release schedule)
ECONOMIC_EVENTS = [
    # 2025
    {"date": "2025-01-10", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2025-01-15", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2025-01-28", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2025-01-29", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    {"date": "2025-02-07", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2025-02-12", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2025-03-07", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2025-03-12", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2025-03-18", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2025-03-19", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    {"date": "2025-04-04", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2025-04-10", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2025-04-30", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2025-05-01", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    {"date": "2025-05-02", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2025-05-13", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2025-06-06", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2025-06-11", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2025-06-17", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2025-06-18", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    {"date": "2025-07-03", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2025-07-11", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2025-07-29", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2025-07-30", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    {"date": "2025-08-01", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2025-08-12", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2025-09-05", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2025-09-10", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2025-09-16", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2025-09-17", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    {"date": "2025-10-03", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2025-10-10", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2025-10-28", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2025-10-29", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    {"date": "2025-11-07", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2025-11-12", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2025-12-05", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2025-12-10", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2025-12-16", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2025-12-17", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    # 2026
    {"date": "2026-01-09", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2026-01-14", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2026-01-27", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2026-01-28", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    {"date": "2026-02-06", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2026-02-11", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2026-03-06", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2026-03-11", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2026-03-17", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2026-03-18", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    {"date": "2026-04-03", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2026-04-08", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2026-04-28", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2026-04-29", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    {"date": "2026-05-08", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2026-05-13", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2026-06-05", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2026-06-10", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2026-06-16", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2026-06-17", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    {"date": "2026-07-10", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2026-07-15", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2026-07-28", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2026-07-29", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    {"date": "2026-08-07", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2026-08-12", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2026-09-04", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2026-09-09", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2026-09-15", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2026-09-16", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    {"date": "2026-10-02", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2026-10-07", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2026-10-27", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2026-10-28", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
    {"date": "2026-11-06", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2026-11-11", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2026-12-04", "event": "Non-Farm Payrolls", "impact": "High", "country": "US"},
    {"date": "2026-12-09", "event": "CPI (Consumer Price Index)", "impact": "High", "country": "US"},
    {"date": "2026-12-15", "event": "FOMC Meeting", "impact": "High", "country": "US"},
    {"date": "2026-12-16", "event": "FOMC Rate Decision", "impact": "High", "country": "US"},
]


# ── Section B: Macro Indicators ───────────────────────────────────────────────

MACRO_INDICATORS = [
    ("^TNX",      "US 10Y Yield",    "%",   False),
    ("^VIX",      "VIX",             "",    False),
    ("DX-Y.NYB",  "DXY Dollar",      "",    False),
    ("GC=F",      "Gold (USD/oz)",   "",    False),
    ("CL=F",      "WTI Crude",       "",    False),
    ("^GSPC",     "S&P 500",         "",    False),
    ("BTC-USD",   "Bitcoin",         "",    False),
    ("EURUSD=X",  "EUR/USD",         "",    False),
]


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_macro_history() -> dict[str, pd.Series]:
    """Fetch 1Y of daily prices for all macro tickers. Returns dict of Series."""
    import yfinance as yf
    tickers = [t for t, _, _, _ in MACRO_INDICATORS]
    out = {}
    try:
        raw = yf.download(tickers, period="1y", auto_adjust=True, progress=False, threads=True)
        if raw.empty:
            return out
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
        else:
            close = raw[["Close"]]
        for ticker in tickers:
            if ticker in close.columns:
                out[ticker] = close[ticker].dropna()
    except Exception:
        pass
    return out


def _sparkline(series: pd.Series, color: str = _GOLD) -> go.Figure:
    """Tiny sparkline chart, no axes, minimal layout."""
    fig = go.Figure(go.Scatter(
        x=series.index, y=series.values,
        mode="lines",
        line=dict(color=color, width=1.5),
        fill="tozeroy",
        fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08)",
        hoverinfo="skip",
    ))
    fig.update_layout(
        paper_bgcolor=_BLOOMBERG_BG, plot_bgcolor=_BLOOMBERG_BG,
        height=60, margin=dict(t=0, b=0, l=0, r=0),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        showlegend=False,
    )
    return fig


def _pct_chg(series: pd.Series, n: int) -> float | None:
    s = series.dropna()
    if len(s) < 2:
        return None
    idx = max(0, len(s) - n - 1)
    start = float(s.iloc[idx])
    end = float(s.iloc[-1])
    if start == 0:
        return None
    return (end - start) / abs(start) * 100


def _render_macro_card(col, ticker: str, label: str, suffix: str, series: pd.Series | None):
    """Render a single macro indicator card."""
    if series is None or series.empty:
        col.metric(label, "—")
        return

    current = float(series.iloc[-1])
    chg_1d = _pct_chg(series, 1)
    chg_1m = _pct_chg(series, 21)

    chg_str = f"{chg_1d:+.2f}%" if chg_1d is not None else None

    if abs(current) >= 1e6:
        val_str = f"{current/1e3:.0f}K"
    elif abs(current) >= 1000:
        val_str = f"{current:,.0f}"
    else:
        val_str = f"{current:.4f}"

    val_str += suffix

    col.metric(label, val_str, chg_str)

    # Sparkline
    color = _GREEN if (chg_1d or 0) >= 0 else _RED
    col.plotly_chart(_sparkline(series, color=color), use_container_width=True,
                     key=f"macro_spark_{ticker}", config={"displayModeBar": False})

    chg_1m_str = f"{chg_1m:+.2f}%" if chg_1m is not None else "—"
    col.caption(f"1M: {chg_1m_str}")


# ── Main render ────────────────────────────────────────────────────────────────

def render_economic_calendar_page(ctx):
    render_page_title("Macro Dashboard")

    @st.fragment(run_every=300)
    def _live():
        st.caption(f"Last refreshed: {datetime.datetime.now().strftime('%H:%M:%S')}")

        tab_macro, tab_cal = st.tabs(["Macro Indicators", "Economic Calendar"])

        # ── Tab: Macro Dashboard ─────────────────────────────────────────────────
        with tab_macro:
            info_section("Key Macro Indicators", "Live prices · 1Y sparklines · 1D and 1M changes.")

            with st.spinner("Fetching macro data..."):
                macro_data = _fetch_macro_history()

            n_cols = 4
            indicators = MACRO_INDICATORS
            for i in range(0, len(indicators), n_cols):
                batch = indicators[i:i + n_cols]
                cols = st.columns(n_cols)
                for col, (ticker, label, suffix, _) in zip(cols, batch):
                    series = macro_data.get(ticker)
                    _render_macro_card(col, ticker, label, suffix, series)
                st.markdown("")

            # ── Full-size 1Y charts ────────────────────────────────────────────
            st.markdown("")
            info_section("1-Year Price Charts", "Select an indicator to view.")
            selected_label = st.selectbox(
                "Indicator",
                [label for _, label, _, _ in MACRO_INDICATORS],
                key="macro_sel_indicator",
            )
            selected_ticker = next(
                (t for t, l, _, _ in MACRO_INDICATORS if l == selected_label), None
            )
            if selected_ticker and selected_ticker in macro_data:
                series = macro_data[selected_ticker]
                fig = go.Figure(go.Scatter(
                    x=series.index, y=series.values,
                    mode="lines",
                    line=dict(color=_GOLD, width=1.5),
                    fill="tozeroy",
                    fillcolor="rgba(243,167,18,0.07)",
                    hovertemplate="%{x|%b %d}<br>%{y:.4f}<extra></extra>",
                ))
                fig.update_layout(
                    paper_bgcolor=_BLOOMBERG_BG, plot_bgcolor=_BLOOMBERG_BG,
                    font=dict(color="#e6e6e6", size=12),
                    height=340,
                    margin=dict(t=30, b=30, l=60, r=20),
                    xaxis=dict(gridcolor="#1a1f2e"),
                    yaxis=dict(gridcolor="#1a1f2e"),
                    title=dict(text=selected_label, font=dict(color=_GOLD, size=13)),
                    hovermode="x unified",
                )
                st.plotly_chart(fig, use_container_width=True, key="macro_full_chart")

        # ── Tab: Economic Calendar ────────────────────────────────────────────────
        with tab_cal:
            info_section("Economic Calendar", "Key US macro events — FOMC, CPI, NFP.")

            col_filter, col_days = st.columns([2, 1])
            with col_filter:
                event_filter = st.multiselect(
                    "Event types",
                    ["Non-Farm Payrolls", "CPI (Consumer Price Index)",
                     "FOMC Meeting", "FOMC Rate Decision"],
                    default=["Non-Farm Payrolls", "CPI (Consumer Price Index)",
                             "FOMC Meeting", "FOMC Rate Decision"],
                    key="cal_event_filter",
                )
            with col_days:
                days_ahead = st.number_input("Days ahead", min_value=7, max_value=365, value=90,
                                             step=7, key="cal_days_ahead")

            today = datetime.date.today()
            cutoff = today + datetime.timedelta(days=int(days_ahead))

            filtered = []
            for ev in ECONOMIC_EVENTS:
                try:
                    d = datetime.date.fromisoformat(ev["date"])
                except Exception:
                    continue
                if today <= d <= cutoff:
                    if not event_filter or ev["event"] in event_filter:
                        filtered.append({**ev, "_date": d})

            filtered.sort(key=lambda e: e["_date"])

            if not filtered:
                st.info("No events in the selected window / filter.")
            else:
                st.markdown(f"**{len(filtered)} events** in the next {days_ahead} days.")
                st.markdown("")

                for ev in filtered:
                    d = ev["_date"]
                    days_out = (d - today).days
                    impact = ev.get("impact", "Medium")
                    impact_color = _RED if impact == "High" else _GOLD if impact == "Medium" else "#888"

                    this_week_badge = ""
                    if days_out <= 7:
                        this_week_badge = f"<span style='background:#1a3a0d;color:{_GREEN};font-size:10px;padding:1px 7px;border-radius:3px;font-family:monospace;margin-left:8px;'>THIS WEEK</span>"
                    today_badge = ""
                    if days_out == 0:
                        today_badge = f"<span style='background:#3a1a0d;color:{_GOLD};font-size:10px;padding:1px 7px;border-radius:3px;font-family:monospace;margin-left:4px;'>TODAY</span>"

                    st.markdown(
                        f"""<div style='background:#111820;border:1px solid #1e2535;border-radius:5px;
                        padding:10px 14px;margin-bottom:5px;display:flex;align-items:center;'>
                        <div style='min-width:100px;color:#888;font-size:12px;font-family:monospace;'>
                            {d.strftime('%a %b %d')}</div>
                        <div style='flex:1;'>
                            <span style='color:#e6e6e6;font-weight:bold;font-family:monospace;font-size:13px;'>
                                {ev['event']}</span>
                            {this_week_badge}{today_badge}
                            <span style='color:#888;font-size:11px;margin-left:8px;'>{ev['country']}</span>
                        </div>
                        <div style='min-width:60px;text-align:right;'>
                            <span style='color:{impact_color};font-size:11px;font-family:monospace;font-weight:bold;'>
                                {impact.upper()}</span>
                            <div style='color:#555;font-size:10px;font-family:monospace;'>
                                {days_out}d</div>
                        </div>
                        </div>""",
                        unsafe_allow_html=True,
                    )

            # ── Show all as table ──────────────────────────────────────────────
            st.markdown("")
            with st.expander("View as table", expanded=False):
                table_events = [
                    {
                        "Date": ev["date"],
                        "Event": ev["event"],
                        "Impact": ev["impact"],
                        "Country": ev["country"],
                        "Days Until": (datetime.date.fromisoformat(ev["date"]) - today).days,
                    }
                    for ev in ECONOMIC_EVENTS
                    if today <= datetime.date.fromisoformat(ev["date"]) <= cutoff
                ]
                if table_events:
                    st.dataframe(pd.DataFrame(table_events), use_container_width=True, hide_index=True)

    _live()
