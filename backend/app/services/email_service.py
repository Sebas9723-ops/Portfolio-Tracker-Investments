"""
Simple SMTP email service for drift alerts.
Reads SMTP config from environment variables:
  EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASSWORD, EMAIL_FROM
Falls back to Sendgrid if EMAIL_PROVIDER=sendgrid is set.
"""
from __future__ import annotations
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger(__name__)


def _smtp_config() -> tuple[str, int, str, str, str]:
    """Read SMTP settings fresh from env each call (safe for Render cold starts)."""
    host     = os.getenv("EMAIL_HOST", "")
    port     = int(os.getenv("EMAIL_PORT", "587"))
    user     = os.getenv("EMAIL_USER", "")
    password = os.getenv("EMAIL_PASSWORD", "")
    from_    = os.getenv("EMAIL_FROM", user)
    return host, port, user, password, from_


def send_email(to: str, subject: str, body_html: str) -> bool:
    """
    Send an HTML email via SMTP.
    Returns True on success, False on failure.
    Silently skips if SMTP credentials are not configured.
    """
    host, port, user, password, from_ = _smtp_config()
    if not host or not user or not password:
        log.warning("Email not configured (HOST=%r USER=%r) — skipping send to %s", host, user, to)
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = from_
        msg["To"]      = to
        msg.attach(MIMEText(body_html, "html"))

        log.info("SMTP connecting to %s:%s as %s", host, port, user)
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=25) as server:
                server.login(user, password)
                server.sendmail(from_, [to], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=25) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(user, password)
                server.sendmail(from_, [to], msg.as_string())
        log.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as exc:
        log.error("Failed to send email to %s: %s", to, exc)
        return False


def send_weekly_report_email(
    to: str,
    summary,
    metrics: dict,
    base_currency: str = "USD",
    benchmark_ticker: str = "VOO",
    benchmark_cum: float | None = None,
    momentum: dict | None = None,
    fear_greed: dict | None = None,
    week_change_pct: float | None = None,
    ai_analysis: str | None = None,
) -> bool:
    """Send the weekly portfolio report as an HTML email."""
    from datetime import datetime
    import pytz

    now = datetime.now(pytz.timezone("America/Bogota"))
    total = summary.total_value_base
    invested = summary.total_invested_base or 0.0
    pnl = summary.total_unrealized_pnl or 0.0
    pnl_pct = summary.total_unrealized_pnl_pct or 0.0

    def _sign(v: float) -> str:
        return "+" if v >= 0 else ""

    def _pct(v: float | None) -> str:
        if v is None:
            return "N/A"
        return f"{_sign(v)}{v:.2f}%"

    sharpe     = metrics.get("sharpe") or 0.0
    sortino    = metrics.get("sortino") or 0.0
    ann_vol    = (metrics.get("annualized_vol") or 0.0) * 100
    max_dd     = (metrics.get("max_drawdown") or 0.0) * 100
    alpha      = (metrics.get("alpha") or 0.0) * 100
    beta       = metrics.get("beta") or 0.0
    twr        = metrics.get("twr") or 0.0
    ann_return = (metrics.get("annualized_return") or 0.0) * 100

    # --- Benchmark row ---
    bm_html = ""
    if benchmark_cum is not None:
        bm_pct = benchmark_cum * 100
        excess = twr - bm_pct
        bm_html = f"""
        <tr><td style='padding:3px 8px;color:#6b7280'>{benchmark_ticker} (cumul.)</td>
            <td style='padding:3px 8px;text-align:right;color:#e2e8f0'>{_pct(bm_pct)}</td></tr>
        <tr><td style='padding:3px 8px;color:#6b7280'>Excess vs {benchmark_ticker}</td>
            <td style='padding:3px 8px;text-align:right;color:{"#4dff4d" if excess >= 0 else "#ff4d4d"}'>{_pct(excess)}</td></tr>
        """

    # --- Week change row ---
    week_html = ""
    if week_change_pct is not None:
        color = "#4dff4d" if week_change_pct >= 0 else "#ff4d4d"
        week_html = f"<tr><td style='padding:3px 8px;color:#6b7280'>Week Change</td><td style='padding:3px 8px;text-align:right;color:{color}'>{_pct(week_change_pct)}</td></tr>"

    # --- Fear & Greed row ---
    fg_html = ""
    if fear_greed and fear_greed.get("score") is not None:
        fg_html = f"<tr><td style='padding:3px 8px;color:#6b7280'>Fear &amp; Greed</td><td style='padding:3px 8px;text-align:right;color:#e2e8f0'>{fear_greed['score']}/100 — {fear_greed.get('rating','')}</td></tr>"

    # --- Momentum table ---
    mom_html = ""
    if momentum and summary.rows:
        mom_rows = ""
        for r in sorted(summary.rows, key=lambda x: x.weight, reverse=True):
            t = r.ticker
            tm = momentum.get(t, {})
            def _m(v):
                if v is None:
                    return "<td style='padding:2px 6px;text-align:right;color:#4b5563'>N/A</td>"
                color = "#4dff4d" if v >= 0 else "#ff4d4d"
                return f"<td style='padding:2px 6px;text-align:right;color:{color}'>{_sign(v)}{v:.1f}%</td>"
            mom_rows += f"<tr><td style='padding:2px 6px;color:#f3a712;font-weight:bold'>{t}</td>{_m(tm.get('1w'))}{_m(tm.get('1m'))}{_m(tm.get('3m'))}{_m(tm.get('6m'))}{_m(tm.get('1y'))}<td style='padding:2px 6px;text-align:right;color:#e2e8f0'>{r.weight:.1f}%</td></tr>"
        mom_html = f"""
        <h3 style='color:#f3a712;margin-top:24px'>Momentum Analysis</h3>
        <table style='border-collapse:collapse;width:100%;font-size:11px'>
          <thead><tr style='color:#6b7280;border-bottom:1px solid #1e2530'>
            <th style='text-align:left;padding:2px 6px'>Ticker</th>
            <th style='text-align:right;padding:2px 6px'>1W</th>
            <th style='text-align:right;padding:2px 6px'>1M</th>
            <th style='text-align:right;padding:2px 6px'>3M</th>
            <th style='text-align:right;padding:2px 6px'>6M</th>
            <th style='text-align:right;padding:2px 6px'>1Y</th>
            <th style='text-align:right;padding:2px 6px'>Wt%</th>
          </tr></thead>
          <tbody>{mom_rows}</tbody>
        </table>"""

    # --- Holdings table ---
    holdings_rows = ""
    for r in summary.rows:
        pnl_r = r.unrealized_pnl_pct or 0.0
        pnl_color = "#4dff4d" if pnl_r >= 0 else "#ff4d4d"
        holdings_rows += (
            f"<tr>"
            f"<td style='padding:3px 8px;color:#f3a712;font-weight:bold'>{r.ticker}</td>"
            f"<td style='padding:3px 8px;text-align:right'>{r.shares:.2f}</td>"
            f"<td style='padding:3px 8px;text-align:right'>{r.price_native:,.2f}</td>"
            f"<td style='padding:3px 8px;text-align:right'>{r.value_base:,.0f}</td>"
            f"<td style='padding:3px 8px;text-align:right'>{r.weight:.1f}%</td>"
            f"<td style='padding:3px 8px;text-align:right;color:{pnl_color}'>{_sign(pnl_r)}{pnl_r:.1f}%</td>"
            f"</tr>"
        )

    # --- AI block ---
    ai_html = ""
    if ai_analysis:
        import html as _html
        safe = _html.escape(ai_analysis)
        ai_html = f"""
        <h3 style='color:#f3a712;margin-top:24px'>AI Weekly Analysis</h3>
        <div style='background:#111827;padding:16px;border-left:3px solid #f3a712;white-space:pre-wrap;font-size:12px;color:#d1d5db'>{safe}</div>
        """

    body = f"""
    <html><body style='background:#0b0f14;color:#e2e8f0;font-family:IBM Plex Mono,monospace;padding:24px;max-width:700px;margin:0 auto'>
      <h1 style='color:#f3a712;font-size:16px;margin-bottom:4px'>⚡ Weekly Portfolio Report</h1>
      <p style='color:#6b7280;font-size:11px;margin-top:0'>{now.strftime('%Y-%m-%d')} | Portfolio Management SA</p>

      <h3 style='color:#f3a712;margin-top:20px'>Portfolio Summary</h3>
      <table style='border-collapse:collapse;width:100%'>
        <tr><td style='padding:3px 8px;color:#6b7280'>Total Value</td>
            <td style='padding:3px 8px;text-align:right;color:#e2e8f0;font-weight:bold'>{base_currency} {total:,.2f}</td></tr>
        <tr><td style='padding:3px 8px;color:#6b7280'>Invested Capital</td>
            <td style='padding:3px 8px;text-align:right;color:#e2e8f0'>{base_currency} {invested:,.2f}</td></tr>
        <tr><td style='padding:3px 8px;color:#6b7280'>Unrealized P&amp;L</td>
            <td style='padding:3px 8px;text-align:right;color:{"#4dff4d" if pnl >= 0 else "#ff4d4d"}'>{_sign(pnl)}{pnl:,.2f} ({_sign(pnl_pct)}{pnl_pct:.2f}%)</td></tr>
        {week_html}
      </table>

      <h3 style='color:#f3a712;margin-top:24px'>Risk &amp; Return (trailing 1Y)</h3>
      <table style='border-collapse:collapse;width:100%'>
        <tr><td style='padding:3px 8px;color:#6b7280'>TWR</td><td style='padding:3px 8px;text-align:right;color:#e2e8f0'>{_pct(twr)}</td></tr>
        <tr><td style='padding:3px 8px;color:#6b7280'>Ann. Return</td><td style='padding:3px 8px;text-align:right;color:#e2e8f0'>{_pct(ann_return)}</td></tr>
        <tr><td style='padding:3px 8px;color:#6b7280'>Ann. Volatility</td><td style='padding:3px 8px;text-align:right;color:#e2e8f0'>{ann_vol:.2f}%</td></tr>
        <tr><td style='padding:3px 8px;color:#6b7280'>Sharpe</td><td style='padding:3px 8px;text-align:right;color:#e2e8f0'>{sharpe:.4f}</td></tr>
        <tr><td style='padding:3px 8px;color:#6b7280'>Sortino</td><td style='padding:3px 8px;text-align:right;color:#e2e8f0'>{sortino:.4f}</td></tr>
        <tr><td style='padding:3px 8px;color:#6b7280'>Max Drawdown</td><td style='padding:3px 8px;text-align:right;color:#ff4d4d'>{max_dd:.2f}%</td></tr>
        <tr><td style='padding:3px 8px;color:#6b7280'>Alpha vs {benchmark_ticker}</td><td style='padding:3px 8px;text-align:right;color:{"#4dff4d" if alpha >= 0 else "#ff4d4d"}'>{_pct(alpha)}</td></tr>
        <tr><td style='padding:3px 8px;color:#6b7280'>Beta</td><td style='padding:3px 8px;text-align:right;color:#e2e8f0'>{beta:.4f}</td></tr>
        {bm_html}
        {fg_html}
      </table>

      {mom_html}

      <h3 style='color:#f3a712;margin-top:24px'>Holdings</h3>
      <table style='border-collapse:collapse;width:100%;font-size:11px'>
        <thead><tr style='color:#6b7280;border-bottom:1px solid #1e2530'>
          <th style='text-align:left;padding:3px 8px'>Ticker</th>
          <th style='text-align:right;padding:3px 8px'>Shares</th>
          <th style='text-align:right;padding:3px 8px'>Price</th>
          <th style='text-align:right;padding:3px 8px'>Value</th>
          <th style='text-align:right;padding:3px 8px'>Wt%</th>
          <th style='text-align:right;padding:3px 8px'>PnL%</th>
        </tr></thead>
        <tbody>{holdings_rows}</tbody>
      </table>

      {ai_html}

      <p style='color:#4b5563;font-size:10px;margin-top:32px;border-top:1px solid #1e2530;padding-top:12px'>
        Portfolio Management SA — automated weekly report. Do not reply to this email.
      </p>
    </body></html>
    """
    return send_email(to, f"⚡ Weekly Portfolio Report — {now.strftime('%Y-%m-%d')}", body)


def send_drift_alert(
    to: str,
    drifts: list[dict],
    portfolio_value: float,
    base_currency: str = "USD",
) -> bool:
    """
    Send a portfolio drift alert email.
    drifts: list of {ticker, current_pct, target_pct, drift_pct}
    """
    rows_html = "".join(
        f"<tr>"
        f"<td style='padding:4px 8px;font-weight:bold;color:#f3a712'>{d['ticker']}</td>"
        f"<td style='padding:4px 8px;text-align:right'>{d['current_pct']:.1f}%</td>"
        f"<td style='padding:4px 8px;text-align:right'>{d['target_pct']:.1f}%</td>"
        f"<td style='padding:4px 8px;text-align:right;color:{'#ff4d4d' if d['drift_pct'] < 0 else '#4dff4d'}'>"
        f"{'+' if d['drift_pct'] > 0 else ''}{d['drift_pct']:.1f}%</td>"
        f"</tr>"
        for d in drifts
    )
    body = f"""
    <html><body style='background:#0b0f14;color:#e2e8f0;font-family:IBM Plex Mono,monospace;padding:24px'>
      <h2 style='color:#f3a712'>Portfolio Drift Alert</h2>
      <p style='color:#6b7280'>Portfolio Value: <strong style='color:#e2e8f0'>{base_currency} {portfolio_value:,.2f}</strong></p>
      <p style='color:#6b7280'>The following positions have drifted beyond your threshold:</p>
      <table style='border-collapse:collapse;width:100%;margin-top:12px'>
        <thead>
          <tr style='border-bottom:1px solid #1e2530;color:#6b7280;font-size:11px'>
            <th style='text-align:left;padding:4px 8px'>Ticker</th>
            <th style='text-align:right;padding:4px 8px'>Current</th>
            <th style='text-align:right;padding:4px 8px'>Target</th>
            <th style='text-align:right;padding:4px 8px'>Drift</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      <p style='color:#6b7280;margin-top:20px;font-size:11px'>
        Log in to your portfolio tracker to take action.
      </p>
    </body></html>
    """
    return send_email(to, "⚠️ Portfolio Drift Alert — Action Required", body)
