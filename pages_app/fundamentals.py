import datetime
"""
Fundamentals page — financial statements, valuation multiples, and peer comparison.
Uses get_income_stmt() / get_balance_sheet() / get_cashflow() for statements (yfinance
newer API), with .financials / .balance_sheet / .cashflow as fallbacks.
Uses get_info() as primary source for valuation metrics, with .info as fallback.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import info_section, render_page_title
from utils_aggrid import show_aggrid

_BLOOMBERG_BG = "#0b0f14"
_GOLD = "#f3a712"
_GREEN = "#4dff4d"
_RED = "#ff4d4d"


# ── Data fetching ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_fast_info(ticker: str) -> dict:
    import yfinance as yf
    out = {}
    try:
        fi = yf.Ticker(ticker).fast_info
        for attr in ["last_price", "market_cap", "shares", "currency",
                     "year_high", "year_low", "fifty_day_average",
                     "two_hundred_day_average", "company_name"]:
            try:
                out[attr] = getattr(fi, attr, None)
            except Exception:
                out[attr] = None
    except Exception:
        pass
    # Supplement with get_info() for fields not in fast_info (company name, sector, industry)
    try:
        info = yf.Ticker(ticker).get_info() or {}
        out['company_name'] = info.get('longName') or info.get('shortName') or out.get('company_name') or ticker
        out['sector'] = info.get('sector')
        out['industry'] = info.get('industry')
    except Exception:
        pass
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_financials(ticker: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Returns (income_stmt, balance_sheet, cashflow). Uses newer get_* API with fallback."""
    import yfinance as yf
    t = yf.Ticker(ticker)

    def _get(new_method, old_attr):
        try:
            df = getattr(t, new_method)()
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
        try:
            df = getattr(t, old_attr)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
        return pd.DataFrame()

    inc = _get("get_income_stmt", "financials")
    bal = _get("get_balance_sheet", "balance_sheet")
    cf  = _get("get_cashflow", "cashflow")
    return inc, bal, cf


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_valuation_metrics(ticker: str) -> dict:
    """Uses get_info() (newer API) with .info fallback."""
    import yfinance as yf
    metrics = {
        "trailingPE": None, "forwardPE": None, "pegRatio": None,
        "priceToBook": None, "priceToSalesTrailing12Months": None, "enterpriseToEbitda": None,
        "dividendYield": None, "trailingEps": None, "forwardEps": None,
        "beta": None,
    }
    t = yf.Ticker(ticker)
    info = {}
    for method in ("get_info", "info"):
        try:
            raw = getattr(t, method)() if method == "get_info" else getattr(t, method)
            if raw and len(raw) > 5:
                info = raw
                break
        except Exception:
            continue
    for k in metrics:
        v = info.get(k)
        if v is not None:
            try:
                metrics[k] = float(v)
            except Exception:
                pass
    return metrics


# ── Formatting ────────────────────────────────────────────────────────────────

def _fmt_large(v) -> str:
    try:
        v = float(v)
        if pd.isna(v):
            return "—"
        if abs(v) >= 1e12: return f"{v/1e12:.2f}T"
        if abs(v) >= 1e9:  return f"{v/1e9:.2f}B"
        if abs(v) >= 1e6:  return f"{v/1e6:.2f}M"
        if abs(v) >= 1e3:  return f"{v/1e3:.2f}K"
        return f"{v:.2f}"
    except Exception:
        return "—"


def _fmt_ratio(v, decimals=2) -> str:
    try:
        f = float(v)
        if pd.isna(f):
            return "—"
        return f"{f:.{decimals}f}x"
    except Exception:
        return "—"


def _fmt_pct(v) -> str:
    try:
        f = float(v)
        if pd.isna(f):
            return "—"
        return f"{f*100:.2f}%"
    except Exception:
        return "—"


# ── Statement helpers ─────────────────────────────────────────────────────────

def _get_row(df: pd.DataFrame, keys: list[str]) -> pd.Series | None:
    """Try multiple row name variants, return first match."""
    if df is None or df.empty:
        return None
    for key in keys:
        for idx in df.index:
            if isinstance(idx, str) and key.lower() in idx.lower():
                return df.loc[idx]
    return None


def _last_value(df: pd.DataFrame, keys: list[str]) -> float | None:
    row = _get_row(df, keys)
    if row is None:
        return None
    valid = row.dropna()
    if valid.empty:
        return None
    try:
        return float(valid.iloc[0])
    except Exception:
        return None


# ── Bar chart for financial statements ───────────────────────────────────────

def _income_bar_chart(inc: pd.DataFrame) -> go.Figure | None:
    """Revenue and Net Income bar chart for last 4 periods."""
    rev_row = _get_row(inc, ["Total Revenue", "Revenue"])
    ni_row = _get_row(inc, ["Net Income"])
    if rev_row is None and ni_row is None:
        return None

    cols = list(inc.columns[:4]) if len(inc.columns) >= 4 else list(inc.columns)
    labels = [str(c)[:10] if hasattr(c, "__str__") else str(c) for c in cols]

    fig = go.Figure()
    if rev_row is not None:
        vals = [rev_row.get(c) for c in cols]
        vals_clean = [float(v)/1e9 if pd.notna(v) else 0.0 for v in vals]
        fig.add_trace(go.Bar(x=labels, y=vals_clean, name="Revenue (B)",
                             marker_color=_GOLD,
                             hovertemplate="%{x}<br>Revenue: $%{y:.2f}B<extra></extra>"))
    if ni_row is not None:
        vals = [ni_row.get(c) for c in cols]
        vals_clean = [float(v)/1e9 if pd.notna(v) else 0.0 for v in vals]
        colors = [_GREEN if v >= 0 else _RED for v in vals_clean]
        fig.add_trace(go.Bar(x=labels, y=vals_clean, name="Net Income (B)",
                             marker_color=colors,
                             hovertemplate="%{x}<br>Net Income: $%{y:.2f}B<extra></extra>"))

    fig.update_layout(
        barmode="group",
        paper_bgcolor=_BLOOMBERG_BG, plot_bgcolor=_BLOOMBERG_BG,
        font=dict(color="#e6e6e6", size=12),
        height=320,
        margin=dict(t=30, b=20, l=60, r=20),
        xaxis=dict(gridcolor="#1a1f2e"),
        yaxis=dict(gridcolor="#1a1f2e", title="USD Billions"),
        legend=dict(orientation="h", y=1.05, x=0.0),
        title=dict(text="Revenue & Net Income", font=dict(color=_GOLD, size=13)),
    )
    return fig


# ── Peer comparison ───────────────────────────────────────────────────────────

def _build_comparison_table(tickers: list[str]) -> pd.DataFrame:
    rows = []
    for t in tickers:
        fi = _fetch_fast_info(t)
        val = _fetch_valuation_metrics(t)
        rows.append({
            "Ticker": t,
            "Market Cap": _fmt_large(fi.get("market_cap")),
            "P/E (TTM)": _fmt_ratio(val.get("trailingPE")),
            "Forward P/E": _fmt_ratio(val.get("forwardPE")),
            "P/B": _fmt_ratio(val.get("priceToBook")),
            "P/S": _fmt_ratio(val.get("priceToSalesTrailing12Months")),
            "EV/EBITDA": _fmt_ratio(val.get("enterpriseToEbitda")),
            "Div Yield": _fmt_pct(val.get("dividendYield")),
            "Beta": _fmt_ratio(val.get("beta"), decimals=2),
        })
    return pd.DataFrame(rows)


# ── Main render ────────────────────────────────────────────────────────────────

def render_fundamentals_page(ctx):
    render_page_title("Fundamentals")

    @st.fragment(run_every=3600)
    def _live():
        st.caption(f"Last refreshed: {datetime.datetime.now().strftime('%H:%M:%S')}")

        # ── Ticker selection ──────────────────────────────────────────────────────
        portfolio_tickers = []
        try:
            df_port = ctx.get("df")
            if df_port is not None and "Ticker" in df_port.columns:
                portfolio_tickers = df_port["Ticker"].dropna().unique().tolist()
        except Exception:
            pass

        col_sel, col_custom = st.columns([2, 2])
        with col_sel:
            use_custom = st.checkbox("Custom ticker", value=False, key="fund_use_custom")
        with col_custom:
            if use_custom:
                ticker = st.text_input("Ticker", placeholder="e.g. AAPL", key="fund_custom",
                                       label_visibility="collapsed").upper().strip()
            else:
                ticker = st.selectbox("Select ticker", portfolio_tickers, key="fund_sel") if portfolio_tickers else ""

        if not ticker:
            st.info("Select or enter a ticker to load fundamentals.")
            return

        # ── Fetch data ────────────────────────────────────────────────────────────
        with st.spinner(f"Loading fundamentals for {ticker}..."):
            fi = _fetch_fast_info(ticker)
            val = _fetch_valuation_metrics(ticker)
            inc, bal, cf = _fetch_financials(ticker)

        name = fi.get("company_name") or ticker
        price = fi.get("last_price")
        ccy = fi.get("currency") or "USD"

        st.markdown(
            f"<h3 style='color:#e6e6e6;font-family:monospace;margin:0;'>"
            f"{ticker} <span style='color:#888;font-size:14px;font-weight:normal;'>{name}</span>"
            f"  <span style='color:{_GOLD};font-size:16px;'>"
            f"{ccy} {price:.2f}" if price else ""
            f"</span></h3>",
            unsafe_allow_html=True,
        )
        st.markdown("")

        # ── Section 1: Valuation ──────────────────────────────────────────────────
        info_section("Valuation Multiples", "Key price-based ratios.")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("P/E (TTM)", _fmt_ratio(val.get("trailingPE")))
        c2.metric("Forward P/E", _fmt_ratio(val.get("forwardPE")))
        c3.metric("PEG Ratio", _fmt_ratio(val.get("pegRatio")))
        c4.metric("P/B", _fmt_ratio(val.get("priceToBook")))
        c5.metric("P/S", _fmt_ratio(val.get("priceToSalesTrailing12Months")))
        c6.metric("EV/EBITDA", _fmt_ratio(val.get("enterpriseToEbitda")))

        col_div, col_eps, col_feps, col_beta, col_mktcap, _ = st.columns(6)
        col_div.metric("Div Yield", _fmt_pct(val.get("dividendYield")))
        col_eps.metric("EPS (TTM)", _fmt_ratio(val.get("trailingEps"), decimals=2))
        col_feps.metric("Forward EPS", _fmt_ratio(val.get("forwardEps"), decimals=2))
        col_beta.metric("Beta", _fmt_ratio(val.get("beta"), decimals=2))
        col_mktcap.metric("Market Cap", _fmt_large(fi.get("market_cap")))

        # ── Revenue/Net Income chart ───────────────────────────────────────────────
        if not inc.empty:
            chart = _income_bar_chart(inc)
            if chart:
                st.plotly_chart(chart, use_container_width=True, key=f"fund_income_{ticker}")

        # ── Tabs: IS / BS / CF ────────────────────────────────────────────────────
        tab_is, tab_bs, tab_cf = st.tabs(["Income Statement", "Balance Sheet", "Cash Flow"])

        with tab_is:
            info_section("Income Statement (TTM)", "Annual figures from yfinance.")
            if not inc.empty:
                rev = _last_value(inc, ["Total Revenue", "Revenue"])
                gp = _last_value(inc, ["Gross Profit"])
                oi = _last_value(inc, ["Operating Income", "Ebit"])
                ni = _last_value(inc, ["Net Income"])

                co1, co2, co3, co4 = st.columns(4)
                co1.metric("Revenue", _fmt_large(rev))
                co2.metric("Gross Profit", _fmt_large(gp))
                co3.metric("Operating Income", _fmt_large(oi))
                co4.metric("Net Income", _fmt_large(ni))

                st.markdown("")
                show_aggrid(
                    inc.apply(lambda r: r.map(_fmt_large), axis=1),
                    height=min(500, max(200, 35 * len(inc) + 48)),
                    key="aggrid_fundamentals_income",
                )
            else:
                st.info("Income statement data not available.")

        with tab_bs:
            info_section("Balance Sheet", "Most recent annual snapshot.")
            if not bal.empty:
                assets = _last_value(bal, ["Total Assets"])
                debt = _last_value(bal, ["Total Debt", "Long Term Debt"])
                cash = _last_value(bal, ["Cash And Cash Equivalents", "Cash"])
                equity = _last_value(bal, ["Stockholders Equity", "Total Equity"])

                b1, b2, b3, b4 = st.columns(4)
                b1.metric("Total Assets", _fmt_large(assets))
                b2.metric("Total Debt", _fmt_large(debt))
                b3.metric("Cash", _fmt_large(cash))
                b4.metric("Equity", _fmt_large(equity))

                st.markdown("")
                show_aggrid(
                    bal.apply(lambda r: r.map(_fmt_large), axis=1),
                    height=min(500, max(200, 35 * len(bal) + 48)),
                    key="aggrid_fundamentals_balance_sheet",
                )
            else:
                st.info("Balance sheet data not available.")

        with tab_cf:
            info_section("Cash Flow Statement", "Most recent annual.")
            if not cf.empty:
                op_cf = _last_value(cf, ["Operating Cash Flow", "Cash From Operations"])
                capex = _last_value(cf, ["Capital Expenditure", "Capital Expenditures"])
                fcf_val = None
                if op_cf is not None and capex is not None:
                    fcf_val = op_cf - abs(capex)

                f1, f2, f3 = st.columns(3)
                f1.metric("Operating CF", _fmt_large(op_cf))
                f2.metric("CapEx", _fmt_large(capex))
                f3.metric("Free Cash Flow", _fmt_large(fcf_val))

                st.markdown("")
                show_aggrid(
                    cf.apply(lambda r: r.map(_fmt_large), axis=1),
                    height=min(500, max(200, 35 * len(cf) + 48)),
                    key="aggrid_fundamentals_cashflow",
                )
            else:
                st.info("Cash flow data not available.")

        # ── Peer comparison ───────────────────────────────────────────────────────
        st.markdown("")
        info_section("Peer Comparison", "Compare valuation multiples side by side.")

        peer_input = st.text_input(
            "Add peer tickers (comma-separated)",
            placeholder="e.g. MSFT, GOOGL",
            key="fund_peers",
        )
        peer_tickers = [t.strip().upper() for t in peer_input.split(",") if t.strip()]
        all_compare = list(dict.fromkeys([ticker] + peer_tickers))

        if len(all_compare) > 1:
            with st.spinner("Loading peer data..."):
                comp_df = _build_comparison_table(all_compare)
            show_aggrid(comp_df, height=400, key="aggrid_fundamentals_peer_comparison")
        else:
            st.caption("Add peer tickers above to enable comparison.")

    _live()
