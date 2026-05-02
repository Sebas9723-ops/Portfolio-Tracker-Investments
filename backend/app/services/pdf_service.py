"""
Institutional-grade PDF report generator using reportlab.
Produces a clean, printable portfolio snapshot with metrics and holdings.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Optional

import pytz
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Brand palette ──────────────────────────────────────────────────────────────
GOLD   = colors.HexColor("#f3a712")
NAVY   = colors.HexColor("#1e2535")
DARK   = colors.HexColor("#0f172a")
GREEN  = colors.HexColor("#16a34a")
RED    = colors.HexColor("#dc2626")
MUTED  = colors.HexColor("#64748b")
LGRAY  = colors.HexColor("#f1f5f9")
BORDER = colors.HexColor("#e2e8f0")

_COL = pytz.timezone("America/Bogota")


def _sign(v: float) -> str:
    return "+" if v >= 0 else ""


def _pct(v: Optional[float], mult: float = 100, d: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v * mult:+.{d}f}%"


def _num(v: Optional[float], d: int = 4) -> str:
    if v is None:
        return "—"
    return f"{v:.{d}f}"


def _fmt(v: float, ccy: str = "USD") -> str:
    return f"{ccy} {v:,.2f}"


def generate_portfolio_report(
    summary,           # PortfolioSummary from portfolio_builder
    metrics: dict,     # compute_extended_ratios output (keys: twr, annualized_return, …)
    base_currency: str = "USD",
    benchmark_ticker: str = "VOO",
) -> bytes:
    """Return raw PDF bytes for the portfolio report."""
    buf = BytesIO()
    now = datetime.now(_COL)

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Portfolio Report",
        author="Portafolio Management SA",
    )

    styles = getSampleStyleSheet()

    def _style(name: str, **kw) -> ParagraphStyle:
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    h2 = _style("H2", fontSize=9, fontName="Helvetica-Bold", textColor=MUTED,
                spaceBefore=14, spaceAfter=4, letterSpacing=0.5)
    caption = _style("Cap", fontSize=7, fontName="Helvetica", textColor=MUTED, spaceAfter=2)

    elems = []

    # ── Header ────────────────────────────────────────────────────────────────
    hdr = Table(
        [[
            Paragraph(
                "<b>PORTAFOLIO MANAGEMENT SA</b>",
                _style("HL", fontSize=15, fontName="Helvetica-Bold", textColor=DARK),
            ),
            Paragraph(
                f"Report date: {now.strftime('%Y-%m-%d %H:%M')} COT",
                _style("HR", fontSize=9, textColor=MUTED, alignment=TA_RIGHT),
            ),
        ]],
        colWidths=[11 * cm, 6 * cm],
    )
    hdr.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    elems.append(hdr)
    elems.append(HRFlowable(width="100%", thickness=2.5, color=GOLD))
    elems.append(Spacer(1, 10))

    # ── Summary banner ────────────────────────────────────────────────────────
    total     = summary.total_value_base
    invested  = summary.total_invested_base or 0.0
    pnl       = summary.total_unrealized_pnl or 0.0
    pnl_pct   = summary.total_unrealized_pnl_pct or 0.0
    day_chg   = summary.total_day_change_base or 0.0

    banner_vals = [
        f"{base_currency} {total:,.2f}",
        f"{base_currency} {invested:,.2f}",
        f"{_sign(pnl)}{base_currency} {abs(pnl):,.2f}\n({_sign(pnl_pct)}{pnl_pct:.2f}%)",
        f"{_sign(day_chg)}{base_currency} {abs(day_chg):,.2f}",
    ]
    banner_labels = ["PORTFOLIO VALUE", "INVESTED CAPITAL", "UNREALIZED P&L", "TODAY'S CHANGE"]

    banner = Table(
        [banner_labels, banner_vals],
        colWidths=[4.25 * cm] * 4,
    )
    banner_style = TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",      (0, 0), (-1, 0), colors.white),
        ("FONTNAME",       (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, 0), 7),
        ("FONTSIZE",       (0, 1), (-1, 1), 11),
        ("FONTNAME",       (0, 1), (-1, 1), "Helvetica-Bold"),
        ("TEXTCOLOR",      (0, 1), (1, 1), DARK),
        ("TEXTCOLOR",      (2, 1), (2, 1), GREEN if pnl >= 0 else RED),
        ("TEXTCOLOR",      (3, 1), (3, 1), GREEN if day_chg >= 0 else RED),
        ("ALIGN",          (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 8),
        ("BACKGROUND",     (0, 1), (-1, 1), LGRAY),
        ("GRID",           (0, 0), (-1, -1), 0.5, BORDER),
        ("BOX",            (0, 0), (-1, -1), 1, BORDER),
    ])
    banner.setStyle(banner_style)
    elems.append(banner)
    elems.append(Spacer(1, 14))

    # ── Performance metrics ───────────────────────────────────────────────────
    elems.append(Paragraph("PERFORMANCE METRICS", h2))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    elems.append(Spacer(1, 6))

    twr      = metrics.get("twr") or 0.0
    ann_ret  = metrics.get("annualized_return")
    ann_vol  = metrics.get("annualized_vol")
    sharpe   = metrics.get("sharpe")
    sortino  = metrics.get("sortino")
    max_dd   = metrics.get("max_drawdown")
    alpha    = metrics.get("alpha")
    beta     = metrics.get("beta")
    info_r   = metrics.get("information_ratio")
    calmar   = metrics.get("calmar")

    # annualized_return, annualized_vol, max_drawdown, alpha are already in % form
    # (e.g. 27.73 means 27.73%) — use mult=1 to avoid double-multiplying by 100
    pdata = [
        ["Metric", "Value", "Metric", "Value"],
        ["TWR (cumulative)",     f"{twr:+.2f}%",              "Ann. Return",     _pct(ann_ret, mult=1)],
        ["Sharpe Ratio",         _num(sharpe),                "Sortino Ratio",   _num(sortino)],
        ["Max Drawdown",         _pct(max_dd, mult=1),        "Ann. Volatility", _pct(ann_vol, mult=1)],
        [f"Alpha vs {benchmark_ticker}", _pct(alpha, mult=1), "Beta",            _num(beta)],
        ["Information Ratio",    _num(info_r),                "Calmar Ratio",    _num(calmar)],
    ]

    ptable = Table(pdata, colWidths=[5.5 * cm, 3 * cm, 5.5 * cm, 3 * cm])
    ptable.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("TEXTCOLOR",     (0, 1), (0, -1), MUTED),
        ("TEXTCOLOR",     (2, 1), (2, -1), MUTED),
        ("FONTNAME",      (1, 1), (1, -1), "Helvetica-Bold"),
        ("FONTNAME",      (3, 1), (3, -1), "Helvetica-Bold"),
        ("TEXTCOLOR",     (1, 1), (1, -1), DARK),
        ("TEXTCOLOR",     (3, 1), (3, -1), DARK),
        ("ALIGN",         (1, 0), (1, -1), "RIGHT"),
        ("ALIGN",         (3, 0), (3, -1), "RIGHT"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, LGRAY]),
        ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
        ("BOX",           (0, 0), (-1, -1), 1, BORDER),
    ]))
    elems.append(ptable)
    elems.append(Spacer(1, 14))

    # ── Holdings ──────────────────────────────────────────────────────────────
    elems.append(Paragraph("HOLDINGS", h2))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    elems.append(Spacer(1, 6))

    hdr_row = ["Ticker", "Name", "Shares", "Avg Cost", f"Price ({base_currency})", f"Value ({base_currency})", "Weight", "P&L%"]
    hrows = [hdr_row]

    for row in sorted(summary.rows, key=lambda r: -r.value_base):
        pnl_r = row.unrealized_pnl_pct or 0.0
        hrows.append([
            row.ticker,
            (row.name or row.ticker)[:22],
            f"{row.shares:.3f}",
            f"{row.avg_cost_native:.2f}" if row.avg_cost_native else "—",
            f"{row.price_base:,.2f}",
            f"{row.value_base:,.0f}",
            f"{row.weight:.1f}%",
            f"{pnl_r:+.1f}%",
        ])

    col_w = [1.7 * cm, 4.5 * cm, 1.6 * cm, 1.8 * cm, 2 * cm, 2.2 * cm, 1.4 * cm, 1.8 * cm]
    htable = Table(hrows, colWidths=col_w)

    hts = TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("TEXTCOLOR",     (0, 1), (0, -1), colors.HexColor("#1d4ed8")),
        ("FONTNAME",      (0, 1), (0, -1), "Helvetica-Bold"),
        ("ALIGN",         (2, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, LGRAY]),
        ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
        ("BOX",           (0, 0), (-1, -1), 1, BORDER),
    ])
    # Color P&L% per row
    for i, r in enumerate(hrows[1:], start=1):
        val = r[-1]
        hts.add("TEXTCOLOR", (7, i), (7, i), GREEN if val.startswith("+") else (RED if val.startswith("-") else MUTED))
        hts.add("FONTNAME",  (7, i), (7, i), "Helvetica-Bold")

    htable.setStyle(hts)
    elems.append(htable)
    elems.append(Spacer(1, 20))

    # ── Footer ────────────────────────────────────────────────────────────────
    elems.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    elems.append(Spacer(1, 4))
    elems.append(Paragraph(
        f"Portafolio Management SA · {now.strftime('%Y-%m-%d')} · For internal use only. "
        "Past performance is not indicative of future results. "
        "Data sourced from Yahoo Finance.",
        caption,
    ))

    doc.build(elems)
    return buf.getvalue()
