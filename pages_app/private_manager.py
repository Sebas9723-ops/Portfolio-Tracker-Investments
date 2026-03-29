from datetime import date

import pandas as pd
import streamlit as st

from app_core import (
    append_transaction_to_sheets,
    get_manage_password,
    info_metric,
    info_section,
    render_page_title,
    save_private_positions_to_sheets,
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

    _render_control_buttons(ctx)

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
            st.success("Current shares updated successfully and transaction history saved.")
            st.rerun()

        except Exception as e:
            st.error(f"Could not save current shares: {e}")

    total_positions = len(current_positions)
    invested_assets = float(ctx["holdings_value"])
    total_portfolio = float(ctx["total_portfolio_value"])

    info_section(
        "Private Workflow",
        "Transactions are a read-only ledger. Private Manager is the operational control layer for current shares, and each change creates a historical transaction record automatically.",
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