import pandas as pd
import streamlit as st

from app_core import (
    info_metric,
    info_section,
    render_page_title,
)


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

    st.dataframe(
        display[["Date", "Ticker", "Type", "Shares", "Price", "Gross Value", "Fees", "Notes"]],
        use_container_width=True,
        height=440,
    )