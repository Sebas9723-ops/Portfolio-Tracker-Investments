"""
Telegram notification service.

Sends daily portfolio snapshots and alert messages via the Telegram Bot API.
Credentials are read from Settings (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID env vars).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional

import pytz

from app.config import get_settings

_COLOMBIA_TZ = pytz.timezone("America/Bogota")


# ── Low-level sender ──────────────────────────────────────────────────────────

def _post(bot_token: str, method: str, payload: dict) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except urllib.error.URLError as exc:
        import logging
        logging.getLogger(__name__).warning("Telegram request failed: %s", exc)
        return False


def send_message(text: str, bot_token: str = "", chat_id: str = "") -> bool:
    """Send an HTML-formatted text message. Falls back to settings if creds not provided."""
    settings = get_settings()
    token = bot_token or settings.TELEGRAM_BOT_TOKEN
    cid = chat_id or settings.TELEGRAM_CHAT_ID
    if not token or not cid:
        return False
    return _post(token, "sendMessage", {
        "chat_id": cid,
        "text": text,
        "parse_mode": "HTML",
    })


# ── Message builders ──────────────────────────────────────────────────────────

def _sign(v: float) -> str:
    return "+" if v >= 0 else ""


def build_snapshot_messages(
    summary,           # PortfolioSummary from portfolio_builder
    metrics: dict,     # output of compute_extended_ratios
    base_currency: str = "USD",
    benchmark_ticker: str = "VOO",
    benchmark_cum: Optional[float] = None,
) -> list[str]:
    """
    Build a list of Telegram HTML messages for the daily portfolio snapshot.
    Split across multiple messages to respect Telegram's 4096-char limit.
    """
    now_col = datetime.now(_COLOMBIA_TZ)
    total = summary.total_value_base
    invested = summary.total_invested_base or 0.0
    pnl = summary.total_unrealized_pnl or 0.0
    pnl_pct = summary.total_unrealized_pnl_pct or 0.0
    day_change = summary.total_day_change_base or 0.0

    sharpe = metrics.get("sharpe") or 0.0
    sortino = metrics.get("sortino") or 0.0
    ann_vol = (metrics.get("annualized_vol") or 0.0) * 100
    max_dd = (metrics.get("max_drawdown") or 0.0) * 100
    alpha = (metrics.get("alpha") or 0.0) * 100
    beta = metrics.get("beta") or 0.0
    info_ratio = metrics.get("information_ratio") or 0.0
    ann_return = (metrics.get("annualized_return") or 0.0) * 100
    twr = metrics.get("twr") or 0.0

    summary_lines = [
        "<b>PORTAFOLIO MANAGEMENT SA</b>",
        f"📅 {now_col.strftime('%Y-%m-%d %H:%M')} Colombia",
        "",
        "<b>📊 PORTFOLIO SUMMARY</b>",
        f"💼 Total:              <code>{base_currency} {total:>14,.2f}</code>",
        f"   Invested Capital:  <code>{base_currency} {invested:>14,.2f}</code>",
        f"   Unrealized PnL:    <code>{_sign(pnl)}{pnl:>14,.2f} ({_sign(pnl_pct)}{pnl_pct:.2f}%)</code>",
        f"   Today's Change:    <code>{_sign(day_change)}{day_change:>14,.2f}</code>",
        "",
        "<b>📈 PERFORMANCE METRICS</b>",
        f"   TWR (total):       <code>{_sign(twr)}{twr:.2f}%</code>",
        f"   Ann. Return:       <code>{_sign(ann_return)}{ann_return:.2f}%</code>",
        f"   Ann. Volatility:   <code>{ann_vol:.2f}%</code>",
        f"   Sharpe Ratio:      <code>{sharpe:.4f}</code>",
        f"   Sortino Ratio:     <code>{sortino:.4f}</code>",
        f"   Max Drawdown:      <code>{max_dd:.2f}%</code>",
        f"   Alpha vs {benchmark_ticker}:    <code>{_sign(alpha)}{alpha:.2f}%</code>",
        f"   Beta:              <code>{beta:.4f}</code>",
        f"   Info Ratio:        <code>{info_ratio:.4f}</code>",
    ]
    if benchmark_cum is not None:
        bm_pct = benchmark_cum * 100
        excess = twr - bm_pct
        summary_lines.append(f"   {benchmark_ticker} (cumul):      <code>{_sign(bm_pct)}{bm_pct:.2f}%</code>")
        summary_lines.append(f"   Excess vs {benchmark_ticker}:   <code>{_sign(excess)}{excess:.2f}%</code>")

    messages = ["\n".join(summary_lines)]

    # Holdings table
    rows_data = summary.rows
    if rows_data:
        header = f"{'Ticker':<8} {'Shares':>8} {'Price':>10} {'Value':>12} {'Wt%':>6} {'PnL%':>7}"
        separator = "─" * len(header)
        table_rows = [header, separator]
        for r in rows_data:
            ticker = r.ticker[:8]
            shares = r.shares
            price = r.price_native
            value = r.value_base
            weight = r.weight
            pnl_r = r.unrealized_pnl_pct or 0.0
            table_rows.append(
                f"{ticker:<8} {shares:>8.2f} {price:>10,.2f} {value:>12,.0f} {weight:>5.1f}% {pnl_r:>+6.1f}%"
            )
        hold_msg = "<b>📋 HOLDINGS</b>\n<pre>" + "\n".join(table_rows) + "</pre>"
        messages.append(hold_msg)

    return messages


# ── High-level daily report ───────────────────────────────────────────────────

def send_daily_report(
    summary,
    metrics: dict,
    base_currency: str = "USD",
    benchmark_ticker: str = "VOO",
    benchmark_cum: Optional[float] = None,
    bot_token: str = "",
    chat_id: str = "",
) -> bool:
    """Build and send the full daily portfolio report to Telegram."""
    settings = get_settings()
    token = bot_token or settings.TELEGRAM_BOT_TOKEN
    cid = chat_id or settings.TELEGRAM_CHAT_ID
    if not token or not cid:
        return False

    messages = build_snapshot_messages(summary, metrics, base_currency, benchmark_ticker, benchmark_cum)
    ok = True
    for text in messages:
        ok = ok and _post(token, "sendMessage", {
            "chat_id": cid,
            "text": text,
            "parse_mode": "HTML",
        })
    return ok
