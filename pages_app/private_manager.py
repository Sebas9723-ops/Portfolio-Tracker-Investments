import streamlit as st

from app_core import (
    render_page_title,
    info_section,
    save_private_positions_to_sheets,
)


def render_private_manager_page(ctx):
    render_page_title("Private Manager")

    if ctx["mode"] != "Private" or not ctx["authenticated"]:
        st.info("This page is available only in Private mode.")
        return

    info_section("Private Sync", "Manage the private positions snapshot stored in Google Sheets.")

    if ctx["has_transactions"]:
        st.info("Transactions are active. Current private shares are derived from the Transactions sheet. Saving here will update the private snapshot sheet only.")

    st.dataframe(
        ctx["df"][["Ticker", "Name", "Shares", "Source"]],
        use_container_width=True,
        height=320,
    )

    if st.button("Save Current Shares To Private Positions Sheet"):
        payload = {}
        for _, row in ctx["df"].iterrows():
            payload[row["Ticker"]] = {
                "name": row["Name"],
                "shares": float(row["Shares"]),
            }
        save_private_positions_to_sheets(payload)
        st.success("Private positions sheet updated.")
        st.rerun()