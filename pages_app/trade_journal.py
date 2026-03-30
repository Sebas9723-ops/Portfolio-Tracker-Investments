import uuid
from datetime import date

import pandas as pd
import streamlit as st

from app_core import (
    append_trade_journal_entry,
    get_manage_password,
    info_section,
    load_trade_journal_from_sheets,
    render_page_title,
    update_trade_journal_entry,
)


_STATUS_OPTIONS = ["Active", "Validated", "Invalidated", "Closed"]
_DIRECTION_OPTIONS = ["BUY", "SELL"]


def _auth_check() -> bool:
    if st.session_state.get("journal_auth"):
        return True
    pw = st.text_input("Management password", type="password", key="journal_pw_input")
    if st.button("Unlock Journal", key="journal_pw_btn"):
        if pw == get_manage_password():
            st.session_state["journal_auth"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


def _load_journal() -> pd.DataFrame:
    try:
        return load_trade_journal_from_sheets()
    except Exception as e:
        st.warning(f"Could not load trade journal: {e}")
        return pd.DataFrame()


def _compute_pnl_row(row: pd.Series, current_prices: dict) -> float | None:
    """Current open P&L or realised P&L for closed entries."""
    ticker = str(row.get("ticker", "")).upper()
    direction = str(row.get("direction", "")).upper()
    shares = float(row.get("shares") or 0)
    entry_price = float(row.get("entry_price") or 0)
    exit_price = row.get("exit_price")

    if shares <= 0 or entry_price <= 0:
        return None

    if pd.notna(exit_price) and float(exit_price) > 0:
        close_px = float(exit_price)
    else:
        close_px = current_prices.get(ticker)

    if close_px is None:
        return None

    if direction == "BUY":
        return (close_px - entry_price) * shares
    else:
        return (entry_price - close_px) * shares


def _render_new_entry_form(ctx):
    tickers = list(ctx.get("updated_portfolio", {}).keys())
    base_currency = ctx.get("base_currency", "USD")

    info_section("New Trade Entry", "Record the thesis and trade parameters for a new position.")

    with st.form("new_journal_entry", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            ticker = st.selectbox("Ticker", tickers, key="nj_ticker") if tickers else st.text_input("Ticker")
            direction = st.selectbox("Direction", _DIRECTION_OPTIONS, key="nj_dir")
        with c2:
            entry_date = st.date_input("Entry Date", value=date.today(), key="nj_date")
            shares = st.number_input("Shares", min_value=0.0, step=0.01, format="%.4f", key="nj_shares")
        with c3:
            entry_price = st.number_input(
                f"Entry Price ({base_currency})", min_value=0.0, step=0.01, format="%.4f", key="nj_price"
            )
            status = st.selectbox("Status", _STATUS_OPTIONS, key="nj_status")

        c4, c5 = st.columns(2)
        with c4:
            target_price = st.number_input(
                f"Target Price ({base_currency})", min_value=0.0, step=0.01, format="%.4f", key="nj_target"
            )
        with c5:
            stop_loss = st.number_input(
                f"Stop Loss ({base_currency})", min_value=0.0, step=0.01, format="%.4f", key="nj_stop"
            )

        thesis = st.text_area(
            "Investment Thesis",
            placeholder="Why are you entering this trade? What is the catalyst, valuation rationale, or risk factor?",
            key="nj_thesis",
            height=100,
        )
        notes = st.text_input("Notes (optional)", key="nj_notes")

        submitted = st.form_submit_button("Add to Journal", type="primary", use_container_width=True)
        if submitted:
            if not ticker or entry_price <= 0 or shares <= 0:
                st.error("Ticker, shares, and entry price are required.")
            elif not thesis.strip():
                st.error("Investment thesis is required.")
            else:
                entry = {
                    "id": str(uuid.uuid4())[:8],
                    "date": str(entry_date),
                    "ticker": str(ticker).upper().strip(),
                    "direction": direction,
                    "shares": shares,
                    "entry_price": entry_price,
                    "target_price": target_price if target_price > 0 else "",
                    "stop_loss": stop_loss if stop_loss > 0 else "",
                    "thesis": thesis.strip(),
                    "status": status,
                    "exit_date": "",
                    "exit_price": "",
                    "notes": notes.strip(),
                }
                try:
                    append_trade_journal_entry(entry)
                    st.success(f"Entry added for {ticker}.")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not save entry: {e}")


def _render_journal_table(ctx, journal_df: pd.DataFrame):
    if journal_df is None or journal_df.empty:
        st.info("No trade journal entries yet. Add your first entry above.")
        return

    info_section("Trade Journal", "All recorded trades with thesis and P&L tracking.")

    # Compute P&L against current prices
    df_ctx = ctx.get("df", pd.DataFrame())
    current_prices = {}
    if not df_ctx.empty and "Ticker" in df_ctx.columns and "Price" in df_ctx.columns:
        current_prices = df_ctx.set_index("Ticker")["Price"].to_dict()

    display = journal_df.copy()
    display["P&L"] = display.apply(lambda r: _compute_pnl_row(r, current_prices), axis=1)
    display["P&L"] = display["P&L"].apply(lambda v: f"{v:+.2f}" if pd.notna(v) else "—")

    display["entry_price"] = display["entry_price"].apply(
        lambda v: f"{v:.4f}" if pd.notna(v) else "—"
    )
    display["target_price"] = display["target_price"].apply(
        lambda v: f"{v:.4f}" if pd.notna(v) else "—"
    )
    display["stop_loss"] = display["stop_loss"].apply(
        lambda v: f"{v:.4f}" if pd.notna(v) else "—"
    )
    display["date"] = display["date"].apply(
        lambda v: str(v.date()) if pd.notna(v) else "—"
    )

    rename = {
        "id": "ID", "date": "Date", "ticker": "Ticker", "direction": "Dir",
        "shares": "Shares", "entry_price": "Entry Px", "target_price": "Target",
        "stop_loss": "Stop", "thesis": "Thesis", "status": "Status", "notes": "Notes",
        "P&L": "P&L",
    }
    cols_show = ["date", "ticker", "direction", "shares", "entry_price", "target_price",
                 "stop_loss", "status", "P&L", "thesis", "notes"]
    display = display[[c for c in cols_show if c in display.columns]].rename(columns=rename)

    st.dataframe(display, use_container_width=True, hide_index=True)


def _render_journal_stats(journal_df: pd.DataFrame, ctx):
    if journal_df is None or journal_df.empty:
        return

    info_section("Journal Statistics", "Win rate, average holding period, and P&L summary.")

    df_ctx = ctx.get("df", pd.DataFrame())
    current_prices = {}
    if not df_ctx.empty and "Ticker" in df_ctx.columns and "Price" in df_ctx.columns:
        current_prices = df_ctx.set_index("Ticker")["Price"].to_dict()

    pnls = journal_df.apply(lambda r: _compute_pnl_row(r, current_prices), axis=1).dropna()
    total = len(journal_df)
    winners = int((pnls > 0).sum())
    losers = int((pnls < 0).sum())
    total_pnl = float(pnls.sum()) if not pnls.empty else 0.0
    win_rate = winners / len(pnls) * 100 if len(pnls) > 0 else 0.0

    avg_hold = None
    if "exit_date" in journal_df.columns and "date" in journal_df.columns:
        closed = journal_df[journal_df["exit_date"].notna()].copy()
        if not closed.empty:
            hold_days = (
                pd.to_datetime(closed["exit_date"], errors="coerce") -
                pd.to_datetime(closed["date"], errors="coerce")
            ).dt.days.dropna()
            if not hold_days.empty:
                avg_hold = hold_days.mean()

    status_counts = journal_df["status"].value_counts().to_dict()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Entries", total)
    c2.metric("Win Rate", f"{win_rate:.0f}%", f"{winners}W / {losers}L")
    c3.metric("Total P&L", f"{total_pnl:+.2f}")
    c4.metric("Avg Hold (closed)", f"{avg_hold:.0f}d" if avg_hold else "—")
    active_count = int(status_counts.get("Active", 0))
    c5.metric("Active Theses", active_count)

    # Status breakdown
    if status_counts:
        st.markdown("**Thesis Status Breakdown**")
        cols = st.columns(len(status_counts))
        for i, (s, cnt) in enumerate(sorted(status_counts.items())):
            color = {"Active": "#f3a712", "Validated": "#00c853",
                     "Invalidated": "#ff1744", "Closed": "#888"}.get(s, "#e6e6e6")
            cols[i].markdown(
                f"<div style='text-align:center;padding:8px;border-radius:6px;"
                f"background:#1a1f2e;border:1px solid {color}'>"
                f"<span style='color:{color};font-size:18px;font-weight:bold'>{cnt}</span><br>"
                f"<span style='color:#aaa;font-size:12px'>{s}</span></div>",
                unsafe_allow_html=True,
            )


def _render_close_entry_form(journal_df: pd.DataFrame):
    active = journal_df[journal_df["status"] == "Active"] if journal_df is not None and not journal_df.empty else pd.DataFrame()
    if active.empty:
        return

    info_section("Close / Update Entry", "Mark a trade as Closed or update its thesis status.")

    with st.expander("Update an entry", expanded=False):
        ids = active["id"].tolist()
        labels = [f"{row['ticker']} — {row['id']} ({str(row['date'])[:10]})"
                  for _, row in active.iterrows()]
        chosen = st.selectbox("Select entry", labels, key="close_entry_select")
        idx = labels.index(chosen)
        entry_id = ids[idx]

        c1, c2 = st.columns(2)
        new_status = c1.selectbox("New Status", _STATUS_OPTIONS, index=2, key="close_status")
        exit_date = c2.date_input("Exit Date", value=date.today(), key="close_exit_date")
        exit_price = st.number_input("Exit Price (0 = skip)", min_value=0.0, step=0.01,
                                     format="%.4f", key="close_exit_price")
        notes_upd = st.text_input("Update Notes (optional)", key="close_notes")

        if st.button("Update Entry", key="close_update_btn", type="primary"):
            updates = {"status": new_status, "exit_date": str(exit_date)}
            if exit_price > 0:
                updates["exit_price"] = exit_price
            if notes_upd.strip():
                updates["notes"] = notes_upd.strip()
            try:
                update_trade_journal_entry(entry_id, updates)
                st.success("Entry updated.")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Could not update entry: {e}")


def render_trade_journal_page(ctx):
    render_page_title("Trade Journal")

    if ctx.get("app_scope") != "private":
        st.info("Trade Journal is only available in Private mode.")
        return

    if not _auth_check():
        return

    journal_df = _load_journal()

    tab1, tab2, tab3 = st.tabs(["Journal", "Statistics", "New Entry"])

    with tab1:
        _render_journal_table(ctx, journal_df)
        _render_close_entry_form(journal_df)
    with tab2:
        _render_journal_stats(journal_df, ctx)
    with tab3:
        _render_new_entry_form(ctx)
