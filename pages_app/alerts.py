import uuid
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import streamlit as st

from app_core import (
    ALERTS_HEADERS,
    append_alert_to_sheets,
    delete_alert,
    get_manage_password,
    info_metric,
    info_section,
    load_alerts_from_sheets,
    render_page_title,
    send_telegram_message,
    update_alert_field,
)


# ── Alert types ───────────────────────────────────────────────────────────────

ALERT_TYPE_LABELS = {
    "price_above":      "Price Above threshold",
    "price_below":      "Price Below threshold",
    "day_change_pct":   "Day Change % drops below threshold",
    "portfolio_value":  "Portfolio Value drops below threshold",
    "rsi_overbought":   "RSI > 70 (overbought)",
    "rsi_oversold":     "RSI < 30 (oversold)",
    "weight_drift":     "Position weight drifts > threshold from target",
}

TICKER_REQUIRED = {
    "price_above", "price_below", "day_change_pct",
    "rsi_overbought", "rsi_oversold", "weight_drift",
}

THRESHOLD_LABELS = {
    "price_above": "Price threshold (e.g. 250.00)",
    "price_below": "Price threshold (e.g. 180.00)",
    "day_change_pct": "Day drop threshold (e.g. -0.05 for -5%)",
    "portfolio_value": "Portfolio value floor (e.g. 50000)",
    "rsi_overbought": "RSI level (default 70)",
    "rsi_oversold": "RSI level (default 30)",
    "weight_drift": "Max drift from target (e.g. 0.05 for 5%)",
}

THRESHOLD_DEFAULTS = {
    "price_above": 200.0,
    "price_below": 100.0,
    "day_change_pct": -0.05,
    "portfolio_value": 50_000.0,
    "rsi_overbought": 70.0,
    "rsi_oversold": 30.0,
    "weight_drift": 0.05,
}


# ── Price and RSI fetching ────────────────────────────────────────────────────

@st.cache_data(ttl=240, show_spinner=False)
def _fetch_prices_for_alerts(tickers: tuple) -> dict[str, float]:
    import yfinance as yf
    prices = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).fast_info
            p = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
            if p and float(p) > 0:
                prices[t] = float(p)
        except Exception:
            pass
    return prices


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_rsi_batch(tickers: tuple) -> dict[str, float]:
    import yfinance as yf
    result = {}
    if not tickers:
        return result
    try:
        raw = yf.download(list(tickers), period="60d", auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
        else:
            close = raw[["Close"]].rename(columns={"Close": tickers[0]})

        for t in tickers:
            if t not in close.columns:
                continue
            s = pd.to_numeric(close[t], errors="coerce").dropna()
            if len(s) < 15:
                continue
            delta = s.diff()
            avg_gain = delta.clip(lower=0).rolling(14).mean()
            avg_loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            rsi = 100 - 100 / (1 + rs)
            result[t] = float(rsi.iloc[-1])
    except Exception:
        pass
    return result


# ── Alert condition checking ──────────────────────────────────────────────────

def _check_single_alert(
    alert: dict,
    prices: dict[str, float],
    rsi_values: dict[str, float],
    ctx: dict,
) -> tuple[bool, str]:
    """Returns (triggered, human-readable message)."""
    alert_type = str(alert.get("alert_type", ""))
    ticker = str(alert.get("ticker", "")).upper().strip()
    threshold = float(alert.get("threshold", 0.0))

    try:
        if alert_type == "price_above":
            price = prices.get(ticker)
            if price is None:
                return False, ""
            triggered = price > threshold
            return triggered, f"<b>{ticker}</b> price <b>{price:.2f}</b> &gt; {threshold:.2f}"

        elif alert_type == "price_below":
            price = prices.get(ticker)
            if price is None:
                return False, ""
            triggered = price < threshold
            return triggered, f"<b>{ticker}</b> price <b>{price:.2f}</b> &lt; {threshold:.2f}"

        elif alert_type == "day_change_pct":
            asset_returns = ctx.get("asset_returns", pd.DataFrame())
            if asset_returns is None or asset_returns.empty or ticker not in asset_returns.columns:
                return False, ""
            last_ret = float(asset_returns[ticker].dropna().iloc[-1])
            triggered = last_ret < threshold
            return triggered, f"<b>{ticker}</b> day change <b>{last_ret:.2%}</b> &lt; {threshold:.2%}"

        elif alert_type == "portfolio_value":
            total = float(ctx.get("total_portfolio_value", 0.0))
            triggered = total < threshold
            return triggered, f"Portfolio value <b>{total:,.2f}</b> &lt; {threshold:,.2f}"

        elif alert_type == "rsi_overbought":
            rsi = rsi_values.get(ticker)
            if rsi is None:
                return False, ""
            triggered = rsi > threshold
            return triggered, f"<b>{ticker}</b> RSI <b>{rsi:.1f}</b> &gt; {threshold:.0f} (overbought)"

        elif alert_type == "rsi_oversold":
            rsi = rsi_values.get(ticker)
            if rsi is None:
                return False, ""
            triggered = rsi < threshold
            return triggered, f"<b>{ticker}</b> RSI <b>{rsi:.1f}</b> &lt; {threshold:.0f} (oversold)"

        elif alert_type == "weight_drift":
            df = ctx.get("df", pd.DataFrame())
            policy_map = ctx.get("policy_target_map", {})
            if df.empty or ticker not in df["Ticker"].values:
                return False, ""
            current_w = float(df.loc[df["Ticker"] == ticker, "Weight"].iloc[0])
            target_w = float(policy_map.get(ticker, current_w))
            drift = abs(current_w - target_w)
            triggered = drift > threshold
            return triggered, (
                f"<b>{ticker}</b> weight drift <b>{drift:.2%}</b> &gt; {threshold:.2%} "
                f"(current {current_w:.2%}, target {target_w:.2%})"
            )

    except Exception:
        pass

    return False, ""


def _should_skip_due_to_cooldown(last_triggered_str: str, cooldown_hours: int = 1) -> bool:
    """Return True if this alert fired within the last cooldown_hours."""
    if not last_triggered_str or str(last_triggered_str).strip() == "":
        return False
    try:
        last_dt = pd.to_datetime(last_triggered_str)
        if last_dt.tzinfo is None:
            last_dt = last_dt.tz_localize("UTC")
        now_utc = pd.Timestamp.now(tz="UTC")
        return (now_utc - last_dt) < timedelta(hours=cooldown_hours)
    except Exception:
        return False


def _check_all_alerts(alerts_df: pd.DataFrame, ctx: dict) -> list[dict]:
    """Return list of triggered alerts with their messages."""
    active = alerts_df[alerts_df["active"] == True]
    if active.empty:
        return []

    # Batch-fetch prices and RSI for relevant tickers
    price_tickers = tuple(sorted({
        str(r["ticker"]).upper()
        for _, r in active.iterrows()
        if r["alert_type"] in ("price_above", "price_below", "day_change_pct")
        and str(r["ticker"]).strip()
    }))
    rsi_tickers = tuple(sorted({
        str(r["ticker"]).upper()
        for _, r in active.iterrows()
        if r["alert_type"] in ("rsi_overbought", "rsi_oversold")
        and str(r["ticker"]).strip()
    }))

    prices = _fetch_prices_for_alerts(price_tickers) if price_tickers else {}
    rsi_values = _fetch_rsi_batch(rsi_tickers) if rsi_tickers else {}

    triggered = []
    for _, alert in active.iterrows():
        if _should_skip_due_to_cooldown(str(alert.get("last_triggered", ""))):
            continue

        fired, message = _check_single_alert(dict(alert), prices, rsi_values, ctx)
        if fired:
            triggered.append({
                "id": str(alert["id"]),
                "ticker": str(alert["ticker"]),
                "alert_type": str(alert["alert_type"]),
                "message": message,
                "notes": str(alert.get("notes", "")),
            })

    return triggered


# ── Auto-check fragment ───────────────────────────────────────────────────────

def _auto_check_fragment(ctx: dict):
    @st.fragment(run_every=300)
    def _inner():
        alerts_df = load_alerts_from_sheets()
        if alerts_df.empty or alerts_df["active"].sum() == 0:
            st.caption(f"No active alerts · Last checked: {datetime.now().strftime('%H:%M:%S')}")
            return

        triggered = _check_all_alerts(alerts_df, ctx)

        if triggered:
            for t in triggered:
                # Send Telegram
                msg = (
                    f"🚨 <b>Portfolio Alert</b>\n\n"
                    f"{t['message']}"
                    + (f"\n<i>{t['notes']}</i>" if t["notes"] else "")
                    + f"\n\n<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
                )
                sent = send_telegram_message(msg)
                # Update last_triggered in Sheets
                update_alert_field(t["id"], "last_triggered", datetime.utcnow().isoformat())

                tg_icon = "✅" if sent else "⚠️"
                st.warning(
                    f"{tg_icon} **Alert triggered:** {t['ticker']} — "
                    + t["message"].replace("<b>", "**").replace("</b>", "**").replace("&gt;", ">").replace("&lt;", "<"),
                    icon="🚨",
                )
        else:
            active_count = int(alerts_df["active"].sum())
            st.success(
                f"All clear — {active_count} alert{'s' if active_count != 1 else ''} monitored, none triggered.",
                icon="✅",
            )

        st.caption(f"Last checked: {datetime.now().strftime('%H:%M:%S')} · Auto-refreshes every 5 min")

    _inner()


# ── CRUD UI ───────────────────────────────────────────────────────────────────

def _render_create_form(portfolio_tickers: list[str]):
    with st.expander("➕ Add New Alert", expanded=False):
        with st.form("alerts_create_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            alert_type = c1.selectbox(
                "Alert type",
                list(ALERT_TYPE_LABELS.keys()),
                format_func=lambda k: ALERT_TYPE_LABELS[k],
                key="al_type",
            )
            needs_ticker = alert_type in TICKER_REQUIRED
            if needs_ticker:
                ticker_options = portfolio_tickers + ["Custom..."]
                selected = c2.selectbox("Ticker (portfolio)", ticker_options, key="al_ticker_pick")
                if selected == "Custom...":
                    ticker = st.text_input("Custom ticker", key="al_ticker_custom").upper().strip()
                else:
                    ticker = selected
            else:
                ticker = ""
                c2.info("No ticker required for this alert type.")

            threshold = st.number_input(
                THRESHOLD_LABELS.get(alert_type, "Threshold"),
                value=float(THRESHOLD_DEFAULTS.get(alert_type, 0.0)),
                step=0.01, format="%.4f",
                key="al_threshold",
            )
            notes = st.text_input("Notes (optional)", key="al_notes")
            auth = st.text_input("Authorization password", type="password", key="al_auth")
            submitted = st.form_submit_button("Create Alert", type="primary", use_container_width=True)

        if submitted:
            if auth != get_manage_password():
                st.error("Incorrect authorization password.")
                return
            if needs_ticker and not ticker:
                st.error("Ticker is required for this alert type.")
                return

            condition_str = f"{ALERT_TYPE_LABELS[alert_type]} | threshold={threshold}"
            alert = {
                "id": str(uuid.uuid4())[:8],
                "ticker": ticker.upper().strip(),
                "alert_type": alert_type,
                "condition": condition_str,
                "threshold": str(threshold),
                "active": "TRUE",
                "created_at": datetime.utcnow().isoformat(),
                "last_triggered": "",
                "notes": notes.strip(),
            }
            try:
                append_alert_to_sheets(alert)
                st.cache_data.clear()
                st.success(f"Alert created: {condition_str}")
                st.rerun()
            except Exception as e:
                st.error(f"Could not save alert: {e}")


def _render_alerts_table(alerts_df: pd.DataFrame):
    if alerts_df.empty:
        st.info("No alerts configured yet.")
        return

    display = alerts_df.copy()
    display["active"] = display["active"].map({True: "✅ Active", False: "⏸ Paused"})
    display["alert_type"] = display["alert_type"].map(
        lambda k: ALERT_TYPE_LABELS.get(k, k)
    )
    display["threshold"] = display["threshold"].apply(lambda v: f"{float(v):.4f}" if v else "")
    display["last_triggered"] = display["last_triggered"].apply(
        lambda v: str(v)[:19].replace("T", " ") if v else "Never"
    )
    display["created_at"] = display["created_at"].apply(
        lambda v: str(v)[:10] if v else ""
    )

    st.dataframe(
        display[["id", "ticker", "alert_type", "threshold", "active", "last_triggered", "notes"]].rename(
            columns={
                "id": "ID", "ticker": "Ticker", "alert_type": "Alert Type",
                "threshold": "Threshold", "active": "Status",
                "last_triggered": "Last Triggered", "notes": "Notes",
            }
        ),
        use_container_width=True,
        height=280,
    )

    # Management actions
    if len(alerts_df) > 0:
        st.markdown("#### Manage Alert")
        alert_ids = alerts_df["id"].tolist()
        mgmt_col1, mgmt_col2, mgmt_col3, mgmt_col4 = st.columns([2, 1, 1, 2])

        with mgmt_col1:
            selected_id = st.selectbox(
                "Select alert ID", alert_ids, key="al_manage_id",
            )
        with mgmt_col4:
            mgmt_auth = st.text_input(
                "Password", type="password", key="al_manage_auth",
            )

        selected_row = alerts_df[alerts_df["id"] == selected_id]
        is_active = bool(selected_row["active"].iloc[0]) if not selected_row.empty else True

        with mgmt_col2:
            toggle_label = "⏸ Pause" if is_active else "▶ Activate"
            if st.button(toggle_label, key="al_toggle", use_container_width=True):
                if mgmt_auth != get_manage_password():
                    st.error("Wrong password.")
                else:
                    new_val = "FALSE" if is_active else "TRUE"
                    update_alert_field(selected_id, "active", new_val)
                    st.cache_data.clear()
                    st.rerun()

        with mgmt_col3:
            if st.button("🗑 Delete", key="al_delete", use_container_width=True):
                if mgmt_auth != get_manage_password():
                    st.error("Wrong password.")
                else:
                    delete_alert(selected_id)
                    st.cache_data.clear()
                    st.rerun()


# ── Page renderer ─────────────────────────────────────────────────────────────

def render_alerts_page(ctx: dict):
    render_page_title("Custom Alerts")

    if ctx.get("app_scope") != "private" or not ctx.get("authenticated"):
        st.warning("Custom Alerts is only available in Private mode.")
        return

    # Telegram config check
    tg = st.secrets.get("telegram", {})
    has_telegram = bool(tg.get("bot_token", "").strip()) and bool(tg.get("chat_id", "").strip())
    if not has_telegram:
        st.warning(
            "Telegram not configured. Add to `.streamlit/secrets.toml`:\n"
            "```toml\n[telegram]\nbot_token = \"xxxx:yyyy\"\nchat_id = \"123456789\"\n```",
        )
    else:
        st.success("Telegram bot connected.", icon="🤖")

    # ── Auto-check section (runs every 5 min) ──────────────────────────────────
    info_section("Alert Monitor", "Checks all active alerts every 5 minutes and sends Telegram notifications.")
    _auto_check_fragment(ctx)

    # ── Alert rules table ──────────────────────────────────────────────────────
    info_section("Alert Rules", "All configured alerts.")
    alerts_df = load_alerts_from_sheets()
    _render_alerts_table(alerts_df)

    # ── Create new alert ───────────────────────────────────────────────────────
    info_section("Create New Alert", "Configure a new price, portfolio, or technical alert.")
    portfolio_tickers = list(ctx.get("updated_portfolio", {}).keys())
    _render_create_form(portfolio_tickers)

    # ── Telegram test ──────────────────────────────────────────────────────────
    if has_telegram:
        info_section("Telegram Test", "Send a test message to confirm your bot is working.")
        if st.button("Send Test Message", key="al_test_tg"):
            sent = send_telegram_message(
                f"✅ <b>Portfolio Management SA</b>\n\n"
                f"Alert system test — connection confirmed.\n"
                f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
            )
            if sent:
                st.success("Test message sent to Telegram.")
            else:
                st.error("Failed to send — check bot_token and chat_id in secrets.")
