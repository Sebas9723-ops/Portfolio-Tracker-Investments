import uuid
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import (
    append_paper_trade_to_sheets,
    get_manage_password,
    info_metric,
    info_section,
    load_paper_capital_from_sheets,
    load_paper_trades_from_sheets,
    render_page_title,
    reset_paper_trades_to_sheets,
    save_paper_capital_to_sheets,
)


# ── Price helpers ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _fetch_current_prices(tickers: tuple) -> dict:
    import yfinance as yf
    prices = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).fast_info
            p = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
            if p and p > 0:
                prices[t] = float(p)
        except Exception:
            pass
    return prices


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_price_history(tickers: tuple, start: str) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    import yfinance as yf
    all_t = list(tickers) + (["VOO"] if "VOO" not in tickers else [])
    try:
        df = yf.download(all_t, start=start, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df = df["Close"]
        elif len(all_t) == 1:
            df = df[["Close"]].rename(columns={"Close": all_t[0]})
        return df.ffill()
    except Exception:
        return pd.DataFrame()


# ── Position computation ──────────────────────────────────────────────────────

def _build_positions(trades_df: pd.DataFrame, starting_capital: float) -> tuple[dict, float]:
    """Replay trade log → current positions dict and remaining cash."""
    cash = float(starting_capital)
    positions: dict = {}  # ticker → {shares, avg_cost, total_cost}

    for _, row in trades_df.sort_values("timestamp").iterrows():
        ticker = str(row["ticker"]).strip().upper()
        shares = float(row["shares"])
        price = float(row["price"])
        fees = float(row.get("fees", 0.0))

        if row["action"] == "BUY":
            cost = shares * price + fees
            if ticker not in positions:
                positions[ticker] = {"shares": 0.0, "total_cost": 0.0}
            positions[ticker]["shares"] += shares
            positions[ticker]["total_cost"] += cost
            if positions[ticker]["shares"] > 0:
                positions[ticker]["avg_cost"] = (
                    positions[ticker]["total_cost"] / positions[ticker]["shares"]
                )
            cash -= cost

        elif row["action"] == "SELL":
            if ticker in positions and positions[ticker]["shares"] >= shares - 1e-9:
                proceeds = shares * price - fees
                positions[ticker]["shares"] -= shares
                # Reduce total_cost proportionally
                if positions[ticker]["shares"] <= 1e-9:
                    del positions[ticker]
                else:
                    positions[ticker]["total_cost"] = (
                        positions[ticker]["avg_cost"] * positions[ticker]["shares"]
                    )
                cash += proceeds

    return positions, cash


def _compute_equity_curve(
    trades_df: pd.DataFrame, starting_capital: float
) -> pd.Series:
    """
    Build a daily equity curve from the paper trade log.
    Uses historical closing prices from yfinance.

    Vectorized: builds shares-held-per-day matrix from trade deltas,
    then multiplies by daily prices.
    """
    if trades_df.empty:
        return pd.Series(dtype=float)

    all_tickers = tuple(sorted(trades_df["ticker"].unique()))
    first_date = trades_df["timestamp"].min()
    start_str = first_date.strftime("%Y-%m-%d") if not pd.isna(first_date) else "2020-01-01"

    price_hist = _fetch_price_history(all_tickers, start_str)
    if price_hist.empty:
        return pd.Series(dtype=float)

    dates = price_hist.index.normalize().unique().sort_values()

    # Build daily share deltas per ticker
    trades_copy = trades_df.copy()
    trades_copy["date_only"] = trades_copy["timestamp"].dt.normalize()
    trades_copy["signed_shares"] = trades_copy.apply(
        lambda r: float(r["shares"]) if r["action"] == "BUY" else -float(r["shares"]),
        axis=1,
    )
    trades_copy["cash_delta"] = trades_copy.apply(
        lambda r: -(float(r["shares"]) * float(r["price"]) + float(r["fees"]))
        if r["action"] == "BUY"
        else float(r["shares"]) * float(r["price"]) - float(r["fees"]),
        axis=1,
    )

    # Shares matrix: index=dates, columns=tickers
    shares_matrix = pd.DataFrame(0.0, index=dates, columns=list(all_tickers))
    cash_series = pd.Series(0.0, index=dates)

    for _, row in trades_copy.iterrows():
        d = row["date_only"]
        t = row["ticker"]
        if d in shares_matrix.index and t in shares_matrix.columns:
            shares_matrix.loc[d, t] += row["signed_shares"]
            cash_series.loc[d] += row["cash_delta"]

    # Cumulative shares and cash across time
    cum_shares = shares_matrix.cumsum()
    cum_cash = starting_capital + cash_series.cumsum()

    # Align price history to our dates
    price_aligned = price_hist.reindex(dates, method="ffill").reindex(columns=list(all_tickers))

    # Holdings value = element-wise shares × price
    holdings_value = (cum_shares * price_aligned).sum(axis=1)
    equity = cum_cash + holdings_value

    return equity


# ── Charts ────────────────────────────────────────────────────────────────────

def _build_equity_chart(
    paper_equity: pd.Series,
    starting_capital: float,
    price_hist: pd.DataFrame,
    first_trade_date,
) -> go.Figure:
    fig = go.Figure()

    fig.add_scatter(
        x=paper_equity.index, y=paper_equity,
        mode="lines", name="Paper Portfolio",
        line=dict(color="#f3a712", width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra>Paper Portfolio</extra>",
    )

    # VOO baseline (normalized to starting_capital)
    if "VOO" in price_hist.columns and first_trade_date is not None:
        voo = price_hist.loc[price_hist.index >= first_trade_date, "VOO"].dropna()
        if not voo.empty:
            voo_norm = voo / voo.iloc[0] * starting_capital
            fig.add_scatter(
                x=voo_norm.index, y=voo_norm,
                mode="lines", name="VOO",
                line=dict(color="#00c8ff", width=1.5, dash="dot"),
                hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra>VOO</extra>",
            )

    fig.update_layout(
        paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"), height=380,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Date", yaxis_title="Portfolio Value ($)",
        yaxis=dict(tickprefix="$", tickformat=",.0f"),
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


# ── Page renderer ─────────────────────────────────────────────────────────────

def render_paper_trading_page(ctx):
    render_page_title("Paper Trading")

    if ctx.get("app_scope") != "private" or not ctx.get("authenticated"):
        st.warning("Paper Trading is only available in Private mode.")
        return

    # ── Load data ──────────────────────────────────────────────────────────────
    starting_capital = load_paper_capital_from_sheets()
    trades_df = load_paper_trades_from_sheets()

    # ── First-time setup ───────────────────────────────────────────────────────
    if starting_capital <= 0:
        st.info("Set your virtual starting capital to begin paper trading.")
        with st.form("pt_setup_form"):
            cap = st.number_input(
                "Starting capital ($)", min_value=1000.0, value=100_000.0, step=1000.0,
                format="%.2f", key="pt_setup_capital",
            )
            auth = st.text_input("Authorization password", type="password", key="pt_setup_auth")
            if st.form_submit_button("Initialize Paper Portfolio", type="primary"):
                if auth != get_manage_password():
                    st.error("Incorrect password.")
                else:
                    save_paper_capital_to_sheets(cap)
                    st.cache_data.clear()
                    st.rerun()
        return

    # ── Compute current state ──────────────────────────────────────────────────
    positions, cash = _build_positions(trades_df, starting_capital)
    all_tickers_held = tuple(sorted(positions.keys()))

    current_prices = _fetch_current_prices(all_tickers_held) if all_tickers_held else {}

    holdings_value = sum(
        meta["shares"] * current_prices.get(t, meta.get("avg_cost", 0.0))
        for t, meta in positions.items()
    )
    total_value = holdings_value + cash
    total_pnl = total_value - starting_capital
    total_pnl_pct = total_pnl / starting_capital * 100 if starting_capital > 0 else 0.0

    # ── Summary metrics ────────────────────────────────────────────────────────
    info_section("Virtual Portfolio", "Paper trading simulation — no real money at risk.")

    c1, c2, c3, c4, c5 = st.columns(5)
    info_metric(c1, "Starting Capital", f"${starting_capital:,.0f}", "Initial virtual capital")
    info_metric(c2, "Current Value", f"${total_value:,.2f}", "Holdings + cash")
    info_metric(c3, "Total P&L", f"${total_pnl:+,.2f}", f"{total_pnl_pct:+.2f}%")
    info_metric(c4, "Cash Available", f"${cash:,.2f}", "Uninvested cash")
    info_metric(c5, "Open Positions", str(len(positions)), "Number of tickers held")

    # ── Positions table ────────────────────────────────────────────────────────
    if positions:
        info_section("Open Positions", "Current mark-to-market valuation of virtual holdings.")
        pos_rows = []
        for ticker, meta in sorted(positions.items()):
            cur_price = current_prices.get(ticker, meta.get("avg_cost", 0.0))
            shares = meta["shares"]
            avg_cost = meta.get("avg_cost", 0.0)
            market_val = shares * cur_price
            unreal_pnl = shares * (cur_price - avg_cost)
            unreal_pct = (cur_price / avg_cost - 1) * 100 if avg_cost > 0 else 0.0
            pos_rows.append({
                "Ticker": ticker,
                "Shares": round(shares, 4),
                "Avg Cost": round(avg_cost, 4),
                "Current Price": round(cur_price, 4),
                "Market Value": round(market_val, 2),
                "Unrealized P&L": round(unreal_pnl, 2),
                "Unrealized P&L %": round(unreal_pct, 2),
            })
        st.dataframe(
            pd.DataFrame(pos_rows),
            use_container_width=True,
            height=240,
            column_config={
                "Unrealized P&L %": st.column_config.NumberColumn("Unrealized P&L %", format="%.2f%%"),
            },
        )
    else:
        st.info("No open positions. Enter your first trade below.")

    # ── Equity curve ──────────────────────────────────────────────────────────
    if not trades_df.empty:
        info_section("Equity Curve", "Paper portfolio value over time vs VOO.")
        with st.spinner("Building equity curve..."):
            first_trade = trades_df["timestamp"].min()
            all_tickers_traded = tuple(sorted(trades_df["ticker"].unique()))
            start_str = first_trade.strftime("%Y-%m-%d") if not pd.isna(first_trade) else "2020-01-01"
            price_hist = _fetch_price_history(all_tickers_traded, start_str)
            equity_curve = _compute_equity_curve(trades_df, starting_capital)

        if not equity_curve.empty:
            fig = _build_equity_chart(equity_curve, starting_capital, price_hist, first_trade)
            st.plotly_chart(fig, use_container_width=True, key="pt_equity_chart")

    # ── New trade form ─────────────────────────────────────────────────────────
    info_section("New Trade", "Log a paper trade. Requires authorization password.")

    # Import from ML signals if available
    ml_signals = st.session_state.get("ml_signals", {})
    ml_tickers = [t for t, s in ml_signals.items() if s.get("signal") in ("BULLISH", "BEARISH")]

    with st.form("pt_trade_form", clear_on_submit=True):
        col_ticker, col_action, col_shares, col_price = st.columns([2, 1, 1, 1])

        with col_ticker:
            # Allow importing from ML signals
            use_ml = ml_tickers and st.checkbox(
                "Import from ML Signal", key="pt_use_ml", value=False,
            )
            if use_ml:
                ml_pick = st.selectbox("ML signal ticker", ml_tickers, key="pt_ml_pick")
                ticker_input = ml_pick
                suggested_action = ml_signals[ml_pick]["signal"]
                suggested_action = "BUY" if suggested_action == "BULLISH" else "SELL"
            else:
                ticker_input = st.text_input(
                    "Ticker", placeholder="e.g. AAPL", key="pt_ticker",
                ).upper().strip()
                suggested_action = "BUY"

        with col_action:
            action = st.selectbox(
                "Action",
                ["BUY", "SELL"],
                index=0 if suggested_action == "BUY" else 1,
                key="pt_action",
            )

        with col_shares:
            shares_input = st.number_input(
                "Shares", min_value=0.0001, value=1.0, step=0.1,
                format="%.4f", key="pt_shares",
            )

        with col_price:
            # Show live price as reference
            live_ref = current_prices.get(ticker_input, 0.0) if ticker_input else 0.0
            price_input = st.number_input(
                f"Price {'(live: ' + str(round(live_ref, 2)) + ')' if live_ref > 0 else ''}",
                min_value=0.0001, value=max(live_ref, 1.0), step=0.01,
                format="%.4f", key="pt_price",
            )

        col_fees, col_notes, col_source = st.columns([1, 3, 1])
        fees_input = col_fees.number_input("Fees ($)", min_value=0.0, value=0.0, key="pt_fees")
        notes_input = col_notes.text_input("Notes", key="pt_notes")
        source_label = "ML_SIGNAL" if (use_ml if ml_tickers else False) else "MANUAL"

        auth_input = st.text_input("Authorization password", type="password", key="pt_auth")
        submitted = st.form_submit_button("Log Trade", type="primary", use_container_width=True)

    if submitted:
        if auth_input != get_manage_password():
            st.error("Incorrect authorization password.")
        elif not ticker_input:
            st.error("Ticker is required.")
        elif shares_input <= 0:
            st.error("Shares must be greater than 0.")
        elif price_input <= 0:
            st.error("Price must be greater than 0.")
        else:
            # Guard: selling more shares than held
            if action == "SELL":
                held = positions.get(ticker_input, {}).get("shares", 0.0)
                if shares_input > held + 1e-9:
                    st.error(
                        f"Cannot sell {shares_input:.4f} shares of {ticker_input} — "
                        f"only {held:.4f} held."
                    )
                    st.stop()

            # Guard: insufficient cash for buy
            if action == "BUY":
                cost = shares_input * price_input + fees_input
                if cost > cash + 1.0:
                    st.error(
                        f"Insufficient cash. Trade costs ${cost:,.2f} but only ${cash:,.2f} available."
                    )
                    st.stop()

            trade = {
                "id": str(uuid.uuid4()),
                "timestamp": datetime.now().isoformat(),
                "ticker": ticker_input,
                "action": action,
                "shares": float(shares_input),
                "price": float(price_input),
                "fees": float(fees_input),
                "notes": notes_input.strip(),
                "source": source_label,
            }
            try:
                append_paper_trade_to_sheets(trade)
                st.cache_data.clear()
                st.success(
                    f"Trade logged: {action} {shares_input:.4f} {ticker_input} @ ${price_input:.4f}"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Could not save trade: {e}")

    # ── Trade log ─────────────────────────────────────────────────────────────
    info_section("Trade Log", "Complete history of all paper trades.")
    if trades_df.empty:
        st.info("No trades logged yet.")
    else:
        display_trades = trades_df.copy()
        display_trades["timestamp"] = display_trades["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
        st.dataframe(
            display_trades[["timestamp", "ticker", "action", "shares", "price", "fees", "notes", "source"]],
            use_container_width=True,
            height=360,
        )
        csv = trades_df.to_csv(index=False)
        st.download_button(
            "Download Trade Log (CSV)",
            data=csv,
            file_name="paper_trades.csv",
            mime="text/csv",
        )

    # ── Settings ──────────────────────────────────────────────────────────────
    info_section("Portfolio Settings", "Adjust starting capital or reset the virtual portfolio.")

    with st.expander("Settings (password required)"):
        with st.form("pt_settings_form"):
            new_capital = st.number_input(
                "New starting capital ($)", min_value=1000.0,
                value=float(starting_capital), step=1000.0,
                format="%.2f", key="pt_new_capital",
            )
            reset_trades = st.checkbox(
                "Also clear all trade history (cannot be undone)", key="pt_reset_trades",
            )
            settings_auth = st.text_input(
                "Authorization password", type="password", key="pt_settings_auth",
            )
            if st.form_submit_button("Save Settings", use_container_width=True):
                if settings_auth != get_manage_password():
                    st.error("Incorrect authorization password.")
                else:
                    save_paper_capital_to_sheets(new_capital)
                    if reset_trades:
                        reset_paper_trades_to_sheets()
                    st.cache_data.clear()
                    st.success("Settings updated.")
                    st.rerun()
