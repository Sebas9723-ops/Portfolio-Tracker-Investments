import pandas as pd
import streamlit as st

from app_core import (
    SUPPORTED_BASE_CCY,
    append_transaction_to_sheets,
    adjust_cash_balance,
    asset_currency,
    info_metric,
    info_section,
    load_cash_balances_from_sheets,
    render_page_title,
    save_cash_balances_to_sheets,
)


def render_transactions_page(ctx):
    render_page_title("Transactions")

    if ctx["mode"] != "Private" or not ctx["authenticated"]:
        st.info("This page is available only in Private mode.")
        return

    info_section(
        "Add Transaction",
        "Register a buy or sell operation. Share quantities in Private mode are derived from this transaction ledger."
    )

    current_tickers = sorted(
        set(ctx["portfolio_data"].keys()) |
        set(ctx["transactions_df"]["ticker"].tolist() if not ctx["transactions_df"].empty else [])
    )
    ticker_options = current_tickers + ["OTHER"]

    with st.form("add_transaction_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)

        with c1:
            tx_date = st.date_input("Date")
            ticker_choice = st.selectbox("Ticker", ticker_options)
            tx_type = st.selectbox("Type", ["BUY", "SELL"])

        with c2:
            shares = st.number_input("Shares", min_value=0.0, value=0.0, step=0.0001, format="%.4f")
            price = st.number_input("Price", min_value=0.0, value=0.0, step=0.01, format="%.4f")
            fees = st.number_input("Fees", min_value=0.0, value=0.0, step=0.01, format="%.4f")

        with c3:
            manual_ticker = st.text_input("Manual Ticker (only if OTHER)").strip().upper()
            notes = st.text_input("Notes").strip()
            update_cash = st.checkbox("Update cash balance automatically", value=True)

        ticker = manual_ticker if ticker_choice == "OTHER" else ticker_choice
        native_ccy = asset_currency(ticker) if ticker else "—"
        st.caption(f"Inferred native currency: {native_ccy}")

        submitted = st.form_submit_button("Add Transaction")

    if submitted:
        if not ticker:
            st.error("Please select a ticker or enter one manually.")
            return

        if shares <= 0 or price <= 0:
            st.error("Shares and price must be greater than zero.")
            return

        tx = {
            "date": tx_date.isoformat(),
            "ticker": ticker,
            "type": tx_type,
            "shares": float(shares),
            "price": float(price),
            "fees": float(fees),
            "notes": notes,
        }

        append_transaction_to_sheets(tx)

        if update_cash:
            gross_value = float(shares) * float(price)
            if tx_type == "BUY":
                delta = -(gross_value + float(fees))
            else:
                delta = gross_value - float(fees)
            adjust_cash_balance(native_ccy, delta)

        st.success("Transaction saved successfully.")
        st.rerun()

    info_section("Cash Balances", "Edit and save current cash balances by currency.")

    live_cash_df = load_cash_balances_from_sheets().copy()
    live_cash_df["currency"] = live_cash_df["currency"].astype(str).str.upper()

    cash_cols = st.columns(3)
    cash_values = {}

    for idx, ccy in enumerate(SUPPORTED_BASE_CCY):
        row = live_cash_df[live_cash_df["currency"] == ccy]
        amount = float(row["amount"].iloc[0]) if not row.empty else 0.0

        with cash_cols[idx % 3]:
            cash_values[ccy] = st.number_input(
                f"{ccy} Cash",
                value=float(amount),
                step=100.0,
                format="%.2f",
                key=f"cash_edit_{ccy}",
            )

    if st.button("Save Cash Balances"):
        save_df = pd.DataFrame(
            {
                "currency": list(cash_values.keys()),
                "amount": list(cash_values.values()),
            }
        )
        save_cash_balances_to_sheets(save_df)
        st.success("Cash balances saved.")
        st.rerun()

    t1, t2, t3 = st.columns(3)
    info_metric(
        t1,
        "Transactions",
        str(0 if ctx["transactions_df"].empty else len(ctx["transactions_df"])),
        "Number of recorded buy and sell transactions.",
    )
    info_metric(
        t2,
        "Tracked Tickers",
        str(len(set(ctx["transactions_df"]["ticker"].tolist())) if not ctx["transactions_df"].empty else 0),
        "Number of tickers present in the transaction ledger.",
    )
    info_metric(
        t3,
        "Cash Total",
        f"{ctx['base_currency']} {ctx['cash_total_value']:,.2f}",
        "Cash balances converted to the selected base currency.",
    )

    info_section("Transaction History", "Chronological list of all recorded transactions.")

    if ctx["transactions_df"].empty:
        st.info("No transactions recorded yet.")
    else:
        tx_display = ctx["transactions_df"].copy()
        tx_display["date"] = pd.to_datetime(tx_display["date"]).dt.date
        tx_display = tx_display.sort_values("date", ascending=False).reset_index(drop=True)
        tx_display.columns = ["Date", "Ticker", "Type", "Shares", "Price", "Fees", "Notes"]
        st.dataframe(tx_display, use_container_width=True, height=360)

    info_section("Tracked Positions", "Positions reconstructed from transactions and current market prices.")
    tracked_positions = ctx["display_df"][
        [
            "Ticker",
            "Name",
            "Source",
            "Shares",
            "Avg Cost",
            "Price",
            "Invested Capital",
            "Value",
            "Unrealized PnL",
            "Realized PnL",
        ]
    ].copy()
    st.dataframe(tracked_positions, use_container_width=True, height=320)