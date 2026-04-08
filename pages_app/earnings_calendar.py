"""
Earnings Calendar page — upcoming earnings dates for portfolio and custom tickers.
Uses yfinance calendar / earnings_dates attributes.
"""

import datetime

import pandas as pd
import streamlit as st

from app_core import info_section, render_page_title

_BLOOMBERG_BG = "#0b0f14"
_GOLD = "#f3a712"
_GREEN = "#4dff4d"
_RED = "#ff4d4d"


# ── Data fetching ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_earnings_info(ticker: str) -> dict:
    """
    Fetch next earnings date for a ticker.
    Tries calendar first, then earnings_dates, returns a dict with fields.
    """
    import yfinance as yf
    result = {
        "ticker": ticker,
        "next_earnings": None,
        "eps_estimate": None,
        "eps_previous": None,
        "revenue_estimate": None,
        "name": ticker,
    }

    try:
        t = yf.Ticker(ticker)

        # Try fast_info for company name
        try:
            fi = t.fast_info
            result["name"] = getattr(fi, "company_name", ticker) or ticker
        except Exception:
            pass

        # Try .calendar attribute
        try:
            cal = t.calendar
            if cal is not None and not (isinstance(cal, dict) and not cal):
                if isinstance(cal, dict):
                    # Earnings Date field
                    ed = cal.get("Earnings Date") or cal.get("earnings_date")
                    if ed is not None:
                        if isinstance(ed, (list, tuple)) and len(ed) > 0:
                            result["next_earnings"] = pd.Timestamp(ed[0]).date()
                        elif hasattr(ed, "date"):
                            result["next_earnings"] = ed.date()
                    result["eps_estimate"] = cal.get("EPS Estimate") or cal.get("eps_estimate")
                    result["revenue_estimate"] = cal.get("Revenue Estimate") or cal.get("revenue_estimate")
                elif isinstance(cal, pd.DataFrame):
                    if "Earnings Date" in cal.index:
                        ed_val = cal.loc["Earnings Date"].iloc[0] if not cal.empty else None
                        if ed_val is not None:
                            result["next_earnings"] = pd.Timestamp(ed_val).date()
                    if "EPS Estimate" in cal.index:
                        result["eps_estimate"] = float(cal.loc["EPS Estimate"].iloc[0])
                    if "Revenue Estimate" in cal.index:
                        result["revenue_estimate"] = float(cal.loc["Revenue Estimate"].iloc[0])
        except Exception:
            pass

        # Fallback: earnings_dates
        if result["next_earnings"] is None:
            try:
                ed_df = t.earnings_dates
                if ed_df is not None and not ed_df.empty:
                    today = datetime.date.today()
                    future = []
                    for idx in ed_df.index:
                        d = pd.Timestamp(idx).date()
                        if d >= today:
                            future.append((d, ed_df.loc[idx]))
                    if future:
                        future.sort(key=lambda x: x[0])
                        result["next_earnings"] = future[0][0]
                        row = future[0][1]
                        if "EPS Estimate" in row:
                            result["eps_estimate"] = row["EPS Estimate"]
            except Exception:
                pass

        # EPS Previous from earnings history
        if result["eps_previous"] is None:
            try:
                earnings = t.earnings
                if earnings is not None and not earnings.empty and "Earnings" in earnings.columns:
                    result["eps_previous"] = float(earnings["Earnings"].iloc[-1])
            except Exception:
                pass

    except Exception:
        pass

    return result


# ── Helpers ────────────────────────────────────────────────────────────────────

def _days_until(d: datetime.date | None) -> int | None:
    if d is None:
        return None
    return (d - datetime.date.today()).days


def _fmt_val(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        f = float(v)
        if abs(f) >= 1e9:
            return f"{f/1e9:.2f}B"
        if abs(f) >= 1e6:
            return f"{f/1e6:.2f}M"
        return f"{f:.4f}"
    except Exception:
        return str(v)


# ── Week grouping ──────────────────────────────────────────────────────────────

def _week_label(d: datetime.date) -> str:
    monday = d - datetime.timedelta(days=d.weekday())
    friday = monday + datetime.timedelta(days=4)
    return f"Week of {monday.strftime('%b %d')} – {friday.strftime('%b %d')}"


# ── Main render ────────────────────────────────────────────────────────────────

def render_earnings_calendar_page(ctx):
    render_page_title("Earnings Calendar")

    @st.fragment(run_every=3600)
    def _live():
        st.caption(f"Last refreshed: {datetime.datetime.now().strftime('%H:%M:%S')}")

        # ── Ticker collection ─────────────────────────────────────────────────────
        portfolio_tickers = []
        try:
            df_port = ctx.get("df")
            if df_port is not None and "Ticker" in df_port.columns:
                portfolio_tickers = df_port["Ticker"].dropna().unique().tolist()
        except Exception:
            pass

        col1, col2 = st.columns([2, 1])
        with col1:
            extra_input = st.text_input(
                "Add extra tickers (comma-separated)",
                placeholder="e.g. MSFT, AMZN, TSLA",
                key="earn_extra",
            )
        with col2:
            max_days = st.number_input("Look-ahead (days)", min_value=7, max_value=180, value=60,
                                       step=7, key="earn_lookahead")

        extra_tickers = [t.strip().upper() for t in extra_input.split(",") if t.strip()]
        all_tickers = list(dict.fromkeys(portfolio_tickers + extra_tickers))  # unique, preserve order

        if not all_tickers:
            st.info("No tickers to display. Add portfolio tickers or enter custom ones above.")
            return

        portfolio_set = set(portfolio_tickers)

        # ── Fetch earnings data ───────────────────────────────────────────────────
        with st.spinner(f"Fetching earnings data for {len(all_tickers)} tickers..."):
            records = []
            for ticker in all_tickers:
                info = _fetch_earnings_info(ticker)
                records.append(info)

        # ── Filter to upcoming within look-ahead window ───────────────────────────
        today = datetime.date.today()
        cutoff = today + datetime.timedelta(days=int(max_days))

        upcoming = []
        no_date = []
        for r in records:
            d = r["next_earnings"]
            if d is None:
                no_date.append(r)
            elif today <= d <= cutoff:
                upcoming.append(r)

        upcoming.sort(key=lambda r: r["next_earnings"])

        # ── Summary metrics ───────────────────────────────────────────────────────
        info_section("Upcoming Earnings", f"Next {max_days} days · {len(upcoming)} events found.")

        this_week = [r for r in upcoming if _days_until(r["next_earnings"]) is not None
                     and _days_until(r["next_earnings"]) <= 7]
        port_upcoming = [r for r in upcoming if r["ticker"] in portfolio_set]

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("This Week", str(len(this_week)))
        col_b.metric(f"Next {max_days} Days", str(len(upcoming)))
        col_c.metric("Portfolio Companies", str(len(port_upcoming)))

        if not upcoming:
            st.info("No upcoming earnings found for the selected tickers and time window.")
        else:
            # ── Calendar view — grouped by week ───────────────────────────────────
            st.markdown("")
            info_section("Calendar View", "Grouped by week.")

            # Group
            from itertools import groupby
            def _week_key(r):
                d = r["next_earnings"]
                return d - datetime.timedelta(days=d.weekday())

            for week_start, group in groupby(upcoming, key=_week_key):
                group_list = list(group)
                week_end = week_start + datetime.timedelta(days=4)
                st.markdown(
                    f"<div style='color:{_GOLD};font-family:monospace;font-size:13px;"
                    f"font-weight:bold;margin:14px 0 6px;border-bottom:1px solid #1e2535;padding-bottom:4px;'>"
                    f"📅 {week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                for r in group_list:
                    d = r["next_earnings"]
                    days_out = _days_until(d)
                    in_portfolio = r["ticker"] in portfolio_set

                    badge = ""
                    if days_out is not None and days_out <= 7:
                        badge = f"<span style='background:#1a3a0d;color:{_GREEN};font-size:10px;padding:1px 6px;border-radius:3px;font-family:monospace;margin-left:6px;'>THIS WEEK</span>"
                    port_badge = ""
                    if in_portfolio:
                        port_badge = f"<span style='background:#1a2a0d;color:{_GOLD};font-size:10px;padding:1px 6px;border-radius:3px;font-family:monospace;margin-left:4px;'>PORTFOLIO</span>"

                    eps_str = f"EPS Est: {_fmt_val(r['eps_estimate'])}" if r["eps_estimate"] else ""
                    prev_str = f"Prev: {_fmt_val(r['eps_previous'])}" if r["eps_previous"] else ""
                    rev_str = f"Rev Est: {_fmt_val(r['revenue_estimate'])}" if r["revenue_estimate"] else ""
                    detail = " | ".join(filter(None, [eps_str, prev_str, rev_str]))

                    st.markdown(
                        f"""<div style='background:#111820;border:1px solid #1e2535;border-radius:5px;
                        padding:10px 14px;margin-bottom:5px;display:flex;align-items:center;'>
                        <div style='min-width:90px;color:#888;font-size:12px;font-family:monospace;'>
                            {d.strftime('%a %b %d')}</div>
                        <div style='flex:1;'>
                            <span style='color:#e6e6e6;font-weight:bold;font-family:monospace;font-size:13px;'>
                                {r['ticker']}</span>
                            <span style='color:#888;font-size:12px;margin-left:8px;'>{r['name']}</span>
                            {badge}{port_badge}
                            {f'<div style="color:#aaa;font-size:11px;font-family:monospace;margin-top:3px;">{detail}</div>' if detail else ''}
                        </div>
                        </div>""",
                        unsafe_allow_html=True,
                    )

        # ── Full table ────────────────────────────────────────────────────────────
        st.markdown("")
        info_section("Full Earnings Table", "All tickers with available earnings dates.")

        table_rows = []
        for r in records:
            d = r["next_earnings"]
            table_rows.append({
                "Ticker": r["ticker"],
                "Name": r["name"],
                "Earnings Date": str(d) if d else "Unknown",
                "Days Until": _days_until(d) if d else None,
                "EPS Estimate": _fmt_val(r["eps_estimate"]),
                "EPS Previous": _fmt_val(r["eps_previous"]),
                "Revenue Estimate": _fmt_val(r["revenue_estimate"]),
                "In Portfolio": "Yes" if r["ticker"] in portfolio_set else "",
            })

        tbl_df = pd.DataFrame(table_rows).sort_values(
            by="Days Until", na_position="last"
        ).reset_index(drop=True)

        def _color_days(val):
            try:
                v = int(val)
                if v <= 7:   return f"color: {_GOLD}; font-weight: bold"
                if v <= 30:  return "color: #e6e6e6"
            except Exception:
                pass
            return "color: #888"

        st.dataframe(
            tbl_df.style.map(_color_days, subset=["Days Until"]),
            use_container_width=True,
            hide_index=True,
        )

        if no_date:
            with st.expander(f"Tickers with no earnings date found ({len(no_date)})", expanded=False):
                st.write([r["ticker"] for r in no_date])

    _live()
