"""
Portfolio alert system.

Checks drawdown, weight deviation, and daily drop thresholds on every app load.
Sends a Telegram message when conditions are triggered (max once per day per condition).
Tracks sent alerts in Google Sheets tab 'alerts_log'.

Requires in .streamlit/secrets.toml:
    [telegram]
    bot_token = "xxxx:yyyy"
    chat_id   = "123456789"

Optional secrets (defaults apply if absent):
    [alerts]
    drawdown_threshold         = -0.10
    weight_deviation_threshold = 0.05
    daily_drop_threshold       = -0.03
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from datetime import datetime

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
    try:
        from app_core import _get_private_positions_sheet_locator, _get_worksheet_records_cached
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
    except Exception as e:
        st.warning(f"⚠️ Failed to log alert to Sheets: {e}")


# ── Condition checks ───────────────────────────────────────────────────────────

def _get_threshold(key: str, default: float) -> float:
    try:
        return float(st.secrets.get("alerts", {}).get(key, default))
    except Exception:
        return default


def check_alert_conditions(ctx: dict) -> list[dict]:
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

    sent_session = st.session_state.get("alerts_sent_session", set())
    new_alerts = [a for a in alerts if a["type"] not in sent_session]
    if not new_alerts:
        return False

    sent_today = _alerts_sent_today([a["type"] for a in new_alerts])
    truly_new = [a for a in new_alerts if a["type"] not in sent_today]
    if not truly_new:
        st.session_state["alerts_sent_session"] = sent_session | sent_today
        return False

    alerts.clear()
    alerts.extend(truly_new)
    return True


# ── Telegram sender ────────────────────────────────────────────────────────────

def _build_telegram_message(alerts: list[dict], ctx: dict) -> str:
    now_col = datetime.now(_COLOMBIA_TZ)
    ccy = ctx.get("base_currency", "USD")
    total = float(ctx.get("total_portfolio_value", 0.0))

    emoji_map = {"critical": "🚨", "warning": "⚠️"}
    lines = [
        f"<b>PORTAFOLIO MANAGEMENT SA</b>",
        f"📅 {now_col.strftime('%Y-%m-%d %H:%M')} Colombia",
        f"💼 Portfolio: <b>{ccy} {total:,.2f}</b>",
        "",
    ]

    for a in alerts:
        emoji = emoji_map.get(a["severity"], "ℹ️")
        label = a["severity"].upper()
        lines.append(f"{emoji} <b>[{label}]</b> {a['message']}")

    return "\n".join(lines)


def send_alert_telegram(alerts: list[dict], ctx: dict):
    tg = st.secrets.get("telegram", {})
    bot_token = str(tg.get("bot_token", "")).strip()
    chat_id = str(tg.get("chat_id", "")).strip()

    if not bot_token or not chat_id:
        return

    text = _build_telegram_message(alerts, ctx)
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)

        _mark_alerts_sent(alerts)
        sent_session = st.session_state.get("alerts_sent_session", set())
        st.session_state["alerts_sent_session"] = sent_session | {a["type"] for a in alerts}
    except Exception as e:
        st.warning(f"⚠️ Failed to send alert via Telegram: {e}")


# ── Portfolio snapshot sender ──────────────────────────────────────────────────

def _build_portfolio_snapshot_messages(ctx: dict) -> list[str]:
    """Build Telegram messages for a full portfolio snapshot (split to respect 4096-char limit)."""
    now_col = datetime.now(_COLOMBIA_TZ)
    ccy = ctx.get("base_currency", "USD")
    df = ctx.get("df", pd.DataFrame()).copy()

    total_portfolio = float(ctx.get("total_portfolio_value", 0.0))
    holdings_value = float(ctx.get("holdings_value", 0.0))
    cash_total = float(ctx.get("cash_total_value", 0.0))
    invested_capital = float(ctx.get("invested_capital", 0.0))
    unrealized_pnl = float(ctx.get("unrealized_pnl", 0.0))
    total_return = float(ctx.get("total_return", 0.0))
    volatility = float(ctx.get("volatility", 0.0))
    sharpe = float(ctx.get("sharpe", 0.0))
    max_drawdown = float(ctx.get("max_drawdown", 0.0))
    alpha = float(ctx.get("alpha", 0.0))
    beta = float(ctx.get("beta", 0.0))
    tracking_error = float(ctx.get("tracking_error", 0.0))
    information_ratio = float(ctx.get("information_ratio", 0.0))
    benchmark_cum = ctx.get("benchmark_cum_return")
    excess = ctx.get("excess_vs_benchmark")

    pnl_sign = "+" if unrealized_pnl >= 0 else ""

    summary_lines = [
        "<b>PORTAFOLIO MANAGEMENT SA</b>",
        f"📅 {now_col.strftime('%Y-%m-%d %H:%M')} Colombia",
        "",
        "<b>📊 PORTFOLIO SUMMARY</b>",
        f"💼 Total:             <code>{ccy} {total_portfolio:>14,.2f}</code>",
        f"   Holdings:          <code>{ccy} {holdings_value:>14,.2f}</code>",
        f"   Cash:              <code>{ccy} {cash_total:>14,.2f}</code>",
        f"   Invested Capital:  <code>{ccy} {invested_capital:>14,.2f}</code>",
        f"   Unrealized PnL:    <code>{pnl_sign}{unrealized_pnl:>14,.2f}</code>",
        "",
        "<b>📈 PERFORMANCE METRICS</b>",
        f"   Total Return:      <code>{total_return * 100:>+.2f}%</code>",
        f"   Ann. Volatility:   <code>{volatility * 100:.2f}%</code>",
        f"   Sharpe Ratio:      <code>{sharpe:.4f}</code>",
        f"   Max Drawdown:      <code>{max_drawdown * 100:.2f}%</code>",
        f"   Alpha:             <code>{alpha * 100:>+.2f}%</code>",
        f"   Beta:              <code>{beta:.4f}</code>",
        f"   Tracking Error:    <code>{tracking_error * 100:.2f}%</code>",
        f"   Info Ratio:        <code>{information_ratio:.4f}</code>",
    ]
    if benchmark_cum is not None:
        summary_lines.append(f"   VOO Benchmark:     <code>{float(benchmark_cum) * 100:>+.2f}%</code>")
    if excess is not None:
        summary_lines.append(f"   Excess vs VOO:     <code>{float(excess) * 100:>+.2f}%</code>")

    messages = ["\n".join(summary_lines)]

    # Holdings table (uses <pre> for monospace alignment)
    if not df.empty:
        header = f"{'Ticker':<8} {'Shares':>8} {'Price':>10} {'Value':>12} {'Wt%':>6} {'PnL%':>7}"
        separator = "─" * len(header)
        rows = [header, separator]
        for _, row in df.iterrows():
            ticker = str(row.get("Ticker", ""))[:8]
            shares = float(row.get("Shares", 0))
            price = float(row.get("Price", 0))
            value = float(row.get("Value", 0))
            weight = float(row.get("Weight %", 0))
            unreal_pct = float(row.get("Unrealized PnL %", 0))
            rows.append(
                f"{ticker:<8} {shares:>8.2f} {price:>10,.2f} {value:>12,.0f} {weight:>5.1f}% {unreal_pct:>+6.1f}%"
            )
        hold_msg = "<b>📋 HOLDINGS</b>\n<pre>" + "\n".join(rows) + "</pre>"
        messages.append(hold_msg)

    # Dividends (appended to last message if short enough, else separate)
    estimated_annual = ctx.get("estimated_annual_dividends", 0.0)
    dividends_ytd = ctx.get("dividends_ytd", 0.0)
    if estimated_annual and float(estimated_annual) > 0:
        div_lines = [
            "",
            "<b>💰 DIVIDENDS</b>",
            f"   Est. Annual:    <code>{ccy} {float(estimated_annual):>12,.2f}</code>",
            f"   YTD Collected:  <code>{ccy} {float(dividends_ytd):>12,.2f}</code>",
        ]
        div_text = "\n".join(div_lines)
        if len(messages[-1]) + len(div_text) < 4000:
            messages[-1] += div_text
        else:
            messages.append(div_text.strip())

    return messages


def send_portfolio_snapshot_telegram(ctx: dict) -> bool:
    """Send current portfolio snapshot via Telegram. Returns True on success."""
    tg = st.secrets.get("telegram", {})
    bot_token = str(tg.get("bot_token", "")).strip()
    chat_id = str(tg.get("chat_id", "")).strip()

    if not bot_token or not chat_id:
        return False

    messages = _build_portfolio_snapshot_messages(ctx)
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    for text in messages:
        payload = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            return False

    return True
