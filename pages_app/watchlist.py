import datetime

import pandas as pd
import streamlit as st

from app_core import (
    get_manage_password,
    info_section,
    load_watchlist_from_sheets,
    render_page_title,
    save_watchlist_to_sheets,
)

# ── Preset universe ────────────────────────────────────────────────────────────

_PRESETS: dict[str, dict] = {
    "Indices": {
        "tickers": ["^GSPC", "^NDX", "^DJI", "^RUT", "^VIX", "^FTSE", "^GDAXI", "^N225", "^HSI", "^STOXX50E"],
        "names": {
            "^GSPC": "S&P 500", "^NDX": "Nasdaq 100", "^DJI": "Dow Jones",
            "^RUT": "Russell 2000", "^VIX": "VIX", "^FTSE": "FTSE 100",
            "^GDAXI": "DAX", "^N225": "Nikkei 225", "^HSI": "Hang Seng",
            "^STOXX50E": "Euro Stoxx 50",
        },
    },
    "Futures": {
        "tickers": ["ES=F", "NQ=F", "YM=F", "RTY=F", "CL=F", "BZ=F", "GC=F", "SI=F", "HG=F", "ZB=F", "ZN=F"],
        "names": {
            "ES=F": "S&P 500 Futures", "NQ=F": "Nasdaq Futures", "YM=F": "Dow Futures",
            "RTY=F": "Russell Futures", "CL=F": "WTI Crude Oil", "BZ=F": "Brent Crude",
            "GC=F": "Gold Futures", "SI=F": "Silver Futures", "HG=F": "Copper Futures",
            "ZB=F": "30Y T-Bond Fut", "ZN=F": "10Y T-Note Fut",
        },
    },
    "FX": {
        "tickers": ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X", "AUDUSD=X",
                    "USDCOP=X", "USDMXN=X", "EURGBP=X", "USDCAD=X", "NZDUSD=X"],
        "names": {
            "EURUSD=X": "EUR / USD", "GBPUSD=X": "GBP / USD", "USDJPY=X": "USD / JPY",
            "USDCHF=X": "USD / CHF", "AUDUSD=X": "AUD / USD", "USDCOP=X": "USD / COP",
            "USDMXN=X": "USD / MXN", "EURGBP=X": "EUR / GBP", "USDCAD=X": "USD / CAD",
            "NZDUSD=X": "NZD / USD",
        },
    },
    "Rates & Bonds": {
        "tickers": ["^IRX", "^FVX", "^TNX", "^TYX", "TLT", "IEF", "SHY", "HYG", "LQD", "BND"],
        "names": {
            "^IRX": "3M T-Bill Yield", "^FVX": "5Y Treasury Yield",
            "^TNX": "10Y Treasury Yield", "^TYX": "30Y Treasury Yield",
            "TLT": "iShares 20Y+ Bond", "IEF": "iShares 7-10Y Bond",
            "SHY": "iShares 1-3Y Bond", "HYG": "High Yield Corp",
            "LQD": "Invest Grade Corp", "BND": "Total Bond Market",
        },
    },
    "Commodities": {
        "tickers": ["GC=F", "SI=F", "CL=F", "BZ=F", "NG=F", "HG=F", "ZW=F", "ZC=F", "ZS=F", "CC=F"],
        "names": {
            "GC=F": "Gold", "SI=F": "Silver", "CL=F": "WTI Crude Oil",
            "BZ=F": "Brent Crude Oil", "NG=F": "Natural Gas", "HG=F": "Copper",
            "ZW=F": "Wheat", "ZC=F": "Corn", "ZS=F": "Soybeans", "CC=F": "Cocoa",
        },
    },
    "Crypto": {
        "tickers": ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "ADA-USD", "AVAX-USD", "DOGE-USD"],
        "names": {
            "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana",
            "BNB-USD": "BNB", "XRP-USD": "XRP", "ADA-USD": "Cardano",
            "AVAX-USD": "Avalanche", "DOGE-USD": "Dogecoin",
        },
    },
}

# Tickers shown in the top summary bar
_SUMMARY_TICKERS = [
    ("^GSPC", "SPX"), ("^NDX", "NDX"), ("^DJI", "DJIA"), ("^VIX", "VIX"),
    ("^TNX", "10Y Yld"), ("CL=F", "WTI"), ("GC=F", "Gold"),
    ("BTC-USD", "BTC"), ("EURUSD=X", "EUR/USD"),
]

# ── Data fetching ──────────────────────────────────────────────────────────────

def _safe_float(v, default=None):
    try:
        f = float(v)
        return f if f == f else default
    except Exception:
        return default


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_tickers(tickers: tuple, preset_names: tuple = ()) -> pd.DataFrame:
    """preset_names: tuple of (ticker, name) pairs — must be hashable for cache."""
    import yfinance as yf

    names_map = dict(preset_names)
    rows = []
    for ticker in tickers:
        row = {
            "Ticker": ticker,
            "Name": names_map.get(ticker, ticker),
            "Price": None, "Day Δ": None, "Day Δ%": None,
            "52W High": None, "52W Low": None,
            "Volume": None, "Mkt Cap": None,
        }
        try:
            t = yf.Ticker(ticker)
            fi = t.fast_info

            current = _safe_float(getattr(fi, "last_price", None))
            prev    = _safe_float(getattr(fi, "previous_close", None))

            if current is None:
                hist = t.history(period="2d", auto_adjust=True)
                if not hist.empty:
                    current = _safe_float(hist["Close"].iloc[-1])
                    prev    = _safe_float(hist["Close"].iloc[-2]) if len(hist) >= 2 else current

            if current is not None:
                prev    = prev or current
                day_chg = current - prev
                day_pct = (day_chg / prev * 100) if prev else 0.0
                row.update({
                    "Price":    round(current, 4),
                    "Day Δ":    round(day_chg, 4),
                    "Day Δ%":   round(day_pct, 2),
                    "52W High": round(h, 4) if (h := _safe_float(getattr(fi, "year_high", None))) else None,
                    "52W Low":  round(l, 4) if (l := _safe_float(getattr(fi, "year_low", None))) else None,
                    "Volume":   getattr(fi, "last_volume", None),
                    "Mkt Cap":  _safe_float(getattr(fi, "market_cap", None)),
                })

            # Name from .info only when no preset name provided
            if not names_map.get(ticker):
                try:
                    info = t.info or {}
                    row["Name"] = (info.get("longName") or info.get("shortName") or ticker)[:30]
                except Exception:
                    pass

        except Exception:
            pass

        rows.append(row)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _fmt_large(v) -> str:
    try:
        v = float(v)
        if v >= 1e12: return f"{v / 1e12:.2f}T"
        if v >= 1e9:  return f"{v / 1e9:.2f}B"
        if v >= 1e6:  return f"{v / 1e6:.2f}M"
        return f"{v:,.0f}"
    except Exception:
        return "—"


def _color_delta(val):
    try:
        f = float(val)
        if f > 0:  return "color: #4dff4d; font-weight: 600"
        if f < 0:  return "color: #ff4d4d; font-weight: 600"
    except Exception:
        pass
    return "color: #888888"


def _style_table(df: pd.DataFrame) -> object:
    subset = [c for c in ["Day Δ", "Day Δ%"] if c in df.columns]
    if not subset:
        return df.style
    return df.style.map(_color_delta, subset=subset)


def _render_table(df: pd.DataFrame, show_mktcap: bool = True):
    if df.empty:
        st.info("No data available.")
        return

    display = df.copy()
    if "Volume" in display.columns:
        display["Volume"] = display["Volume"].apply(_fmt_large)
    if show_mktcap and "Mkt Cap" in display.columns:
        display["Mkt Cap"] = display["Mkt Cap"].apply(_fmt_large)
    elif "Mkt Cap" in display.columns:
        display = display.drop(columns=["Mkt Cap"])

    cols = [c for c in ["Ticker", "Name", "Price", "Day Δ", "Day Δ%", "52W High", "52W Low", "Volume", "Mkt Cap"] if c in display.columns]
    display = display[cols]

    styled = _style_table(display)
    st.dataframe(
        styled,
        use_container_width=True,
        height=min(600, max(200, 38 * len(df) + 48)),
        column_config={
            "Price":    st.column_config.NumberColumn("Price",    format="%.4f"),
            "Day Δ":   st.column_config.NumberColumn("Day Δ",   format="%.4f"),
            "Day Δ%":  st.column_config.NumberColumn("Day Δ%",  format="%.2f%%"),
            "52W High": st.column_config.NumberColumn("52W High", format="%.4f"),
            "52W Low":  st.column_config.NumberColumn("52W Low",  format="%.4f"),
        },
        hide_index=True,
    )


# ── Summary bar ────────────────────────────────────────────────────────────────

@st.fragment(run_every=60)
def _render_summary_bar():
    tickers = tuple(t for t, _ in _SUMMARY_TICKERS)
    names   = tuple(_SUMMARY_TICKERS)  # already (ticker, label) pairs
    df = _fetch_tickers(tickers, preset_names=names)
    if df.empty:
        return

    cols = st.columns(len(_SUMMARY_TICKERS))
    for col, (ticker, label) in zip(cols, _SUMMARY_TICKERS):
        row = df[df["Ticker"] == ticker]
        if row.empty:
            col.metric(label, "—")
            continue
        price = row["Price"].iloc[0]
        pct   = row["Day Δ%"].iloc[0]
        price_str = f"{price:,.4f}" if price is not None else "—"
        delta_str = f"{pct:+.2f}%" if pct is not None else None
        col.metric(label, price_str, delta_str)


# ── Main page ──────────────────────────────────────────────────────────────────

def render_watchlist_page(ctx):
    render_page_title("Watchlist")

    if ctx["mode"] != "Private" or not ctx["authenticated"]:
        st.warning("Watchlist is only available in Private mode.")
        return

    # ── Summary bar ───────────────────────────────────────────────────────────
    info_section(
        "Market Overview",
        f"Live snapshot · auto-refreshes every 60s · {datetime.datetime.now().strftime('%H:%M:%S')}",
    )
    _render_summary_bar()

    st.divider()

    # ── Category tabs ─────────────────────────────────────────────────────────
    @st.cache_data(ttl=30, show_spinner=False)
    def _load_custom_tickers():
        return load_watchlist_from_sheets()

    custom_tickers = _load_custom_tickers()

    tab_labels = list(_PRESETS.keys()) + ["My Watchlist"]
    tabs = st.tabs(tab_labels)

    for tab, (category, meta) in zip(tabs[:-1], _PRESETS.items()):
        with tab:
            df = _fetch_tickers(
                tuple(meta["tickers"]),
                preset_names=tuple(meta["names"].items()),
            )
            show_cap = category not in ("FX", "Rates & Bonds", "Indices", "Futures")
            _render_table(df, show_mktcap=show_cap)

    with tabs[-1]:
        if not custom_tickers:
            st.info("Your watchlist is empty. Add tickers below.")
        else:
            df = _fetch_tickers(tuple(sorted(custom_tickers)))
            _render_table(df, show_mktcap=True)

    # ── Manage ────────────────────────────────────────────────────────────────
    st.divider()
    with st.expander("Manage My Watchlist", expanded=False):
        st.caption(f"Current tickers: {', '.join(custom_tickers) if custom_tickers else '(empty)'}")
        col_l, col_r = st.columns(2)

        with col_l:
            with st.form("wl_add_form"):
                new_ticker = st.text_input("Ticker to add", placeholder="e.g. MSFT, VWCE.DE, BTC-USD")
                add_auth   = st.text_input("Password", type="password")
                add_sub    = st.form_submit_button("Add to Watchlist", use_container_width=True)
            if add_sub:
                t = new_ticker.strip().upper()
                if not t:
                    st.error("Enter a ticker.")
                elif add_auth != get_manage_password():
                    st.error("Wrong password.")
                elif t in custom_tickers:
                    st.warning(f"{t} already in watchlist.")
                else:
                    save_watchlist_to_sheets(custom_tickers + [t])
                    st.cache_data.clear()
                    st.success(f"Added {t}")
                    st.rerun()

        with col_r:
            if custom_tickers:
                with st.form("wl_remove_form"):
                    to_remove = st.selectbox("Ticker to remove", custom_tickers)
                    rm_auth   = st.text_input("Password", type="password", key="rm_auth")
                    rm_sub    = st.form_submit_button("Remove", use_container_width=True)
                if rm_sub:
                    if rm_auth != get_manage_password():
                        st.error("Wrong password.")
                    else:
                        save_watchlist_to_sheets([t for t in custom_tickers if t != to_remove])
                        st.cache_data.clear()
                        st.success(f"Removed {to_remove}")
                        st.rerun()
