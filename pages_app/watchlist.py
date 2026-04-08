import pandas as pd
import streamlit as st

from app_core import (
    get_manage_password,
    info_section,
    load_watchlist_from_sheets,
    render_page_title,
    save_watchlist_to_sheets,
)


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_watchlist_data(tickers: tuple) -> pd.DataFrame:
    import yfinance as yf

    def _safe_float(v, default=None):
        try:
            f = float(v)
            return f if f == f else default  # NaN check
        except Exception:
            return default

    rows = []
    for ticker in tickers:
        row = {
            "Ticker": ticker, "Name": ticker,
            "Price": None, "Day Δ": None, "Day Δ%": None,
            "52W High": None, "52W Low": None,
            "Volume": None, "P/E": None, "Mkt Cap": None,
        }
        try:
            t = yf.Ticker(ticker)

            # fast_info is reliable for core price data
            fi = t.fast_info
            current = _safe_float(getattr(fi, "last_price", None))
            prev    = _safe_float(getattr(fi, "previous_close", None))

            # Fallback: last row of recent history
            if current is None:
                hist = t.history(period="2d", auto_adjust=True)
                if not hist.empty:
                    current = _safe_float(hist["Close"].iloc[-1])
                    prev    = _safe_float(hist["Close"].iloc[-2]) if len(hist) >= 2 else current

            if current is not None:
                prev = prev or current
                day_chg = current - prev
                day_pct = (day_chg / prev * 100) if prev else 0.0
                row.update({
                    "Price":   round(current, 4),
                    "Day Δ":   round(day_chg, 4),
                    "Day Δ%":  round(day_pct, 2),
                    "52W High": round(h, 4) if (h := _safe_float(getattr(fi, "year_high", None))) else None,
                    "52W Low":  round(l, 4) if (l := _safe_float(getattr(fi, "year_low", None))) else None,
                    "Volume":   getattr(fi, "last_volume", None) or getattr(fi, "three_month_average_volume", None),
                    "Mkt Cap":  _safe_float(getattr(fi, "market_cap", None)),
                })

            # .info only for supplementary fields (P/E, name) — wrapped separately
            try:
                info = t.info or {}
                row["Name"] = (info.get("longName") or info.get("shortName") or ticker)[:28]
                if info.get("trailingPE"):
                    row["P/E"] = round(float(info["trailingPE"]), 1)
                if row["Mkt Cap"] is None:
                    row["Mkt Cap"] = info.get("marketCap")
            except Exception:
                pass

        except Exception:
            pass

        rows.append(row)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _fmt_large(v) -> str:
    try:
        v = float(v)
        if v >= 1e12: return f"{v / 1e12:.2f}T"
        if v >= 1e9: return f"{v / 1e9:.2f}B"
        if v >= 1e6: return f"{v / 1e6:.2f}M"
        return f"{v:,.0f}"
    except Exception:
        return "—"


def render_watchlist_page(ctx):
    render_page_title("Watchlist")

    if ctx["mode"] != "Private" or not ctx["authenticated"]:
        st.warning("Watchlist is only available in Private mode.")
        return

    @st.cache_data(ttl=30, show_spinner=False)
    def _load_tickers():
        return load_watchlist_from_sheets()

    tickers = _load_tickers()

    @st.fragment(run_every=60)
    def _live_section():
        if not tickers:
            st.info("Your watchlist is empty. Add tickers below.")
            return
        info_section("Live Prices", f"{len(tickers)} tickers · auto-refreshes every 60s")
        with st.spinner("Loading prices..."):
            df = _fetch_watchlist_data(tuple(sorted(tickers)))
        if df.empty:
            st.info("Could not load price data.")
            return
        display = df.copy()
        display["Volume"] = display["Volume"].apply(_fmt_large)
        display["Mkt Cap"] = display["Mkt Cap"].apply(_fmt_large)
        display["P/E"] = display["P/E"].apply(lambda v: f"{v:.1f}x" if v else "—")
        st.dataframe(
            display,
            use_container_width=True,
            height=max(200, 38 * len(df) + 48),
            column_config={
                "Day Δ%": st.column_config.NumberColumn("Day Δ%", format="%.2f%%"),
                "Day Δ": st.column_config.NumberColumn("Day Δ", format="%.2f"),
                "Price": st.column_config.NumberColumn("Price", format="%.2f"),
                "52W High": st.column_config.NumberColumn("52W High", format="%.2f"),
                "52W Low": st.column_config.NumberColumn("52W Low", format="%.2f"),
            },
            hide_index=True,
        )

    _live_section()

    # ── Manage ────────────────────────────────────────────────────────────────
    info_section("Manage Watchlist", "Add or remove tickers. Requires authorization password.")
    st.markdown(f"**Current:** {', '.join(tickers) if tickers else '(empty)'}")

    col_l, col_r = st.columns(2)

    with col_l:
        with st.form("wl_add_form"):
            new_ticker = st.text_input("Ticker to add", placeholder="e.g. MSFT")
            add_auth = st.text_input("Password", type="password")
            add_sub = st.form_submit_button("Add to Watchlist", use_container_width=True)
        if add_sub:
            t = new_ticker.strip().upper()
            if not t:
                st.error("Enter a ticker.")
            elif add_auth != get_manage_password():
                st.error("Wrong password.")
            elif t in tickers:
                st.warning(f"{t} already in watchlist.")
            else:
                save_watchlist_to_sheets(tickers + [t])
                st.cache_data.clear()
                st.success(f"Added {t}")
                st.rerun()

    with col_r:
        if tickers:
            with st.form("wl_remove_form"):
                to_remove = st.selectbox("Ticker to remove", tickers)
                rm_auth = st.text_input("Password", type="password", key="rm_auth")
                rm_sub = st.form_submit_button("Remove", use_container_width=True)
            if rm_sub:
                if rm_auth != get_manage_password():
                    st.error("Wrong password.")
                else:
                    save_watchlist_to_sheets([t for t in tickers if t != to_remove])
                    st.cache_data.clear()
                    st.success(f"Removed {to_remove}")
                    st.rerun()
