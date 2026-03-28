import streamlit as st

from app_core import (
    render_page_title,
    render_status_bar,
    info_section,
    update_selected_private_position,
    build_private_portfolio_for_save,
    save_private_positions_to_sheets,
    get_manage_password,
)


def render_private_manager_page(ctx):
    render_page_title("Private Manager")

    render_status_bar(
        mode=ctx["mode"],
        base_currency=ctx["base_currency"],
        profile=ctx["profile"],
        tc_model=ctx["tc_model"],
        sheets_ok=(ctx["positions_sheet_available"] if ctx["mode"] == "Private" else True),
    )

    info_section(
        "Private Manager",
        "Use the sidebar controls on this page to select one of your existing private tickers and update its current shares. The values are stored in Google Sheets."
    )

    if ctx["mode"] != "Private" or not ctx["authenticated"]:
        st.info("This page is only available in Private mode.")
        return

    st.sidebar.header(
        "Private Position Manager",
        help="Select one of your existing private tickers and update its current shares."
    )

    if not ctx["positions_sheet_available"]:
        st.sidebar.error("Google Sheets connection is not available.")
        if ctx["positions_sheet_error"]:
            st.sidebar.caption(ctx["positions_sheet_error"])

        if st.sidebar.button("Retry Google Sheets", key="retry_google_sheets_manager"):
            st.rerun()
    else:
        manager_password_input = st.sidebar.text_input(
            "Manager Password",
            type="password",
            key="manager_password_input_update",
            help="Required to update a private position in Google Sheets.",
        )

        manager_unlocked = manager_password_input == get_manage_password()

        if manager_password_input and not manager_unlocked:
            st.sidebar.error("Incorrect manager password.")

        if manager_unlocked:
            selectable_tickers = list(ctx["updated_portfolio"].keys())

            selected_ticker = st.sidebar.selectbox(
                "Select Ticker",
                selectable_tickers,
                key="selected_private_ticker_to_update",
                help="Choose which existing private ticker you want to update.",
            )

            current_selected_shares = float(
                st.session_state.get(
                    f"{ctx['prefix']}_shares_{selected_ticker}",
                    ctx["updated_portfolio"][selected_ticker]["shares"]
                )
            )

            selected_name = ctx["updated_portfolio"][selected_ticker]["name"]

            st.sidebar.caption(f"Selected name: {selected_name}")
            st.sidebar.caption(f"Current shares: {current_selected_shares:.4f}")

            new_selected_shares = st.sidebar.number_input(
                "New Current Shares",
                min_value=0.0,
                step=0.0001,
                format="%.4f",
                value=current_selected_shares,
                key=f"new_current_shares_{selected_ticker}",
                help="Write the new current shares for the selected ticker.",
            )

            if st.sidebar.button(
                "Update Selected Position",
                key="update_selected_position_button",
                help="Save only the selected ticker with the new current shares."
            ):
                try:
                    update_selected_private_position(
                        updated_portfolio=ctx["updated_portfolio"],
                        prefix=ctx["prefix"],
                        selected_ticker=selected_ticker,
                        new_shares=new_selected_shares,
                    )
                    st.sidebar.success(f"{selected_ticker} updated successfully.")
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(str(e))

            if st.sidebar.button(
                "Save Private Shares",
                help="Save all current private share quantities to Google Sheets so they persist across sessions."
            ):
                try:
                    sheet_payload = build_private_portfolio_for_save(ctx["updated_portfolio"], ctx["prefix"])
                    save_private_positions_to_sheets(sheet_payload)
                    st.sidebar.success("Private shares saved to Google Sheets.")
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(str(e))

    private_view = ctx["display_df"][["Ticker", "Name", "Shares", "Value", "Weight %"]].copy()
    st.dataframe(private_view, use_container_width=True)