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

_HOST     = os.getenv("EMAIL_HOST", "")
_PORT     = int(os.getenv("EMAIL_PORT", "587"))
_USER     = os.getenv("EMAIL_USER", "")
_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
_FROM     = os.getenv("EMAIL_FROM", _USER)


def send_email(to: str, subject: str, body_html: str) -> bool:
    """
    Send an HTML email via SMTP.
    Returns True on success, False on failure.
    Silently skips if SMTP credentials are not configured.
    """
    if not _HOST or not _USER or not _PASSWORD:
        log.warning("Email not configured — skipping send to %s", to)
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = _FROM
        msg["To"]      = to
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(_HOST, _PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(_USER, _PASSWORD)
            server.sendmail(_FROM, [to], msg.as_string())
        log.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as exc:
        log.error("Failed to send email to %s: %s", to, exc)
        return False


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
