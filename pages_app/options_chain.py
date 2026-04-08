import datetime
"""
Options Chain page — live options chain viewer for any ticker.
Uses yfinance option_chain() for data. No external API keys required.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import info_section, render_page_title

_BLOOMBERG_BG = "#0b0f14"
_GOLD = "#f3a712"
_GREEN = "#4dff4d"
_RED = "#ff4d4d"


# ── Data fetching ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _fetch_current_price(ticker: str) -> float | None:
    import yfinance as yf
    try:
        fi = yf.Ticker(ticker).fast_info
        price = getattr(fi, "last_price", None)
        return float(price) if price else None
    except Exception:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_options_expiries(ticker: str) -> list[str]:
    import yfinance as yf
    try:
        return list(yf.Ticker(ticker).options)
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_option_chain(ticker: str, expiry: str):
    """Returns (calls_df, puts_df) tuple."""
    import yfinance as yf
    try:
        chain = yf.Ticker(ticker).option_chain(expiry)
        return chain.calls, chain.puts
    except Exception:
        return pd.DataFrame(), pd.DataFrame()


# ── Metrics helpers ────────────────────────────────────────────────────────────

def _compute_max_pain(calls: pd.DataFrame, puts: pd.DataFrame) -> float | None:
    """Compute max pain strike (strike where total option value is minimised)."""
    if calls.empty or puts.empty:
        return None
    try:
        strikes = sorted(set(calls["strike"].tolist() + puts["strike"].tolist()))
        min_pain = None
        pain_strike = None
        for s in strikes:
            call_pain = sum(
                max(0.0, float(s) - float(k)) * float(oi)
                for k, oi in zip(calls["strike"], calls["openInterest"])
                if pd.notna(k) and pd.notna(oi)
            )
            put_pain = sum(
                max(0.0, float(k) - float(s)) * float(oi)
                for k, oi in zip(puts["strike"], puts["openInterest"])
                if pd.notna(k) and pd.notna(oi)
            )
            total = call_pain + put_pain
            if min_pain is None or total < min_pain:
                min_pain = total
                pain_strike = s
        return pain_strike
    except Exception:
        return None


def _compute_put_call_ratio(calls: pd.DataFrame, puts: pd.DataFrame) -> float | None:
    try:
        call_vol = calls["volume"].fillna(0).sum()
        put_vol = puts["volume"].fillna(0).sum()
        if call_vol == 0:
            return None
        return round(float(put_vol) / float(call_vol), 3)
    except Exception:
        return None


def _atm_iv(chain_df: pd.DataFrame, current_price: float) -> float | None:
    """Find the closest-to-ATM implied volatility."""
    if chain_df.empty or "impliedVolatility" not in chain_df.columns:
        return None
    try:
        df = chain_df.copy()
        df["distance"] = abs(df["strike"] - current_price)
        df = df.sort_values("distance")
        iv = df["impliedVolatility"].iloc[0]
        return float(iv) * 100 if pd.notna(iv) else None
    except Exception:
        return None


# ── Table preparation ─────────────────────────────────────────────────────────

def _prepare_chain_table(df: pd.DataFrame, current_price: float, is_calls: bool) -> pd.DataFrame:
    """Select and format columns for display."""
    if df.empty:
        return pd.DataFrame()
    cols = ["strike", "lastPrice", "bid", "ask", "volume", "openInterest",
            "impliedVolatility", "inTheMoney"]
    present = [c for c in cols if c in df.columns]
    out = df[present].copy()
    rename = {
        "strike": "Strike", "lastPrice": "Last", "bid": "Bid", "ask": "Ask",
        "volume": "Volume", "openInterest": "OI", "impliedVolatility": "IV",
        "inTheMoney": "ITM",
    }
    out = out.rename(columns=rename)
    if "IV" in out.columns:
        out["IV"] = (out["IV"] * 100).round(1).astype(str) + "%"
    for c in ["Strike", "Last", "Bid", "Ask"]:
        if c in out.columns:
            out[c] = out[c].round(2)
    for c in ["Volume", "OI"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).astype(int)
    return out.reset_index(drop=True)


# ── Charts ─────────────────────────────────────────────────────────────────────

def _oi_chart(calls: pd.DataFrame, puts: pd.DataFrame, current_price: float) -> go.Figure:
    """Open interest by strike: calls green bars, puts red bars."""
    fig = go.Figure()

    if not calls.empty and "strike" in calls.columns and "openInterest" in calls.columns:
        c = calls[["strike", "openInterest"]].dropna()
        fig.add_trace(go.Bar(
            x=c["strike"], y=c["openInterest"],
            name="Calls OI", marker_color="rgba(77,255,77,0.6)",
            hovertemplate="Strike: %{x}<br>OI: %{y:,}<extra>Calls</extra>",
        ))

    if not puts.empty and "strike" in puts.columns and "openInterest" in puts.columns:
        p = puts[["strike", "openInterest"]].dropna()
        fig.add_trace(go.Bar(
            x=p["strike"], y=p["openInterest"],
            name="Puts OI", marker_color="rgba(255,77,77,0.6)",
            hovertemplate="Strike: %{x}<br>OI: %{y:,}<extra>Puts</extra>",
        ))

    fig.add_vline(x=current_price, line_dash="dash", line_color=_GOLD, line_width=1.5,
                  annotation_text=f"Spot: {current_price:.2f}", annotation_font_color=_GOLD)

    fig.update_layout(
        barmode="overlay",
        paper_bgcolor=_BLOOMBERG_BG, plot_bgcolor=_BLOOMBERG_BG,
        font=dict(color="#e6e6e6", size=12),
        height=380,
        margin=dict(t=40, b=40, l=60, r=20),
        xaxis=dict(title="Strike", gridcolor="#1a1f2e"),
        yaxis=dict(title="Open Interest", gridcolor="#1a1f2e"),
        legend=dict(orientation="h", y=1.05, x=0.0),
        title=dict(text="Open Interest by Strike", font=dict(color=_GOLD, size=13)),
    )
    return fig


def _iv_smile_chart(calls: pd.DataFrame, puts: pd.DataFrame, current_price: float) -> go.Figure:
    """IV smile: implied vol vs strike for calls and puts."""
    fig = go.Figure()

    if not calls.empty and "strike" in calls.columns and "impliedVolatility" in calls.columns:
        c = calls[["strike", "impliedVolatility"]].dropna().sort_values("strike")
        fig.add_trace(go.Scatter(
            x=c["strike"], y=c["impliedVolatility"] * 100,
            mode="lines+markers", name="Calls IV",
            line=dict(color=_GREEN, width=1.5),
            marker=dict(size=4),
            hovertemplate="Strike: %{x}<br>IV: %{y:.1f}%<extra>Calls</extra>",
        ))

    if not puts.empty and "strike" in puts.columns and "impliedVolatility" in puts.columns:
        p = puts[["strike", "impliedVolatility"]].dropna().sort_values("strike")
        fig.add_trace(go.Scatter(
            x=p["strike"], y=p["impliedVolatility"] * 100,
            mode="lines+markers", name="Puts IV",
            line=dict(color=_RED, width=1.5),
            marker=dict(size=4),
            hovertemplate="Strike: %{x}<br>IV: %{y:.1f}%<extra>Puts</extra>",
        ))

    fig.add_vline(x=current_price, line_dash="dash", line_color=_GOLD, line_width=1.5,
                  annotation_text=f"Spot: {current_price:.2f}", annotation_font_color=_GOLD)

    fig.update_layout(
        paper_bgcolor=_BLOOMBERG_BG, plot_bgcolor=_BLOOMBERG_BG,
        font=dict(color="#e6e6e6", size=12),
        height=340,
        margin=dict(t=40, b=40, l=60, r=20),
        xaxis=dict(title="Strike", gridcolor="#1a1f2e"),
        yaxis=dict(title="Implied Volatility (%)", gridcolor="#1a1f2e"),
        legend=dict(orientation="h", y=1.05, x=0.0),
        title=dict(text="Implied Volatility Smile", font=dict(color=_GOLD, size=13)),
    )
    return fig


# ── Main render ────────────────────────────────────────────────────────────────

def render_options_chain_page(ctx):
    render_page_title("Options Chain")

    @st.fragment(run_every=60)
    def _live():
        st.caption(f"Last refreshed: {datetime.datetime.now().strftime('%H:%M:%S')}")

        # ── Ticker input ──────────────────────────────────────────────────────────
        portfolio_tickers = list(ctx.get("updated_portfolio", {}).keys())
        default_ticker = portfolio_tickers[0] if portfolio_tickers else "AAPL"

        col_ticker, col_expiry = st.columns([2, 2])
        with col_ticker:
            ticker = st.text_input("Ticker", value=default_ticker, key="opt_ticker").upper().strip()

        if not ticker:
            st.info("Enter a ticker to load options chain.")
            return

        with st.spinner(f"Loading options for {ticker}..."):
            expiries = _fetch_options_expiries(ticker)
            current_price = _fetch_current_price(ticker)

        if not expiries:
            st.error(f"No options data available for {ticker}. Options may not trade on this security.")
            return

        with col_expiry:
            selected_expiry = st.selectbox("Expiry", expiries, key="opt_expiry")

        if not selected_expiry:
            return

        with st.spinner("Loading option chain..."):
            calls, puts = _fetch_option_chain(ticker, selected_expiry)

        if calls.empty and puts.empty:
            st.error("Could not load option chain. Try a different expiry.")
            return

        price = current_price or 0.0

        # ── Key metrics ───────────────────────────────────────────────────────────
        info_section("Options Metrics", f"{ticker} · Expiry: {selected_expiry}")

        atm = _atm_iv(calls if not calls.empty else puts, price)
        pcr = _compute_put_call_ratio(calls, puts)
        max_pain = _compute_max_pain(calls, puts)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Current Price", f"{price:.2f}" if price else "—")
        col2.metric("ATM IV", f"{atm:.1f}%" if atm else "—")
        col3.metric("Put/Call Ratio", f"{pcr:.3f}" if pcr else "—")
        col4.metric("Max Pain", f"{max_pain:.2f}" if max_pain else "—")

        st.markdown("")

        # ── Side-by-side chains ───────────────────────────────────────────────────
        info_section("Option Chain", "Calls (left) and Puts (right) for selected expiry.")

        calls_display = _prepare_chain_table(calls, price, is_calls=True)
        puts_display = _prepare_chain_table(puts, price, is_calls=False)

        col_calls, col_puts = st.columns(2)

        with col_calls:
            st.markdown(f"**CALLS** — {len(calls_display)} strikes")
            if not calls_display.empty:
                def _style_calls(row):
                    styles = [""] * len(row)
                    if "ITM" in row.index and row["ITM"]:
                        styles = [f"background-color: rgba(243,167,18,0.12)"] * len(row)
                    return styles
                st.dataframe(
                    calls_display.style.apply(_style_calls, axis=1),
                    use_container_width=True,
                    height=min(600, max(200, 35 * len(calls_display) + 48)),
                    hide_index=True,
                )
            else:
                st.info("No call data.")

        with col_puts:
            st.markdown(f"**PUTS** — {len(puts_display)} strikes")
            if not puts_display.empty:
                def _style_puts(row):
                    styles = [""] * len(row)
                    if "ITM" in row.index and row["ITM"]:
                        styles = [f"background-color: rgba(243,167,18,0.12)"] * len(row)
                    return styles
                st.dataframe(
                    puts_display.style.apply(_style_puts, axis=1),
                    use_container_width=True,
                    height=min(600, max(200, 35 * len(puts_display) + 48)),
                    hide_index=True,
                )
            else:
                st.info("No put data.")

        st.markdown("")

        # ── Charts ────────────────────────────────────────────────────────────────
        tab_oi, tab_iv = st.tabs(["Open Interest", "IV Smile"])

        with tab_oi:
            st.plotly_chart(_oi_chart(calls, puts, price), use_container_width=True, key="opt_oi_chart")

        with tab_iv:
            st.plotly_chart(_iv_smile_chart(calls, puts, price), use_container_width=True, key="opt_iv_smile")

    _live()
