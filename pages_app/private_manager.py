from datetime import date

import pandas as pd
import streamlit as st

from utils_aggrid import show_aggrid

from app_core import (
    NON_PORTFOLIO_CASH_HEADERS,
    SUPPORTED_BASE_CCY,
    append_transaction_to_sheets,
    get_manage_password,
    info_metric,
    info_section,
    load_non_portfolio_cash_from_sheets,
    render_page_title,
    save_cash_balances_to_sheets,
    save_non_portfolio_cash_to_sheets,
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
    portfolio_data = ctx.get("portfolio_data", {})
    for _, row in ctx["df"].iterrows():
        ticker = str(row["Ticker"])
        # Only show avg_cost in the form if it was explicitly set by the user
        # (stored in portfolio_data), not the current market price fallback.
        explicit_avg_cost = portfolio_data.get(ticker, {}).get("avg_cost")
        avg_cost_native = float(explicit_avg_cost) if explicit_avg_cost and float(explicit_avg_cost) > 0 else 0.0
        positions[ticker] = {
            "name": str(row["Name"]),
            "shares": float(row["Shares"]),
            "native_price": float(row["Native Price"]),
            "avg_cost_native": avg_cost_native,
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
    show_aggrid(snapshot_df, height=260, key="aggrid_pm_snapshot")

    with st.form("private_manager_form"):
        edited_positions = {}
        preview_rows = []

        for ticker in sorted(current_positions.keys()):
            meta = current_positions[ticker]

            c1, c2, c3 = st.columns([2, 1, 1])

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

            with c3:
                new_avg_cost = st.number_input(
                    f"{ticker} avg cost (native)",
                    min_value=0.0,
                    value=float(meta["avg_cost_native"]) if float(meta["avg_cost_native"]) > 0 else 0.0,
                    step=0.01,
                    format="%.4f",
                    key=f"pm_avg_cost_{ticker}",
                    help="Average cost per share in the native currency of this ticker",
                )

            edited_positions[ticker] = {
                "name": meta["name"],
                "shares": float(new_shares),
                "avg_cost": float(new_avg_cost) if new_avg_cost > 0 else None,
            }

            delta = float(new_shares) - float(meta["shares"])
            avg_cost_changed = abs(float(new_avg_cost) - float(meta["avg_cost_native"])) > 1e-6
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
                        "Avg Cost (native)": round(float(new_avg_cost), 4) if new_avg_cost > 0 else "—",
                        "Reference Native Price": round(float(meta["native_price"]), 2),
                    }
                )
            elif avg_cost_changed and new_avg_cost > 0:
                preview_rows.append(
                    {
                        "Ticker": ticker,
                        "Name": meta["name"],
                        "Current Shares": round(float(meta["shares"]), 4),
                        "New Shares": round(float(meta["shares"]), 4),
                        "Delta Shares": 0.0,
                        "Action": "Avg Cost Update",
                        "Avg Cost (native)": round(float(new_avg_cost), 4),
                        "Reference Native Price": round(float(meta["native_price"]), 2),
                    }
                )

        info_section(
            "Pending Transaction History",
            "Preview of the BUY or SELL records that will be written into the read-only Transactions ledger.",
        )

        if preview_rows:
            show_aggrid(pd.DataFrame(preview_rows), height=240, key="aggrid_pm_preview")
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

        save_payload = {}
        for ticker, meta in edited_positions.items():
            entry = {"name": meta["name"], "shares": float(meta["shares"])}
            if meta.get("avg_cost") and float(meta["avg_cost"]) > 0:
                entry["avg_cost"] = float(meta["avg_cost"])
            save_payload[ticker] = entry

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
        show_aggrid(audit_df, height=320, key="aggrid_pm_audit")

    info_section(
        "Cash Balances",
        "Set the total cash balance for a currency. Requires authorization.",
    )

    cash_df = ctx.get("cash_balances_df", pd.DataFrame()).copy()
    cash_display_df = ctx.get("cash_display_df", pd.DataFrame()).copy()
    if not cash_display_df.empty:
        show_aggrid(cash_display_df, height=220, key="aggrid_pm_cash_display")
    elif not cash_df.empty:
        display_cash = cash_df[["currency", "amount"]].rename(
            columns={"currency": "Currency", "amount": "Amount"}
        )
        show_aggrid(display_cash, height=220, key="aggrid_pm_cash_raw")
    else:
        st.info("No cash balances on record.")

    with st.form("cash_balances_form"):
        cc1, cc2 = st.columns(2)
        with cc1:
            cash_currency = st.selectbox("Currency", SUPPORTED_BASE_CCY, key="pm_cash_currency")
        with cc2:
            cash_amount_raw = st.text_input(
                "New Balance (use . as decimal separator)",
                value="0.00",
                key="pm_cash_amount",
            )

        cash_auth = st.text_input("Authorization Password", type="password", key="pm_cash_auth")
        cash_submitted = st.form_submit_button("Save Cash Balance", use_container_width=True)

    if cash_submitted:
        try:
            cash_amount = float(str(cash_amount_raw).strip().replace(",", "."))
        except ValueError:
            st.error(f"Invalid amount: '{cash_amount_raw}'. Use a number with . as decimal separator (e.g. 2.58).")
            cash_amount = None

        if cash_amount is not None and cash_auth != get_manage_password():
            st.error("Incorrect authorization password.")
        elif cash_amount is not None:
            try:
                currency_up = str(cash_currency).upper().strip()
                updated_cash = cash_df.copy()

                if not updated_cash.empty and currency_up in updated_cash["currency"].values:
                    updated_cash.loc[updated_cash["currency"] == currency_up, "amount"] = cash_amount
                else:
                    updated_cash = pd.concat(
                        [updated_cash, pd.DataFrame({"currency": [currency_up], "amount": [cash_amount]})],
                        ignore_index=True,
                    )

                save_cash_balances_to_sheets(updated_cash)
                # Keep override alive for the whole browser session so every page reflects
                # the new value without depending on Sheets cache expiry.
                if "pm_cash_override" not in st.session_state:
                    st.session_state["pm_cash_override"] = {}
                st.session_state["pm_cash_override"][currency_up] = cash_amount
                st.session_state["pm_save_banner"] = f"Cash balance updated: {currency_up} {cash_amount:,.2f}"
                st.rerun()
            except Exception as e:
                st.error(f"Could not save cash balance: {e}")

    # ── Non-Portfolio Cash ────────────────────────────────────────────────────
    info_section(
        "Cash Non Portfolio",
        "External cash accounts (savings, checking, crypto wallets) not held within your "
        "investment portfolio. Included in Investments Net Worth on the Portfolio page.",
    )

    npc_df = ctx.get("non_portfolio_cash_df", pd.DataFrame(columns=NON_PORTFOLIO_CASH_HEADERS)).copy()
    investments_net_worth = float(ctx.get("investments_net_worth", float(ctx.get("total_portfolio_value", 0.0))))

    if not npc_df.empty:
        display_npc = npc_df[["label", "currency", "amount", "institution", "notes"]].rename(
            columns={"label": "Label", "currency": "Currency", "amount": "Amount",
                     "institution": "Institution", "notes": "Notes"}
        )
        show_aggrid(display_npc, height=200, key="aggrid_pm_npc")
    else:
        st.info("No non-portfolio cash entries recorded yet.")

    c_nw1, c_nw2, c_nw3 = st.columns(3)
    info_metric(c_nw1, "Portfolio Value", f"{ctx['base_currency']} {float(ctx['total_portfolio_value']):,.2f}", "Invested assets plus in-portfolio cash.")
    info_metric(c_nw2, "Non-Portfolio Cash", f"{ctx['base_currency']} {float(ctx.get('non_portfolio_cash_value', 0.0)):,.2f}", "External savings and cash accounts converted to base currency.")
    info_metric(c_nw3, "Investments Net Worth", f"{ctx['base_currency']} {investments_net_worth:,.2f}", "Total wealth: portfolio + external cash.")

    with st.form("non_portfolio_cash_form"):
        st.markdown("**Add / Update Entry**")
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            npc_label = st.text_input("Label (e.g. Bancolombia Savings)", key="npc_label", placeholder="Bancolombia Savings")
            npc_institution = st.text_input("Institution (optional)", key="npc_institution", placeholder="Bancolombia")
        with fc2:
            npc_currency = st.selectbox("Currency", SUPPORTED_BASE_CCY, key="npc_currency")
            npc_amount_raw = st.text_input("Amount", value="0.00", key="npc_amount")
        with fc3:
            npc_notes = st.text_input("Notes (optional)", key="npc_notes", placeholder="4% APY savings account")

        npc_auth = st.text_input("Authorization Password", type="password", key="npc_auth")
        npc_submitted = st.form_submit_button("Save Entry", use_container_width=True)

    if npc_submitted:
        if not npc_label.strip():
            st.error("Label is required.")
        else:
            try:
                npc_amount = float(str(npc_amount_raw).strip().replace(",", "."))
            except ValueError:
                st.error(f"Invalid amount: '{npc_amount_raw}'.")
                npc_amount = None

            if npc_amount is not None and npc_auth != get_manage_password():
                st.error("Incorrect authorization password.")
            elif npc_amount is not None:
                try:
                    updated_npc = npc_df.copy()
                    label_up = npc_label.strip()
                    ccy_up = str(npc_currency).upper().strip()
                    mask = updated_npc["label"] == label_up
                    new_row = {
                        "label": label_up, "currency": ccy_up,
                        "amount": npc_amount, "institution": npc_institution.strip(),
                        "notes": npc_notes.strip(),
                    }
                    if mask.any():
                        for col, val in new_row.items():
                            updated_npc.loc[mask, col] = val
                    else:
                        updated_npc = pd.concat(
                            [updated_npc, pd.DataFrame([new_row])], ignore_index=True
                        )
                    save_non_portfolio_cash_to_sheets(updated_npc)
                    st.session_state["pm_save_banner"] = f"Non-portfolio cash entry saved: {label_up} {ccy_up} {npc_amount:,.2f}"
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not save entry: {e}")

    # Delete entry
    if not npc_df.empty:
        with st.expander("Delete Entry", expanded=False):
            del_labels = npc_df["label"].tolist()
            del_label = st.selectbox("Select entry to delete", del_labels, key="npc_del_label")
            del_auth = st.text_input("Authorization Password", type="password", key="npc_del_auth")
            if st.button("Delete Entry", key="npc_del_btn", type="primary"):
                if del_auth != get_manage_password():
                    st.error("Incorrect authorization password.")
                else:
                    try:
                        remaining = npc_df[npc_df["label"] != del_label].reset_index(drop=True)
                        save_non_portfolio_cash_to_sheets(remaining)
                        st.session_state["pm_save_banner"] = f"Deleted entry: {del_label}"
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not delete entry: {e}")