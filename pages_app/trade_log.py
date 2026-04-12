"""Trade Log — merged page (Trade Journal + Order Blotter tabs)."""
import streamlit as st
from app_core import render_page_title
from pages_app.trade_journal import render_trade_journal_page
from pages_app.order_blotter import render_order_blotter_page


def render_trade_log_page(ctx):
    render_page_title("Trade Log")
    tab_journal, tab_blotter = st.tabs(["Trade Journal", "Order Blotter"])
    with tab_journal:
        render_trade_journal_page(ctx)
    with tab_blotter:
        render_order_blotter_page(ctx)
