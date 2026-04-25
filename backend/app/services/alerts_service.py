"""
Portfolio alert conditions checked daily after market close.
Sends Telegram notifications for: daily drop, drawdown, large individual losses.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

log = logging.getLogger(__name__)

# Default thresholds
DAILY_DROP_THRESHOLD = -0.03      # -3% in a single day
DRAWDOWN_THRESHOLD = -0.10        # -10% max drawdown
POSITION_LOSS_THRESHOLD = -0.10   # -10% unrealized loss on a single position
WEIGHT_DRIFT_THRESHOLD = 0.08     # 8% drift from target weight


def _sign(v: float) -> str:
    return "+" if v >= 0 else ""


def check_alerts(summary, metrics: dict, snapshots: list[dict]) -> list[dict]:
    """
    Check portfolio alert conditions.
    Returns list of alert dicts: {type, severity, message}
    """
    alerts = []

    # 1. Daily drop — compare last two snapshots
    if len(snapshots) >= 2:
        today_val = float(snapshots[-1].get("total_value_base") or 0)
        prev_val = float(snapshots[-2].get("total_value_base") or 0)
        if prev_val > 0:
            daily_ret = (today_val - prev_val) / prev_val
            if daily_ret < DAILY_DROP_THRESHOLD:
                alerts.append({
                    "type": "daily_drop",
                    "severity": "critical" if daily_ret < DAILY_DROP_THRESHOLD * 1.5 else "warning",
                    "message": f"El portafolio cayó {daily_ret:.2%} hoy ({_sign(today_val - prev_val)}{today_val - prev_val:,.2f} USD).",
                })

    # 2. Max drawdown breach
    max_dd = metrics.get("max_drawdown") or 0.0
    if max_dd < DRAWDOWN_THRESHOLD:
        alerts.append({
            "type": "drawdown",
            "severity": "critical" if max_dd < DRAWDOWN_THRESHOLD * 1.5 else "warning",
            "message": f"Max drawdown en {max_dd:.2%} — por debajo del umbral de {DRAWDOWN_THRESHOLD:.0%}.",
        })

    # 3. Individual position losses
    for row in summary.rows:
        pnl_pct = (row.unrealized_pnl_pct or 0.0) / 100.0
        if pnl_pct < POSITION_LOSS_THRESHOLD:
            alerts.append({
                "type": "position_loss",
                "severity": "warning",
                "message": f"{row.ticker} acumula {pnl_pct:.2%} de pérdida no realizada ({_sign(row.unrealized_pnl or 0)}{row.unrealized_pnl or 0:,.2f} USD).",
            })

    return alerts


def build_alert_message(alerts: list[dict], summary, base_currency: str = "USD") -> str:
    from datetime import datetime
    import pytz
    now = datetime.now(pytz.timezone("America/Bogota"))
    total = summary.total_value_base

    emoji_map = {"critical": "🚨", "warning": "⚠️"}
    lines = [
        "<b>PORTAFOLIO MANAGEMENT SA — ALERTAS</b>",
        f"📅 {now.strftime('%Y-%m-%d %H:%M')} Colombia",
        f"💼 Portfolio: <b>{base_currency} {total:,.2f}</b>",
        "",
    ]
    for a in alerts:
        emoji = emoji_map.get(a["severity"], "ℹ️")
        label = a["severity"].upper()
        lines.append(f"{emoji} <b>[{label}]</b> {a['message']}")

    return "\n".join(lines)


def send_alerts_if_needed(summary, metrics: dict, snapshots: list[dict], base_currency: str = "USD") -> bool:
    """Check conditions and send Telegram alerts if any triggered. Returns True if alerts sent."""
    alerts = check_alerts(summary, metrics, snapshots)
    if not alerts:
        log.info("Alerts check: no conditions triggered.")
        return False

    from app.services.telegram_service import send_message
    text = build_alert_message(alerts, summary, base_currency)
    ok = send_message(text)
    log.info("Sent %d alert(s) via Telegram: %s", len(alerts), ok)
    return ok
