"""
Portfolio alert system.

Checks drawdown, weight deviation, and daily drop thresholds on every app load.
Sends an email alert when conditions are triggered (max once per day per condition).
Tracks sent alerts in Google Sheets tab 'alerts_log'.

Optional secrets (defaults apply if absent):
    [alerts]
    drawdown_threshold        = -0.10   # e.g. -0.10 = alert when drawdown < -10%
    weight_deviation_threshold = 0.05   # e.g. 0.05 = alert when any ticker is >5% off target
    daily_drop_threshold       = -0.03  # e.g. -0.03 = alert when portfolio drops >3% in a day
"""
from __future__ import annotations

import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
import pytz
import streamlit as st

_COLOMBIA_TZ = pytz.timezone("America/Bogota")
_ALERTS_HEADERS = ["date", "sent_at", "type", "message"]


# ── Google Sheets tracking ─────────────────────────────────────────────────────

def _connect_alerts_log():
    from app_core import _connect_named_worksheet
    return _connect_named_worksheet("alerts_log", _ALERTS_HEADERS)


def _alerts_sent_today(alert_types: list[str]) -> set[str]:
    """Return the set of alert types already sent today."""
    try:
        from app_core import _get_spreadsheet_cached, _get_private_positions_sheet_locator, _get_worksheet_records_cached
        sheet_id, sheet_url = _get_private_positions_sheet_locator()
        records = _get_worksheet_records_cached(sheet_id, sheet_url, "alerts_log")
        today = datetime.now(_COLOMBIA_TZ).strftime("%Y-%m-%d")
        return {str(r.get("type", "")).strip() for r in records if str(r.get("date", "")).strip() == today}
    except Exception:
        return set()


def _mark_alerts_sent(alerts: list[dict]):
    try:
        ws = _connect_alerts_log()
        now = datetime.now(_COLOMBIA_TZ)
        today = now.strftime("%Y-%m-%d")
        sent_at = now.isoformat(timespec="seconds")
        for alert in alerts:
            ws.append_row(
                [today, sent_at, alert["type"], alert["message"]],
                value_input_option="RAW",
            )
        from app_core import _clear_google_sheets_cache
        _clear_google_sheets_cache()
    except Exception:
        pass


# ── Condition checks ───────────────────────────────────────────────────────────

def _get_threshold(key: str, default: float) -> float:
    try:
        return float(st.secrets.get("alerts", {}).get(key, default))
    except Exception:
        return default


def check_alert_conditions(ctx: dict) -> list[dict]:
    """
    Returns a list of triggered alert dicts:
    {"type": str, "message": str, "severity": "warning" | "critical"}
    """
    alerts: list[dict] = []

    drawdown_threshold = _get_threshold("drawdown_threshold", -0.10)
    weight_dev_threshold = _get_threshold("weight_deviation_threshold", 0.05)
    daily_drop_threshold = _get_threshold("daily_drop_threshold", -0.03)

    # 1. Max drawdown breach
    max_dd = float(ctx.get("max_drawdown", 0.0))
    if max_dd < drawdown_threshold:
        alerts.append({
            "type": "drawdown",
            "message": f"Max drawdown is {max_dd:.2%}, below threshold of {drawdown_threshold:.2%}.",
            "severity": "critical" if max_dd < drawdown_threshold * 1.5 else "warning",
        })

    # 2. Rolling drawdown (today's reading)
    rolling_df = ctx.get("rolling_df")
    if rolling_df is not None and not rolling_df.empty and "Rolling Drawdown" in rolling_df.columns:
        latest_dd = float(rolling_df["Rolling Drawdown"].iloc[-1])
        if latest_dd < drawdown_threshold and max_dd >= drawdown_threshold:
            alerts.append({
                "type": "rolling_drawdown",
                "message": f"Rolling drawdown is {latest_dd:.2%}, below threshold of {drawdown_threshold:.2%}.",
                "severity": "warning",
            })

    # 3. Weight deviation
    df = ctx.get("df", pd.DataFrame()).copy()
    policy_target_map = ctx.get("policy_target_map", {})
    if not df.empty and policy_target_map:
        for _, row in df.iterrows():
            ticker = str(row["Ticker"])
            current_w = float(row.get("Weight", 0.0))
            target_w = float(policy_target_map.get(ticker, 0.0))
            deviation = abs(current_w - target_w)
            if deviation > weight_dev_threshold:
                alerts.append({
                    "type": "weight_deviation",
                    "message": f"{ticker} is {deviation:.2%} off target weight ({current_w:.2%} vs {target_w:.2%}).",
                    "severity": "warning",
                })

    # 4. Daily portfolio drop
    portfolio_returns = ctx.get("portfolio_returns")
    if portfolio_returns is not None and not portfolio_returns.empty and len(portfolio_returns) >= 2:
        last_return = float(portfolio_returns.iloc[-1])
        if last_return < daily_drop_threshold:
            alerts.append({
                "type": "daily_drop",
                "message": f"Portfolio dropped {last_return:.2%} today (threshold: {daily_drop_threshold:.2%}).",
                "severity": "critical" if last_return < daily_drop_threshold * 1.5 else "warning",
            })

    return alerts


# ── Deduplication ──────────────────────────────────────────────────────────────

def should_send_alerts(ctx: dict, alerts: list[dict]) -> bool:
    if ctx.get("app_scope") != "private" or not ctx.get("authenticated"):
        return False
    if not alerts:
        return False

    alert_types = [a["type"] for a in alerts]

    # Session-level dedup
    sent_session = st.session_state.get("alerts_sent_session", set())
    new_alerts = [a for a in alerts if a["type"] not in sent_session]
    if not new_alerts:
        return False

    # Sheets-level dedup (once per day)
    sent_today = _alerts_sent_today(alert_types)
    truly_new = [a for a in new_alerts if a["type"] not in sent_today]
    if not truly_new:
        # Update session cache so we don't keep hitting Sheets
        st.session_state["alerts_sent_session"] = sent_session | sent_today
        return False

    # Mutate alerts in place to only send truly new ones
    alerts.clear()
    alerts.extend(truly_new)
    return True


# ── HTML builder ───────────────────────────────────────────────────────────────

_table = "border-collapse:collapse;width:100%;margin-top:8px"
_th = "background:#1a1f2e;color:#f3a712;padding:8px 12px;text-align:left;border:1px solid #2a2f3e;font-family:monospace"
_td = "padding:7px 12px;border:1px solid #1e2430;color:#e6e6e6;font-family:monospace"


def _build_alert_html(alerts: list[dict], ctx: dict) -> str:
    now_col = datetime.now(_COLOMBIA_TZ)
    ccy = ctx.get("base_currency", "USD")
    total = float(ctx.get("total_portfolio_value", 0.0))

    color_map = {"critical": "#f44336", "warning": "#f3a712"}
    rows = ""
    for a in alerts:
        color = color_map.get(a["severity"], "#e6e6e6")
        rows += f"""
        <tr>
            <td style="{_td};color:{color};font-weight:bold">{a['severity'].upper()}</td>
            <td style="{_td}">{a['type'].replace('_', ' ').title()}</td>
            <td style="{_td}">{a['message']}</td>
        </tr>"""

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="background-color:#0b0f14;color:#e6e6e6;font-family:monospace;padding:32px;margin:0">
      <h1 style="color:#f44336;font-size:22px;margin-bottom:4px">PORTFOLIO ALERT</h1>
      <h2 style="color:#aaa;font-size:14px;margin-top:0">Portafolio Management SA · {now_col.strftime('%Y-%m-%d %H:%M')} Colombia</h2>

      <p style="color:#e6e6e6">
        Portfolio value at time of alert: <b>{ccy} {total:,.2f}</b>
      </p>

      <table style="{_table}">
        <tr>
          <th style="{_th}">Severity</th>
          <th style="{_th}">Type</th>
          <th style="{_th}">Detail</th>
        </tr>
        {rows}
      </table>

      <hr style="border-color:#333;margin-top:40px">
      <p style="color:#555;font-size:11px">
        Generated automatically by Portafolio Management SA · {now_col.strftime('%Y-%m-%d %H:%M')} Colombia time
      </p>
    </body>
    </html>
    """


# ── Send ───────────────────────────────────────────────────────────────────────

def send_alert_email(alerts: list[dict], ctx: dict):
    email_cfg = st.secrets.get("email", {})
    smtp_host = str(email_cfg.get("smtp_host", "smtp.gmail.com"))
    smtp_port = int(email_cfg.get("smtp_port", 587))
    sender = str(email_cfg.get("sender", ""))
    password = str(email_cfg.get("app_password", ""))
    recipient = str(email_cfg.get("recipient", ""))

    if not all([sender, password, recipient]):
        return

    severities = [a["severity"] for a in alerts]
    subject_prefix = "CRITICAL" if "critical" in severities else "WARNING"
    now_col = datetime.now(_COLOMBIA_TZ)
    subject = f"[{subject_prefix}] Portfolio Alert · {now_col.strftime('%Y-%m-%d %H:%M')} · Portafolio Management SA"

    html_body = _build_alert_html(alerts, ctx)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())

        _mark_alerts_sent(alerts)

        sent_session = st.session_state.get("alerts_sent_session", set())
        st.session_state["alerts_sent_session"] = sent_session | {a["type"] for a in alerts}
    except Exception:
        pass
