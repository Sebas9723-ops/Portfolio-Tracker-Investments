from datetime import date

import pandas as pd
import streamlit as st

from app_core import (
    SUPPORTED_BASE_CCY,
    append_transaction_to_sheets,
    get_manage_password,
    info_metric,
    info_section,
    render_page_title,
    save_cash_balances_to_sheets,
    save_private_positions_to_sheets,
)
from pages_app.portfolio_history import save_portfolio_snapshot


def _render_control_buttons(ctx):
    c1, c2, c3, c4 = st.columns(4)

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

    if c4.button("Save Portfolio Snapshot", use_container_width=True):
        try:
            save_portfolio_snapshot(ctx, notes="Manual Private Manager snapshot")
            st.cache_data.clear()
            st.session_state["pm_save_banner"] = "Portfolio snapshot saved successfully."
            st.rerun()
        except Exception as e:
            st.error(f"Could not save portfolio snapshot: {e}")


def _build_current_positions_map(ctx):
    positions = {}
    for _, row in ctx["df"].iterrows():
        positions[str(row["Ticker"])] = {
            "name": str(row["Name"]),
            "shares": float(row["Shares"]),
            "native_price": float(row["Native Price"]),
            "base_price": float(row["Price"]),
            "value": float(row["Value"]),
            "weight_pct": float(row["Weight %"]),
        }
    return positions


def _build_audit_trail(ctx, limit=20):
    tx_df = ctx.get("transactions_df", pd.DataFrame()).copy()
    if tx_df.empty:
        return pd.DataFrame()

    work = tx_df.copy()
    work["notes"] = work["notes"].fillna("").astype(str)
    work = work[work["notes"].str.contains("Private Manager share adjustment", case=False, na=False)].copy()

    if work.empty:
        return pd.DataFrame()

    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["shares"] = pd.to_numeric(work["shares"], errors="coerce").fillna(0.0)
    work["price"] = pd.to_numeric(work["price"], errors="coerce").fillna(0.0)
    work["fees"] = pd.to_numeric(work["fees"], errors="coerce").fillna(0.0)
    work["gross_value"] = work["shares"] * work["price"]

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

    return display[["Date", "Ticker", "Type", "Shares", "Price", "Gross Value", "Fees", "Notes"]].head(limit)


def render_private_manager_page(ctx):
    render_page_title("Private Manager")

    if ctx["mode"] != "Private" or not ctx["authenticated"]:
        st.warning("Private Manager is only available in Private mode.")
        return

    pending_snapshot = st.session_state.pop("pm_trigger_snapshot", False)
    pending_note = st.session_state.pop("pm_trigger_snapshot_note", "")

    if pending_snapshot:
        try:
            save_portfolio_snapshot(ctx, notes=pending_note or "Auto snapshot from Private Manager")
            st.cache_data.clear()
            st.session_state["pm_save_banner"] = "Current shares updated, transaction history saved, and snapshot stored."
        except Exception as e:
            st.session_state["pm_save_banner"] = f"Current shares updated, but snapshot could not be stored: {e}"

    _render_control_buttons(ctx)

    banner = st.session_state.pop("pm_save_banner", None)
    if banner:
        st.success(banner)

    info_section(
        "Current Shares Control",
        "Current shares are controlled only from this page. Every change requires authorization and writes a historical BUY or SELL record into Transactions.",
    )

    current_positions = _build_current_positions_map(ctx)

    snapshot_df = ctx["df"][
        ["Ticker", "Name", "Shares", "Native Price", "Price", "Value", "Weight %"]
    ].copy()
    st.dataframe(snapshot_df, use_container_width=True, height=260)

    with st.form("private_manager_form"):
        edited_positions = {}
        preview_rows = []

        for ticker in sorted(current_positions.keys()):
            meta = current_positions[ticker]

            c1, c2 = st.columns([2, 1])

            with c1:
                st.markdown(f"**{ticker}** — {meta['name']}")

            with c2:
                new_shares = st.number_input(
                    f"{ticker} shares",
                    min_value=0.0,
                    value=float(meta["shares"]),
                    step=0.0001,
                    format="%.4f",
                    key=f"pm_shares_{ticker}",
                )

            edited_positions[ticker] = {
                "name": meta["name"],
                "shares": float(new_shares),
            }

            delta = float(new_shares) - float(meta["shares"])
            if abs(delta) > 1e-12:
                action = "BUY" if delta > 0 else "SELL"
                preview_rows.append(
                    {
                        "Ticker": ticker,
                        "Name": meta["name"],
                        "Current Shares": round(float(meta["shares"]), 4),
                        "New Shares": round(float(new_shares), 4),
                        "Delta Shares": round(abs(delta), 4),
                        "Action": action,
                        "Reference Native Price": round(float(meta["native_price"]), 2),
                    }
                )

        info_section(
            "Pending Transaction History",
            "Preview of the BUY or SELL records that will be written into the read-only Transactions ledger.",
        )

        if preview_rows:
            st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, height=240)
        else:
            st.info("No share changes detected.")

        auth_password = st.text_input("Authorization Password", type="password")
        submitted = st.form_submit_button("Save Current Shares", use_container_width=True)

    if submitted:
        if auth_password != get_manage_password():
            st.error("Incorrect authorization password.")
            return

        tx_rows = []
        for ticker, meta in edited_positions.items():
            current_meta = current_positions[ticker]
            old_shares = float(current_meta["shares"])
            new_shares = float(meta["shares"])
            delta = new_shares - old_shares

            if abs(delta) <= 1e-12:
                continue

            tx_type = "BUY" if delta > 0 else "SELL"
            tx_rows.append(
                {
                    "date": str(date.today()),
                    "ticker": ticker,
                    "type": tx_type,
                    "shares": abs(delta),
                    "price": float(current_meta["native_price"]),
                    "fees": 0.0,
                    "notes": f"Private Manager share adjustment: {old_shares:.4f} -> {new_shares:.4f}",
                }
            )

        save_payload = {
            ticker: {
                "name": meta["name"],
                "shares": float(meta["shares"]),
            }
            for ticker, meta in edited_positions.items()
        }

        try:
            save_private_positions_to_sheets(save_payload)

            for tx in tx_rows:
                append_transaction_to_sheets(tx)

            st.cache_data.clear()
            st.session_state["pm_trigger_snapshot"] = True
            st.session_state["pm_trigger_snapshot_note"] = "Auto snapshot after Private Manager share update"
            st.rerun()

        except Exception as e:
            st.error(f"Could not save current shares: {e}")

    total_positions = len(current_positions)
    invested_assets = float(ctx["holdings_value"])
    total_portfolio = float(ctx["total_portfolio_value"])

    info_section(
        "Private Workflow",
        "Transactions are a read-only ledger. Private Manager is the operational control layer for current shares, each change creates a historical transaction record automatically, and phase 5A stores a historical portfolio snapshot.",
    )

    c1, c2, c3 = st.columns(3)
    info_metric(c1, "Managed Positions", str(total_positions), "Number of positions currently controlled from Private Manager.")
    info_metric(c2, "Invested Assets", f"{ctx['base_currency']} {invested_assets:,.2f}", "Current market value of invested assets.")
    info_metric(c3, "Total Portfolio", f"{ctx['base_currency']} {total_portfolio:,.2f}", "Invested assets plus cash.")

    audit_df = _build_audit_trail(ctx, limit=20)

    info_section(
        "Audit Trail",
        "Visual history of changes saved from Private Manager.",
    )
    if audit_df.empty:
        st.info("No Private Manager audit entries found.")
    else:
        st.dataframe(audit_df, use_container_width=True, height=320)

    info_section(
        "Cash Balances",
        "Set the total cash balance for a currency. Requires authorization.",
    )

    cash_df = ctx.get("cash_balances_df", pd.DataFrame()).copy()
    if not cash_df.empty:
        display_cash = cash_df.copy()
        display_cash.columns = ["Currency", "Amount"]
        display_cash["Amount"] = pd.to_numeric(display_cash["Amount"], errors="coerce").fillna(0.0)
        st.dataframe(display_cash, use_container_width=True, height=220)
    else:
        st.info("No cash balances on record.")

    with st.form("cash_balances_form"):
        cc1, cc2 = st.columns(2)
        with cc1:
            cash_currency = st.selectbox("Currency", SUPPORTED_BASE_CCY, key="pm_cash_currency")
        with cc2:
            cash_amount = st.number_input(
                "New Balance",
                min_value=0.0,
                value=0.0,
                step=10.0,
                format="%.2f",
                key="pm_cash_amount",
            )

        cash_auth = st.text_input("Authorization Password", type="password", key="pm_cash_auth")
        cash_submitted = st.form_submit_button("Save Cash Balance", use_container_width=True)

    if cash_submitted:
        if cash_auth != get_manage_password():
            st.error("Incorrect authorization password.")
        else:
            try:
                updated_cash = cash_df.copy()
                currency_up = str(cash_currency).upper().strip()

                if not updated_cash.empty and currency_up in updated_cash["currency"].values:
                    updated_cash.loc[updated_cash["currency"] == currency_up, "amount"] = float(cash_amount)
                else:
                    updated_cash = pd.concat(
                        [updated_cash, pd.DataFrame({"currency": [currency_up], "amount": [float(cash_amount)]})],
                        ignore_index=True,
                    )

                save_cash_balances_to_sheets(updated_cash)
                st.cache_data.clear()
                st.success(f"Cash balance updated: {currency_up} {cash_amount:,.2f}")
                st.rerun()
            except Exception as e:
                st.error(f"Could not save cash balance: {e}")