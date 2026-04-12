import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import (
    info_metric,
    info_section,
    render_page_title,
)
from utils_aggrid import show_aggrid


def _render_control_buttons(ctx):
    c1, c2, c3 = st.columns(3)

    if c1.button("Refresh Market Data", use_container_width=True):
        st.rerun()

    if c2.button("Recalculate Portfolio", use_container_width=True):
        st.rerun()

    if c3.button("Sync Private Data", use_container_width=True):
        if ctx["mode"] == "Private" and ctx["authenticated"]:
            st.cache_data.clear()
            st.rerun()
        else:
            st.info("Private sync is only available in Private mode.")


def render_transactions_page(ctx):
    render_page_title("Transactions")

    if ctx["mode"] != "Private" or not ctx["authenticated"]:
        st.warning("Transactions are only available in Private mode.")
        return

    _render_control_buttons(ctx)

    info_section(
        "Transactions Ledger",
        "This page is now read-only. New transaction history is automatically written when you modify current shares from Private Manager.",
    )

    tx_df = ctx.get("transactions_df", pd.DataFrame()).copy()

    if tx_df.empty:
        st.info("No transactions found.")
        return

    work = tx_df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["shares"] = pd.to_numeric(work["shares"], errors="coerce").fillna(0.0)
    work["price"] = pd.to_numeric(work["price"], errors="coerce").fillna(0.0)
    work["fees"] = pd.to_numeric(work["fees"], errors="coerce").fillna(0.0)
    work["gross_value"] = work["shares"] * work["price"]

    buy_value = float(work.loc[work["type"] == "BUY", "gross_value"].sum())
    sell_value = float(work.loc[work["type"] == "SELL", "gross_value"].sum())
    total_fees = float(work["fees"].sum())

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Transactions", str(len(work)), "Total number of stored transactions.")
    info_metric(c2, "Buy Value", f"{ctx['base_currency']} {buy_value:,.2f}", "Gross buy value stored in the ledger.")
    info_metric(c3, "Sell Value", f"{ctx['base_currency']} {sell_value:,.2f}", "Gross sell value stored in the ledger.")
    info_metric(c4, "Fees", f"{ctx['base_currency']} {total_fees:,.2f}", "Total recorded fees.")

    display = work.rename(
        columns={
            "date": "Date",
            "ticker": "Ticker",
            "type": "Type",
            "shares": "Shares",
            "price": "Price",
            "fees": "Fees",
            "notes": "Notes",
            "gross_value": "Gross Value",
        }
    ).copy()

    display["Date"] = pd.to_datetime(display["Date"], errors="coerce").dt.date
    display = display.sort_values("Date", ascending=False).reset_index(drop=True)

    show_aggrid(
        display[["Date", "Ticker", "Type", "Shares", "Price", "Gross Value", "Fees", "Notes"]],
        height=440,
        key="aggrid_transactions_ledger",
    )

    # ── DCA Tracker ───────────────────────────────────────────────────────────
    asset_hist = ctx.get("asset_hist_native", pd.DataFrame())
    # Show ALL portfolio tickers, not only those with transactions
    df_ctx = ctx.get("df", pd.DataFrame())
    portfolio_tickers = sorted(df_ctx["Ticker"].str.upper().tolist()) if not df_ctx.empty and "Ticker" in df_ctx.columns else []
    tx_tickers = sorted(tx_df["ticker"].str.upper().unique()) if not tx_df.empty else []
    # Union: portfolio tickers + any tx tickers, filtered to those in price history
    all_tickers = sorted(set(portfolio_tickers) | set(tx_tickers))
    tracked = [t for t in all_tickers if t in asset_hist.columns]

    if not tracked:
        return

    info_section(
        "DCA Tracker",
        "Average cost evolution versus market price per position. "
        "Green markers = buy entries. Blue dotted line = running avg cost. "
        "When the price line is above the avg cost line, the position is in profit.",
    )

    for ticker in tracked:
        ticker_tx = work[work["ticker"].str.upper() == ticker].sort_values("date")

        # Reconstruct running avg cost from transactions
        running_shares = 0.0
        running_cost   = 0.0
        avg_cost_pts: list[dict] = []

        for _, row in ticker_tx.iterrows():
            t = str(row["type"]).upper()
            if t == "BUY":
                running_shares += float(row["shares"])
                running_cost   += float(row["shares"]) * float(row["price"]) + float(row["fees"])
            elif t == "SELL" and running_shares > 0:
                avg_per = running_cost / running_shares
                running_cost   -= float(row["shares"]) * avg_per
                running_shares -= float(row["shares"])
                running_shares  = max(running_shares, 0.0)
                running_cost    = max(running_cost, 0.0)

            if running_shares > 1e-9:
                avg_cost_pts.append({"date": row["date"], "avg_cost": running_cost / running_shares})

        price_series = pd.to_numeric(asset_hist[ticker], errors="coerce").dropna()
        price_series.index = pd.to_datetime(price_series.index)
        if price_series.empty:
            continue

        if avg_cost_pts:
            first_tx_date = pd.to_datetime(avg_cost_pts[0]["date"])
            price_series  = price_series[price_series.index >= first_tx_date]
        if price_series.empty:
            continue

        avg_s = pd.Series(dtype=float)
        if avg_cost_pts:
            avg_s = (
                pd.DataFrame(avg_cost_pts)
                .set_index("date")["avg_cost"]
                .reindex(price_series.index)
                .ffill()
                .bfill()
            )

        current_price = float(price_series.iloc[-1])
        current_avg   = float(avg_s.iloc[-1]) if not avg_s.empty else None

        if current_avg:
            gain_pct = (current_price / current_avg - 1) * 100
            st.metric(
                label=ticker,
                value=f"{current_price:.4f}",
                delta=f"{gain_pct:+.2f}% vs avg cost {current_avg:.4f}",
                delta_color="normal" if gain_pct >= 0 else "inverse",
            )
        else:
            st.metric(label=ticker, value=f"{current_price:.4f}", delta="No transactions yet")

        buys = ticker_tx[ticker_tx["type"].str.upper() == "BUY"] if not ticker_tx.empty else pd.DataFrame()

        fig = go.Figure()
        fig.add_scatter(
            x=price_series.index, y=price_series.values,
            name="Market Price", mode="lines",
            line=dict(color="#f3a712", width=2),
            hovertemplate="%{x|%Y-%m-%d}<br>Price: %{y:.4f}<extra></extra>",
        )
        if not avg_s.empty:
            fig.add_scatter(
                x=avg_s.index, y=avg_s.values,
                name="Avg Cost (DCA)", mode="lines",
                line=dict(color="#4db8ff", width=2, dash="dot"),
                hovertemplate="%{x|%Y-%m-%d}<br>Avg Cost: %{y:.4f}<extra></extra>",
            )
        if not buys.empty:
            fig.add_scatter(
                x=pd.to_datetime(buys["date"]), y=buys["price"],
                name="Buy", mode="markers",
                marker=dict(color="#4dff4d", size=9, symbol="triangle-up"),
                hovertemplate="%{x|%Y-%m-%d}<br>Buy at: %{y:.4f}<extra></extra>",
            )
        fig.update_layout(
            paper_bgcolor="#0b0f14",
            plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"),
            height=300,
            margin=dict(t=30, b=20, l=20, r=20),
            xaxis_title="",
            yaxis_title="Price (native currency)",
            legend=dict(orientation="h", y=1.12, x=0.0),
            title=dict(text=ticker, font=dict(color="#f3a712", size=13)),
        )
        st.plotly_chart(fig, use_container_width=True, key=f"dca_{ticker}")