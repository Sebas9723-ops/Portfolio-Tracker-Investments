"""
Bloomberg-style dark-theme PDF report generator using reportlab canvas.
Returns raw PDF bytes for a weekly portfolio snapshot.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from textwrap import wrap as textwrap_wrap
from typing import Optional

import pytz
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

# ── Palette ───────────────────────────────────────────────────────────────────
BG     = HexColor("#0b0f14")   # page background
GOLD   = HexColor("#f3a712")   # accent / header bar
LIGHT  = HexColor("#e2e8f0")   # primary text
MUTED  = HexColor("#6b7280")   # secondary / labels
GREEN  = HexColor("#22c55e")   # positive values
RED    = HexColor("#ef4444")   # negative values
ROW_A  = HexColor("#111827")   # table row alt-A (slightly lighter dark)
ROW_B  = HexColor("#0b0f14")   # table row alt-B (page bg)
BORDER = HexColor("#1f2937")   # subtle row border

_COL_TZ = pytz.timezone("America/Bogota")

PAGE_W, PAGE_H = A4          # 595.27 x 841.89 pts
MARGIN_L = 36
MARGIN_R = PAGE_W - 36
CONTENT_W = MARGIN_R - MARGIN_L


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sign(v: float) -> str:
    return "+" if v >= 0 else ""


def _pct(v: Optional[float], mult: float = 1, d: int = 2) -> str:
    if v is None:
        return "—"
    return f"{_sign(v * mult)}{v * mult:.{d}f}%"


def _num(v: Optional[float], d: int = 2) -> str:
    if v is None:
        return "—"
    return f"{_sign(v)}{v:.{d}f}"


def _money(v: float, ccy: str) -> str:
    return f"{ccy} {v:,.2f}"


def _draw_bg(c: Canvas) -> None:
    """Fill the entire current page with the dark background color."""
    c.setFillColor(BG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)


def _check_page(c: Canvas, y: float, needed: float = 60) -> float:
    """If y is too low, start a new page and return the top y position."""
    if y < needed:
        c.showPage()
        _draw_bg(c)
        return PAGE_H - 40
    return y


def _section_header(c: Canvas, y: float, title: str) -> float:
    """Draw a gold-underlined section title. Returns new y."""
    y = _check_page(c, y, needed=80)
    y -= 18
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(GOLD)
    c.drawString(MARGIN_L, y, title)
    y -= 3
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.8)
    c.line(MARGIN_L, y, MARGIN_R, y)
    return y - 6


def _label_value_row(
    c: Canvas,
    y: float,
    label: str,
    value: str,
    value_color=LIGHT,
    row_idx: int = 0,
) -> float:
    """Draw a single label | value row in a 2-col summary table."""
    row_h = 16
    # alternating row background
    bg = ROW_A if row_idx % 2 == 0 else ROW_B
    c.setFillColor(bg)
    c.rect(MARGIN_L, y - row_h + 4, CONTENT_W, row_h, fill=1, stroke=0)

    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    c.drawString(MARGIN_L + 6, y - 8, label)

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(value_color)
    c.drawRightString(MARGIN_R - 6, y - 8, value)
    return y - row_h


def _table_header_row(c: Canvas, y: float, cols: list, widths: list) -> float:
    """Draw a gold-bar header row for a multi-column table."""
    row_h = 16
    c.setFillColor(GOLD)
    c.rect(MARGIN_L, y - row_h + 4, CONTENT_W, row_h, fill=1, stroke=0)

    x = MARGIN_L
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(BG)
    for i, (col, w) in enumerate(zip(cols, widths)):
        if i == 0:
            c.drawString(x + 4, y - 9, col)
        else:
            c.drawRightString(x + w - 2, y - 9, col)
        x += w
    return y - row_h


def _table_data_row(
    c: Canvas,
    y: float,
    cells: list,
    widths: list,
    colors_per_cell: list,
    row_idx: int = 0,
) -> float:
    """Draw one data row with per-cell colors."""
    row_h = 15
    bg = ROW_A if row_idx % 2 == 0 else ROW_B
    c.setFillColor(bg)
    c.rect(MARGIN_L, y - row_h + 3, CONTENT_W, row_h, fill=1, stroke=0)

    # subtle border line
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.3)
    c.line(MARGIN_L, y - row_h + 3, MARGIN_R, y - row_h + 3)

    x = MARGIN_L
    for i, (cell, w, col) in enumerate(zip(cells, widths, colors_per_cell)):
        c.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 7)
        c.setFillColor(col)
        if i == 0:
            c.drawString(x + 4, y - 9, str(cell))
        else:
            c.drawRightString(x + w - 2, y - 9, str(cell))
        x += w
    return y - row_h


def _value_color(raw: str, zero_color=LIGHT) -> HexColor:
    """Return GREEN for positive, RED for negative, else zero_color."""
    s = str(raw).strip()
    if s.startswith("+") or (s and s[0].isdigit() and not s.startswith("0.00")):
        try:
            if float(s.replace("%", "").replace("+", "")) > 0:
                return GREEN
        except ValueError:
            pass
    if s.startswith("-"):
        return RED
    return zero_color


def _momentum_color(val_str: str) -> HexColor:
    s = str(val_str).strip()
    if s == "—":
        return MUTED
    if s.startswith("+"):
        return GREEN
    if s.startswith("-"):
        return RED
    return LIGHT


# ── Main generator ────────────────────────────────────────────────────────────

def generate_portfolio_pdf(
    summary,
    metrics: dict,
    base_currency: str = "USD",
    benchmark_ticker: str = "VOO",
    benchmark_cum: float | None = None,
    momentum: dict | None = None,
    fear_greed: dict | None = None,
    week_change_pct: float | None = None,
    ai_analysis: str | None = None,
) -> bytes:
    """Generate a Bloomberg dark-theme PDF report and return the raw bytes."""

    buf = BytesIO()
    now = datetime.now(_COL_TZ)

    c = Canvas(buf, pagesize=A4)
    c.setTitle("Weekly Portfolio Report")
    c.setAuthor("Portfolio Management SA")

    # ── Page 1 background ────────────────────────────────────────────────────
    _draw_bg(c)

    y = PAGE_H - 20  # current cursor (top of page)

    # ── 1. Header bar ─────────────────────────────────────────────────────────
    bar_h = 32
    c.setFillColor(GOLD)
    c.rect(0, PAGE_H - bar_h, PAGE_W, bar_h, fill=1, stroke=0)

    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(BG)
    c.drawString(MARGIN_L, PAGE_H - 22, "WEEKLY PORTFOLIO REPORT")

    date_str = now.strftime("%B %d, %Y")
    c.setFont("Helvetica", 9)
    c.drawRightString(MARGIN_R, PAGE_H - 22, date_str)

    y = PAGE_H - bar_h - 14

    # ── 2. PORTFOLIO SUMMARY ──────────────────────────────────────────────────
    y = _section_header(c, y, "PORTFOLIO SUMMARY")

    total    = summary.total_value_base
    invested = summary.total_invested_base or 0.0
    pnl      = summary.total_unrealized_pnl or 0.0
    pnl_pct  = summary.total_unrealized_pnl_pct or 0.0

    pnl_str     = f"{_sign(pnl)}{base_currency} {abs(pnl):,.2f}  ({_pct(pnl_pct)})"
    pnl_color   = GREEN if pnl >= 0 else RED

    summary_rows = [
        ("Total Value",       _money(total, base_currency),   LIGHT),
        ("Invested Capital",  _money(invested, base_currency), LIGHT),
        ("Unrealized P&L",    pnl_str,                         pnl_color),
    ]
    if week_change_pct is not None:
        wc_str   = _pct(week_change_pct)
        wc_color = GREEN if week_change_pct >= 0 else RED
        summary_rows.append(("Week Change", wc_str, wc_color))

    for idx, (label, value, col) in enumerate(summary_rows):
        y = _check_page(c, y, needed=80)
        y = _label_value_row(c, y, label, value, value_color=col, row_idx=idx)

    # ── 3. RISK & RETURN ──────────────────────────────────────────────────────
    y -= 6
    y = _section_header(c, y, "RISK & RETURN (TRAILING 1Y)")

    twr        = metrics.get("twr")
    ann_ret    = metrics.get("annualized_return")
    ann_vol    = metrics.get("annualized_vol")
    sharpe     = metrics.get("sharpe")
    sortino    = metrics.get("sortino")
    max_dd     = metrics.get("max_drawdown")
    alpha      = metrics.get("alpha")
    beta       = metrics.get("beta")

    def _pct_sign(v: Optional[float], d: int = 2) -> str:
        if v is None:
            return "—"
        return f"{_sign(v)}{v:.{d}f}%"

    risk_rows: list[tuple[str, str, HexColor]] = []

    if twr is not None:
        risk_rows.append(("TWR (cumulative)", _pct_sign(twr), GREEN if twr >= 0 else RED))

    if ann_ret is not None:
        risk_rows.append(("Ann. Return", _pct_sign(ann_ret), GREEN if ann_ret >= 0 else RED))

    if ann_vol is not None:
        risk_rows.append(("Ann. Volatility", _pct_sign(ann_vol), LIGHT))

    if sharpe is not None:
        risk_rows.append(("Sharpe Ratio", f"{sharpe:.2f}", LIGHT))

    if sortino is not None:
        risk_rows.append(("Sortino Ratio", f"{sortino:.2f}", LIGHT))

    if max_dd is not None:
        risk_rows.append(("Max Drawdown", _pct_sign(max_dd), RED))

    if alpha is not None:
        risk_rows.append((f"Alpha vs {benchmark_ticker}", _pct_sign(alpha), GREEN if alpha >= 0 else RED))

    if beta is not None:
        risk_rows.append(("Beta", f"{beta:.2f}", LIGHT))

    if benchmark_cum is not None:
        risk_rows.append((f"{benchmark_ticker} Cumulative Return", _pct_sign(benchmark_cum), LIGHT))
        if twr is not None:
            excess = twr - benchmark_cum
            risk_rows.append(("Excess Return vs Benchmark", _pct_sign(excess), GREEN if excess >= 0 else RED))

    if fear_greed is not None:
        fg_score  = fear_greed.get("score", "—")
        fg_rating = fear_greed.get("rating", "")
        fg_str    = f"{fg_score}  {fg_rating}".strip()
        # score < 40 → fear (red), > 60 → greed (green), else neutral
        try:
            fg_color = GREEN if float(fg_score) > 60 else (RED if float(fg_score) < 40 else LIGHT)
        except (TypeError, ValueError):
            fg_color = LIGHT
        risk_rows.append(("Fear & Greed Index", fg_str, fg_color))

    for idx, (label, value, col) in enumerate(risk_rows):
        y = _check_page(c, y, needed=80)
        y = _label_value_row(c, y, label, value, value_color=col, row_idx=idx)

    # ── 4. HOLDINGS ───────────────────────────────────────────────────────────
    y -= 6
    y = _check_page(c, y, needed=120)
    y = _section_header(c, y, "HOLDINGS")

    h_cols   = ["Ticker", "Shares", "Price", "Value", "Wt %", "PnL %"]
    # distribute widths: ticker wider, rest equal
    ticker_w = 58
    rest_w   = (CONTENT_W - ticker_w) / 5
    h_widths = [ticker_w] + [rest_w] * 5

    y = _check_page(c, y, needed=60)
    y = _table_header_row(c, y, h_cols, h_widths)

    for ridx, row in enumerate(sorted(summary.rows, key=lambda r: -r.value_base)):
        y = _check_page(c, y, needed=30)
        pnl_r   = row.unrealized_pnl_pct or 0.0
        pnl_str = _pct_sign(pnl_r)

        cells = [
            row.ticker,
            f"{row.shares:.3f}",
            f"{row.price_native:,.2f}" if hasattr(row, "price_native") and row.price_native else "—",
            f"{row.value_base:,.0f}",
            f"{row.weight:.1f}%",
            pnl_str,
        ]
        cell_colors = [
            GOLD,   # ticker
            LIGHT,
            LIGHT,
            LIGHT,
            MUTED,
            GREEN if pnl_r >= 0 else RED,
        ]
        y = _table_data_row(c, y, cells, h_widths, cell_colors, row_idx=ridx)

    # ── 5. MOMENTUM ───────────────────────────────────────────────────────────
    if momentum:
        y -= 6
        y = _check_page(c, y, needed=120)
        y = _section_header(c, y, "MOMENTUM")

        m_cols   = ["Ticker", "1W", "1M", "3M", "6M", "1Y"]
        tick_w2  = 58
        rest_w2  = (CONTENT_W - tick_w2) / 5
        m_widths = [tick_w2] + [rest_w2] * 5

        y = _check_page(c, y, needed=60)
        y = _table_header_row(c, y, m_cols, m_widths)

        # Sort by ticker name for consistency
        for ridx, (ticker, mdata) in enumerate(sorted(momentum.items())):
            y = _check_page(c, y, needed=30)

            def _mpct(key: str) -> str:
                v = mdata.get(key)
                if v is None:
                    return "—"
                return _pct_sign(v * 100 if abs(v) < 5 else v)  # handle decimal vs pct

            vals = [_mpct(k) for k in ("1w", "1m", "3m", "6m", "1y")]
            cells2 = [ticker] + vals
            cell_colors2 = [GOLD] + [_momentum_color(v) for v in vals]
            y = _table_data_row(c, y, cells2, m_widths, cell_colors2, row_idx=ridx)

    # ── 6. AI WEEKLY ANALYSIS ─────────────────────────────────────────────────
    if ai_analysis:
        y -= 6
        y = _check_page(c, y, needed=120)
        y = _section_header(c, y, "AI WEEKLY ANALYSIS")

        # Box border
        box_pad  = 8
        line_h   = 11
        text_w   = CONTENT_W - box_pad * 2
        # Wrap text at ~100 chars
        char_w   = 5.2  # approx pts per char at font size 7.5
        max_chars = int(text_w / char_w)
        lines: list[str] = []
        for para in ai_analysis.split("\n"):
            if para.strip() == "":
                lines.append("")
            else:
                lines.extend(textwrap_wrap(para, width=max(max_chars, 40)) or [""])

        total_text_h = len(lines) * line_h + box_pad * 2
        # Check if we need a new page for the box
        if y - total_text_h < 60:
            c.showPage()
            _draw_bg(c)
            y = PAGE_H - 40
            y = _section_header(c, y, "AI WEEKLY ANALYSIS")

        box_y = y - total_text_h
        c.setFillColor(ROW_A)
        c.setStrokeColor(GOLD)
        c.setLineWidth(0.8)
        c.rect(MARGIN_L, box_y, CONTENT_W, total_text_h, fill=1, stroke=1)

        text_y = y - box_pad - line_h + 2
        c.setFont("Helvetica", 7.5)
        for line in lines:
            if text_y < box_y + box_pad:
                break  # don't overflow the box (safety)
            c.setFillColor(LIGHT)
            c.drawString(MARGIN_L + box_pad, text_y, line)
            text_y -= line_h

        y = box_y - 8

    # ── 7. Footer ─────────────────────────────────────────────────────────────
    # Footer on current page (and on any subsequent pages via _draw_footer)
    def _draw_footer(canvas: Canvas) -> None:
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(MUTED)
        footer_text = (
            f"Portfolio Management SA  —  automated report  —  "
            f"generated {now.strftime('%Y-%m-%d %H:%M')} COT  —  "
            "Past performance is not indicative of future results."
        )
        canvas.drawCentredString(PAGE_W / 2, 18, footer_text)
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN_L, 28, MARGIN_R, 28)

    _draw_footer(c)
    c.save()

    return buf.getvalue()
