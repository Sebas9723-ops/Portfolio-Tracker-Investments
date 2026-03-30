"""
Monthly portfolio email report.

Sends an HTML email on the 27th of each month (or first app load after).
Tracks sent reports in Google Sheets tab 'reports_log' to avoid duplicates.

Requires in .streamlit/secrets.toml:
    [email]
    smtp_host    = "smtp.gmail.com"
    smtp_port    = 587
    sender       = "you@gmail.com"
    app_password = "xxxx xxxx xxxx xxxx"
    recipient    = "you@gmail.com"
"""
from __future__ import annotations

import io
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import numpy as np
import pandas as pd
import pytz
import streamlit as st

_COLOMBIA_TZ = pytz.timezone("America/Bogota")
_REPORT_DAY = 27
_REPORTS_HEADERS = ["month", "sent_at", "status"]


# ── Google Sheets tracking ─────────────────────────────────────────────────────

def _connect_reports_log():
    from app_core import _get_spreadsheet, _connect_named_worksheet
    return _connect_named_worksheet("reports_log", _REPORTS_HEADERS)


def _report_sent_this_month(month_str: str) -> bool:
    try:
        from app_core import _get_spreadsheet_cached, _get_private_positions_sheet_locator, _get_worksheet_records_cached
        sheet_id, sheet_url = _get_private_positions_sheet_locator()
        records = _get_worksheet_records_cached(sheet_id, sheet_url, "reports_log")
        return any(str(r.get("month", "")).strip() == month_str for r in records)
    except Exception:
        return False


def _mark_report_sent(month_str: str):
    try:
        ws = _connect_reports_log()
        ws.append_row(
            [month_str, datetime.now(_COLOMBIA_TZ).isoformat(timespec="seconds"), "sent"],
            value_input_option="RAW",
        )
        from app_core import _clear_google_sheets_cache
        _clear_google_sheets_cache()
    except Exception:
        pass


# ── Trigger logic ──────────────────────────────────────────────────────────────

def should_send_monthly_report(ctx: dict) -> tuple[bool, str]:
    """Returns (should_send, month_str)."""
    if ctx.get("app_scope") != "private" or not ctx.get("authenticated"):
        return False, ""

    now_col = datetime.now(_COLOMBIA_TZ)
    if now_col.day < _REPORT_DAY:
        return False, ""

    month_str = now_col.strftime("%Y-%m")

    # Avoid resending in the same session
    if st.session_state.get("monthly_report_sent") == month_str:
        return False, ""

    if _report_sent_this_month(month_str):
        st.session_state["monthly_report_sent"] = month_str
        return False, ""

    return True, month_str


# ── HTML builder ───────────────────────────────────────────────────────────────

def _pct(v) -> str:
    try:
        return f"{float(v):.2f}%"
    except Exception:
        return "—"


def _val(v, ccy="") -> str:
    try:
        return f"{ccy} {float(v):,.2f}".strip()
    except Exception:
        return "—"


def build_monthly_report_html(ctx: dict) -> str:
    now_col = datetime.now(_COLOMBIA_TZ)
    month_label = now_col.strftime("%B %Y")
    ccy = ctx.get("base_currency", "USD")
    df: pd.DataFrame = ctx.get("df", pd.DataFrame()).copy()

    total_portfolio = ctx.get("total_portfolio_value", 0.0)
    holdings_value = ctx.get("holdings_value", 0.0)
    cash_total = ctx.get("cash_total_value", 0.0)
    invested_capital = ctx.get("invested_capital", 0.0)
    unrealized_pnl = ctx.get("unrealized_pnl", 0.0)
    total_return = ctx.get("total_return", 0.0)
    volatility = ctx.get("volatility", 0.0)
    sharpe = ctx.get("sharpe", 0.0)
    max_drawdown = ctx.get("max_drawdown", 0.0)
    alpha = ctx.get("alpha", 0.0)
    beta = ctx.get("beta", 0.0)
    tracking_error = ctx.get("tracking_error", 0.0)
    information_ratio = ctx.get("information_ratio", 0.0)
    benchmark_cum = ctx.get("benchmark_cum_return")
    excess = ctx.get("excess_vs_benchmark")

    # Max Sharpe allocation
    max_sharpe_row = ctx.get("max_sharpe_row")
    usable = ctx.get("usable", [])
    max_sharpe_map: dict[str, float] = {}
    if max_sharpe_row is not None and usable:
        arr = np.array(max_sharpe_row["Weights"], dtype=float)
        if len(arr) == len(usable):
            for t, w in zip(usable, arr):
                max_sharpe_map[t] = float(w)

    # Portfolio snapshot from latest snapshot in Sheets (for MoM)
    mom_section = ""
    try:
        from pages_app.portfolio_history import load_portfolio_snapshots, filter_snapshots_for_context, build_monthly_snapshot_summary
        snaps = load_portfolio_snapshots()
        if not snaps.empty:
            filtered = filter_snapshots_for_context(snaps, ctx.get("mode"), ccy)
            monthly_df = build_monthly_snapshot_summary(filtered)
            if not monthly_df.empty and len(monthly_df) >= 1:
                last = monthly_df.iloc[0]
                mom_section = f"""
                <tr><td style="{_td}">Month-over-Month Change</td>
                    <td style="{_td_r}">{_val(last.get('MoM Change'), ccy)}</td></tr>
                <tr><td style="{_td}">MoM Change %</td>
                    <td style="{_td_r}">{_pct(last.get('MoM Change %'))}</td></tr>
                """
    except Exception:
        pass

    # Stress test summary
    stress_section = ""
    stress_df: pd.DataFrame = ctx.get("stress_df", pd.DataFrame())
    stress_pnl = ctx.get("stress_pnl", 0.0)
    stress_return = ctx.get("stress_return", 0.0)
    if not stress_df.empty:
        stress_rows = ""
        for _, row in stress_df.iterrows():
            stress_rows += f"""
            <tr>
                <td style="{_td}">{row['Ticker']}</td>
                <td style="{_td_r}">{_val(row.get('Current Value'), ccy)}</td>
                <td style="{_td_r}">{_val(row.get('Stressed Value'), ccy)}</td>
            </tr>"""
        stress_section = f"""
        <h2 style="color:#f3a712;font-family:monospace;margin-top:32px">STRESS TEST (−10% Equity / −3% Bonds / +5% Gold)</h2>
        <table style="{_table}">
            <tr>
                <th style="{_th}">Ticker</th>
                <th style="{_th}">Current Value</th>
                <th style="{_th}">Stressed Value</th>
            </tr>
            {stress_rows}
        </table>
        <p style="color:#e6e6e6;font-family:monospace">
            Portfolio stress P&amp;L: <b>{_val(stress_pnl, ccy)}</b> ({_pct(stress_return * 100)})
        </p>"""

    # Holdings rows
    holding_rows = ""
    if not df.empty:
        for _, row in df.iterrows():
            ticker = str(row.get("Ticker", ""))
            name = str(row.get("Name", ""))
            shares = row.get("Shares", 0)
            price = row.get("Price", 0)
            value = row.get("Value", 0)
            weight = row.get("Weight %", 0)
            unrealized = row.get("Unrealized PnL", 0)
            unrealized_pct = row.get("Unrealized PnL %", 0)
            ms_weight = max_sharpe_map.get(ticker, 0.0) * 100
            color = "#4caf50" if float(unrealized) >= 0 else "#f44336"
            holding_rows += f"""
            <tr>
                <td style="{_td}"><b>{ticker}</b></td>
                <td style="{_td}">{name}</td>
                <td style="{_td_r}">{shares:.4f}</td>
                <td style="{_td_r}">{_val(price, ccy)}</td>
                <td style="{_td_r}">{_val(value, ccy)}</td>
                <td style="{_td_r}">{weight:.2f}%</td>
                <td style="{_td_r};color:{color}">{_val(unrealized, ccy)} ({unrealized_pct:.2f}%)</td>
                <td style="{_td_r}">{ms_weight:.2f}%</td>
            </tr>"""

    # Dividends
    div_section = ""
    estimated_annual = ctx.get("estimated_annual_dividends", 0.0)
    dividends_ytd = ctx.get("dividends_ytd", 0.0)
    if estimated_annual and float(estimated_annual) > 0:
        div_section = f"""
        <h2 style="color:#f3a712;font-family:monospace;margin-top:32px">DIVIDENDS</h2>
        <table style="{_table}">
            <tr><td style="{_td}">Estimated Annual Dividends</td>
                <td style="{_td_r}">{_val(estimated_annual, ccy)}</td></tr>
            <tr><td style="{_td}">Dividends YTD (collected)</td>
                <td style="{_td_r}">{_val(dividends_ytd, ccy)}</td></tr>
        </table>"""

    benchmark_row = ""
    if benchmark_cum is not None:
        excess_str = _pct(float(excess) * 100) if excess is not None else "—"
        benchmark_row = f"""
        <tr><td style="{_td}">VOO Benchmark Return</td>
            <td style="{_td_r}">{_pct(float(benchmark_cum) * 100)}</td></tr>
        <tr><td style="{_td}">Excess vs Benchmark</td>
            <td style="{_td_r}">{excess_str}</td></tr>"""

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="background-color:#0b0f14;color:#e6e6e6;font-family:monospace;padding:32px;margin:0">

      <h1 style="color:#f3a712;font-size:24px;margin-bottom:4px">
        PORTAFOLIO MANAGEMENT SA
      </h1>
      <h2 style="color:#aaa;font-size:16px;margin-top:0">
        Monthly Report · {month_label}
      </h2>

      <h2 style="color:#f3a712;margin-top:32px">PORTFOLIO SUMMARY</h2>
      <table style="{_table}">
        <tr><td style="{_td}">Total Portfolio</td>
            <td style="{_td_r}"><b>{_val(total_portfolio, ccy)}</b></td></tr>
        <tr><td style="{_td}">Holdings</td>
            <td style="{_td_r}">{_val(holdings_value, ccy)}</td></tr>
        <tr><td style="{_td}">Cash</td>
            <td style="{_td_r}">{_val(cash_total, ccy)}</td></tr>
        <tr><td style="{_td}">Invested Capital</td>
            <td style="{_td_r}">{_val(invested_capital, ccy)}</td></tr>
        <tr><td style="{_td}">Unrealized PnL</td>
            <td style="{_td_r};color:{'#4caf50' if unrealized_pnl >= 0 else '#f44336'}">
                {_val(unrealized_pnl, ccy)}</td></tr>
        {mom_section}
      </table>

      <h2 style="color:#f3a712;margin-top:32px">PERFORMANCE METRICS</h2>
      <table style="{_table}">
        <tr><td style="{_td}">Total Return (historical)</td>
            <td style="{_td_r}">{_pct(total_return * 100)}</td></tr>
        <tr><td style="{_td}">Annualized Volatility</td>
            <td style="{_td_r}">{_pct(volatility * 100)}</td></tr>
        <tr><td style="{_td}">Sharpe Ratio</td>
            <td style="{_td_r}">{sharpe:.4f}</td></tr>
        <tr><td style="{_td}">Max Drawdown</td>
            <td style="{_td_r};color:#f44336">{_pct(max_drawdown * 100)}</td></tr>
        <tr><td style="{_td}">Alpha</td>
            <td style="{_td_r}">{_pct(alpha * 100)}</td></tr>
        <tr><td style="{_td}">Beta</td>
            <td style="{_td_r}">{beta:.4f}</td></tr>
        <tr><td style="{_td}">Tracking Error</td>
            <td style="{_td_r}">{_pct(tracking_error * 100)}</td></tr>
        <tr><td style="{_td}">Information Ratio</td>
            <td style="{_td_r}">{information_ratio:.4f}</td></tr>
        {benchmark_row}
      </table>

      <h2 style="color:#f3a712;margin-top:32px">HOLDINGS</h2>
      <table style="{_table}">
        <tr>
          <th style="{_th}">Ticker</th>
          <th style="{_th}">Name</th>
          <th style="{_th}">Shares</th>
          <th style="{_th}">Price ({ccy})</th>
          <th style="{_th}">Value ({ccy})</th>
          <th style="{_th}">Weight %</th>
          <th style="{_th}">Unrealized PnL</th>
          <th style="{_th}">Max Sharpe %</th>
        </tr>
        {holding_rows}
      </table>

      {div_section}
      {stress_section}

      <hr style="border-color:#333;margin-top:40px">
      <p style="color:#555;font-size:11px;font-family:monospace">
        Generated automatically by Portafolio Management SA · {datetime.now(_COLOMBIA_TZ).strftime("%Y-%m-%d %H:%M")} Colombia time
      </p>
    </body>
    </html>
    """
    return html


# Style constants
_table = "border-collapse:collapse;width:100%;margin-top:8px"
_th = "background:#1a1f2e;color:#f3a712;padding:8px 12px;text-align:left;border:1px solid #2a2f3e;font-family:monospace"
_td = "padding:7px 12px;border:1px solid #1e2430;color:#e6e6e6;font-family:monospace"
_td_r = "padding:7px 12px;border:1px solid #1e2430;color:#e6e6e6;font-family:monospace;text-align:right"


# ── PDF builder ────────────────────────────────────────────────────────────────

def _build_pdf_html(html_body: str) -> str:
    """Return a PDF-friendly variant of the report HTML (light background, xhtml2pdf-safe CSS)."""
    return html_body.replace(
        "background-color:#0b0f14", "background-color:#ffffff"
    ).replace(
        "color:#e6e6e6", "color:#111111"
    ).replace(
        "color:#aaa", "color:#444444"
    ).replace(
        "color:#555", "color:#666666"
    ).replace(
        "background:#1a1f2e", "background:#f0f0f0"
    ).replace(
        "border:1px solid #2a2f3e", "border:1px solid #cccccc"
    ).replace(
        "border:1px solid #1e2430", "border:1px solid #dddddd"
    )


def _html_to_pdf_bytes(html: str) -> bytes | None:
    try:
        from xhtml2pdf import pisa

        pdf_html = _build_pdf_html(html)
        buf = io.BytesIO()
        result = pisa.CreatePDF(io.StringIO(pdf_html), dest=buf)
        if result.err:
            return None
        return buf.getvalue()
    except Exception:
        return None


# ── Send ───────────────────────────────────────────────────────────────────────

def send_monthly_report(ctx: dict, month_str: str):
    email_cfg = st.secrets.get("email", {})
    smtp_host = str(email_cfg.get("smtp_host", "smtp.gmail.com"))
    smtp_port = int(email_cfg.get("smtp_port", 587))
    sender = str(email_cfg.get("sender", ""))
    password = str(email_cfg.get("app_password", ""))
    recipient = str(email_cfg.get("recipient", ""))

    if not all([sender, password, recipient]):
        return

    now_col = datetime.now(_COLOMBIA_TZ)
    subject = f"Portfolio Report · {now_col.strftime('%B %Y')} · Portafolio Management SA"
    html_body = build_monthly_report_html(ctx)

    # Outer container: mixed (text + attachments)
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    # HTML body in an "alternative" sub-part
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    # PDF attachment
    pdf_bytes = _html_to_pdf_bytes(html_body)
    if pdf_bytes:
        filename = f"portfolio_report_{now_col.strftime('%Y_%m')}.pdf"
        attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        attachment.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(attachment)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())

    _mark_report_sent(month_str)
    st.session_state["monthly_report_sent"] = month_str
