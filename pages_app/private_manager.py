import pandas as pd
import streamlit as st
from datetime import date

from app_core import (
    append_transaction_to_sheets,
    info_section,
    render_page_title,
    save_private_positions_to_sheets,
)


def _get_manage_password() -> str:
    try:
        return str(st.secrets["auth"]["manage_password"])
    except Exception:
        return ""


def _safe_positive_reference_price(row) -> float:
    avg_cost = row["Avg Cost"] if "Avg Cost" in row.index else None
    price = row["Price"] if "Price" in row.index else None

    if pd.notna(avg_cost) and float(avg_cost) > 0:
        return float(avg_cost)

    if pd.notna(price) and float(price) > 0:
        return float(price)

    return 0.01


def render_private_manager_page(ctx):
    render_page_title("Private Manager")

    if ctx["mode"] != "Private" or not ctx["authenticated"]:
        st.info("This page is available only in Private mode.")
        return

    info_section(
        "Private Sync",
        "Edit shares directly here or save the current private snapshot. If transactions exist, saving changes here will also create adjustment transactions so current shares stay synchronized."
    )

    if ctx["positions_sheet_available"]:
        st.success("Google Sheets connection is available.")
    else:
        st.error(f"Google Sheets connection is not available. {ctx['positions_sheet_error']}")

    if ctx["has_transactions"]:
        st.info(
            "Transactions are active. Shares shown here are currently reconstructed from the transaction ledger. "
            "If you save edited shares below, the app will also create adjustment transactions so current shares update immediately."
        )

    base_df = ctx["df"].copy()

    display_cols = ["Ticker", "Name", "Shares", "Source"]
    safe_cols = [c for c in display_cols if c in base_df.columns]

    editable_df = base_df[safe_cols].copy()

    edited_df = st.data_editor(
        editable_df,
        use_container_width=True,
        height=320,
        num_rows="fixed",
        disabled=[c for c in editable_df.columns if c != "Shares"],
        key="private_manager_editor",
    )

    auth_password = st.text_input(
        "Authorization Password",
        type="password",
        key="private_manager_authorization_password",
    )

    if st.button("Save Shares To Private Positions Sheet", use_container_width=True):
        if auth_password != _get_manage_password():
            st.error("Invalid authorization password.")
            return

        if "Shares" not in edited_df.columns:
            st.error("Shares column is missing.")
            return

        edited_df["Shares"] = pd.to_numeric(edited_df["Shares"], errors="coerce")

        if edited_df["Shares"].isna().any():
            st.error("All shares values must be numeric.")
            return

        if (edited_df["Shares"] < 0).any():
            st.error("Shares cannot be negative.")
            return

        payload = {}
        for _, row in edited_df.iterrows():
            payload[str(row["Ticker"])] = {
                "name": str(row["Name"]),
                "shares": float(row["Shares"]),
            }

        save_private_positions_to_sheets(payload)

        adjustment_count = 0

        if ctx["has_transactions"]:
            current_map = base_df.set_index("Ticker")

            for _, row in edited_df.iterrows():
                ticker = str(row["Ticker"])
                target_shares = float(row["Shares"])

                if ticker in current_map.index:
                    current_shares = float(current_map.loc[ticker, "Shares"])
                    current_row = current_map.loc[ticker]
                else:
                    current_shares = 0.0
                    current_row = pd.Series(dtype="object")

                delta = round(target_shares - current_shares, 8)

                if abs(delta) < 1e-8:
                    continue

                tx_type = "BUY" if delta > 0 else "SELL"
                reference_price = _safe_positive_reference_price(current_row)

                append_transaction_to_sheets(
                    {
                        "date": date.today().isoformat(),
                        "ticker": ticker,
                        "type": tx_type,
                        "shares": abs(float(delta)),
                        "price": float(reference_price),
                        "fees": 0.0,
                        "notes": "MANUAL_ADJUST_FROM_PRIVATE_MANAGER",
                    }
                )
                adjustment_count += 1

        if ctx["has_transactions"]:
            if adjustment_count > 0:
                st.success(
                    f"Private positions sheet updated and {adjustment_count} adjustment transaction(s) were created. Current shares were updated."
                )
            else:
                st.success("Private positions sheet updated. No share differences were detected.")
        else:
            st.success("Private positions sheet updated successfully. Current shares were updated.")

        st.rerun()