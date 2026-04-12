import uuid
from datetime import date

import pandas as pd
import streamlit as st

from utils_aggrid import show_aggrid

from app_core import (
    append_order_to_blotter,
    get_manage_password,
    info_section,
    load_order_blotter_from_sheets,
    render_page_title,
    update_order_status,
)

_STATUS_OPTIONS = ["Pending", "Filled", "Partially Filled", "Cancelled"]
_ACTIVE_STATUSES = {"Pending", "Partially Filled"}
_HISTORY_STATUSES = {"Filled", "Cancelled"}
_DIRECTION_OPTIONS = ["BUY", "SELL"]


def _auth_check() -> bool:
    if st.session_state.get("blotter_auth"):
        return True
    pw = st.text_input("Management password", type="password", key="blotter_pw_input")
    if st.button("Unlock Order Blotter", key="blotter_pw_btn"):
        if pw == get_manage_password():
            st.session_state["blotter_auth"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


def _load_blotter() -> pd.DataFrame:
    try:
        return load_order_blotter_from_sheets()
    except Exception as e:
        st.warning(f"Could not load order blotter: {e}")
        return pd.DataFrame()


def _render_active_orders(df: pd.DataFrame):
    info_section(
        "Active Orders",
        "Pending and Partially Filled orders. Use buttons to update status.",
    )

    active = df[df["status"].isin(_ACTIVE_STATUSES)].copy() if not df.empty else pd.DataFrame()

    if active.empty:
        st.info("No active orders.")
        return

    for _, row in active.iterrows():
        order_id = str(row.get("id", ""))
        ticker = str(row.get("ticker", ""))
        direction = str(row.get("direction", ""))
        qty = row.get("quantity", "")
        limit_px = row.get("limit_price", "")
        status = str(row.get("status", ""))
        notes = str(row.get("notes", ""))
        dt = row.get("date", "")
        dt_str = dt.strftime("%Y-%m-%d") if pd.notna(dt) and hasattr(dt, "strftime") else str(dt)

        dir_color = "#00e676" if direction == "BUY" else "#ff5252"
        st.markdown(
            f"<div style='padding:10px 14px;border-radius:6px;margin-bottom:8px;"
            f"background:#1a1f2e;border-left:4px solid {dir_color}'>"
            f"<b style='color:{dir_color}'>{direction}</b> "
            f"<b style='color:#f3a712'>{ticker}</b> "
            f"<span style='color:#e6e6e6'>Qty: {qty}</span> "
            f"{'| Limit: ' + str(limit_px) if pd.notna(limit_px) and limit_px != '' else ''} "
            f"| <span style='color:#888;font-size:12px'>{status}</span> "
            f"| <span style='color:#888;font-size:11px'>{dt_str}</span>"
            f"{'<br><span style=\"color:#aaa;font-size:11px\">' + notes + '</span>' if notes and notes != 'nan' else ''}"
            f"</div>",
            unsafe_allow_html=True,
        )

        c1, c2, c3 = st.columns([1, 1, 4])
        if c1.button("Mark Filled", key=f"fill_{order_id}"):
            try:
                update_order_status(order_id, {"status": "Filled"})
                st.success(f"Order {order_id} marked as Filled.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to update order: {e}")
        if c2.button("Cancel", key=f"cancel_{order_id}"):
            try:
                update_order_status(order_id, {"status": "Cancelled"})
                st.success(f"Order {order_id} cancelled.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to cancel order: {e}")


def _render_history(df: pd.DataFrame):
    info_section(
        "Order History",
        "All Filled and Cancelled orders.",
    )

    history = df[df["status"].isin(_HISTORY_STATUSES)].copy() if not df.empty else pd.DataFrame()

    if history.empty:
        st.info("No order history.")
        return

    display = history[["date", "ticker", "direction", "quantity", "limit_price",
                        "status", "filled_price", "filled_qty", "notes"]].copy()
    if "date" in display.columns:
        display["date"] = pd.to_datetime(display["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    show_aggrid(display, height=400, key="aggrid_order_blotter_history")


def _render_new_order():
    info_section(
        "New Order",
        "Submit a new order to the blotter.",
    )

    with st.form("new_order_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        ticker = c1.text_input("Ticker", placeholder="AAPL").upper().strip()
        direction = c2.selectbox("Direction", _DIRECTION_OPTIONS)
        quantity = c3.number_input("Quantity", min_value=0.0, step=1.0)

        c4, c5 = st.columns(2)
        limit_price = c4.number_input("Limit Price (optional, 0 = market)", min_value=0.0, step=0.01)
        notes = c5.text_input("Notes", placeholder="Optional notes")

        submitted = st.form_submit_button("Submit Order", type="primary")
        if submitted:
            if not ticker:
                st.error("Ticker is required.")
            elif quantity <= 0:
                st.error("Quantity must be greater than 0.")
            else:
                order = {
                    "id": str(uuid.uuid4())[:8],
                    "date": str(date.today()),
                    "ticker": ticker,
                    "direction": direction,
                    "quantity": float(quantity),
                    "limit_price": float(limit_price) if limit_price > 0 else "",
                    "status": "Pending",
                    "filled_price": "",
                    "filled_qty": "",
                    "notes": notes.strip(),
                }
                try:
                    append_order_to_blotter(order)
                    st.success(f"Order {order['id']} submitted: {direction} {quantity} {ticker}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to submit order: {e}")


def render_order_blotter_page(ctx):
    render_page_title("Order Blotter")

    if not _auth_check():
        return

    df = _load_blotter()

    tab1, tab2, tab3 = st.tabs(["Active Orders", "History", "New Order"])

    with tab1:
        try:
            _render_active_orders(df)
        except Exception as e:
            st.error(f"Error loading active orders: {e}")

    with tab2:
        try:
            _render_history(df)
        except Exception as e:
            st.error(f"Error loading order history: {e}")

    with tab3:
        try:
            _render_new_order()
        except Exception as e:
            st.error(f"Error in new order form: {e}")
