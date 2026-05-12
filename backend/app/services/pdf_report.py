"""
Premium Bloomberg-style portfolio report PDF.
Two A4 pages, dark theme, color-coded tables, weight bar chart, AI analysis.
"""
from __future__ import annotations

import textwrap
from io import BytesIO
from datetime import datetime
from typing import Optional

import pytz

from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor

# ── Palette ───────────────────────────────────────────────────────────────────
BG    = HexColor("#0b0f14")
HDR   = HexColor("#070b10")
CARD  = HexColor("#111827")
CARD2 = HexColor("#0d1117")
BORD  = HexColor("#1e293b")
GOLD  = HexColor("#f3a712")
GOLD2 = HexColor("#fbbf24")
TEXT  = HexColor("#f1f5f9")
MUT   = HexColor("#6b7280")
MUT2  = HexColor("#94a3b8")
GRN   = HexColor("#22c55e")
RED   = HexColor("#ef4444")
BLUE  = HexColor("#60a5fa")

W, H   = A4          # 595.28 × 841.89
ML, MR = 28, 28
UW     = W - ML - MR  # ≈ 539


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sign(v: float) -> str:
    return "+" if v >= 0 else ""

def _pct(v: Optional[float], d: int = 2) -> str:
    if v is None:
        return "—"
    return f"{_sign(v)}{v:.{d}f}%"

def _vc(v: Optional[float]):
    """Return green/red/text color based on sign."""
    if v is None:
        return TEXT
    return GRN if v >= 0 else RED

def _mom_bg(v: Optional[float]):
    if v is None:
        return CARD2
    if v > 10:
        return HexColor("#14532d")
    if v > 3:
        return HexColor("#166534")
    if v >= 0:
        return HexColor("#052e16")
    if v > -3:
        return HexColor("#7f1d1d")
    if v > -10:
        return HexColor("#991b1b")
    return HexColor("#450a0a")

def _mom_fg(v: Optional[float]):
    if v is None:
        return MUT
    return GRN if v >= 0 else RED


# ── Canvas wrapper ────────────────────────────────────────────────────────────

class P:
    """Thin wrapper around ReportLab canvas with convenience methods."""

    def __init__(self, c: rl_canvas.Canvas):
        self.c = c
        self._bg()

    def _bg(self):
        self.c.setFillColor(BG)
        self.c.rect(0, 0, W, H, fill=1, stroke=0)

    def new_page(self):
        self.c.showPage()
        self._bg()

    def t(self, x, y, s, font="Helvetica", sz=8, color=TEXT, align="left"):
        self.c.setFillColor(color)
        self.c.setFont(font, sz)
        s = str(s)
        if align == "right":
            self.c.drawRightString(x, y, s)
        elif align == "center":
            self.c.drawCentredString(x, y, s)
        else:
            self.c.drawString(x, y, s)

    def box(self, x, y, w, h, fill=CARD, r=0):
        self.c.setFillColor(fill)
        if r:
            self.c.roundRect(x, y, w, h, r, fill=1, stroke=0)
        else:
            self.c.rect(x, y, w, h, fill=1, stroke=0)

    def hline(self, x1, x2, y, color=BORD, lw=0.5):
        self.c.setStrokeColor(color)
        self.c.setLineWidth(lw)
        self.c.line(x1, y, x2, y)

    def section(self, x, y, w, label) -> float:
        """Draw gold section header bar, return new cur_y."""
        self.box(x, y - 14, w, 14, fill=GOLD)
        self.t(x + 7, y - 10, label, "Helvetica-Bold", 7, HDR)
        return y - 16


# ══════════════════════════════════════════════════════════════════════════════
# Main generator
# ══════════════════════════════════════════════════════════════════════════════

def generate_portfolio_pdf(
    summary,
    metrics: dict,
    base_currency: str = "USD",
    benchmark_ticker: str = "VOO",
    benchmark_cum: Optional[float] = None,
    momentum: Optional[dict] = None,
    fear_greed: Optional[dict] = None,
    week_change_pct: Optional[float] = None,
    ai_analysis: Optional[str] = None,
    week_ahead: Optional[str] = None,
) -> bytes:

    now      = datetime.now(pytz.timezone("America/Bogota"))
    date_str = now.strftime("%B %d, %Y")
    gen_str  = now.strftime("%Y-%m-%d %H:%M") + " COT"

    buf = BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=A4)
    p   = P(c)

    # ── pre-compute metrics ───────────────────────────────────────────────────
    total   = summary.total_value_base
    pnl     = summary.total_unrealized_pnl or 0.0
    pnl_pct = summary.total_unrealized_pnl_pct or 0.0
    sharpe  = metrics.get("sharpe") or 0.0
    sortino = metrics.get("sortino") or 0.0
    twr     = metrics.get("twr") or 0.0
    # already in % form — do NOT multiply by 100 again
    ann_ret = metrics.get("annualized_return") or 0.0
    vol     = metrics.get("annualized_vol") or 0.0
    max_dd  = metrics.get("max_drawdown") or 0.0
    alpha   = metrics.get("alpha") or 0.0
    beta    = metrics.get("beta") or 0.0

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE 1
    # ══════════════════════════════════════════════════════════════════════════

    # ── Header ────────────────────────────────────────────────────────────────
    HH = 52
    p.box(0, H - HH, W, HH, fill=HDR)
    p.box(0, H - HH, 6, HH, fill=GOLD)                   # left gold bar
    # decorative corner triangle
    c.setFillColor(HexColor("#1a1f2b"))
    c.beginPath()
    c.moveTo(W - 160, H); c.lineTo(W, H); c.lineTo(W, H - HH); c.lineTo(W - 90, H - HH)
    c.closePath(); c.fill()

    p.t(18, H - 22, "WEEKLY PORTFOLIO REPORT", "Helvetica-Bold", 15, GOLD)
    p.t(18, H - 38, "Portfolio Management SA  |  Confidential", sz=8, color=MUT2)
    p.t(W - MR, H - 20, date_str, sz=9, color=TEXT, align="right")
    p.t(W - MR, H - 36, "Page 1 / 2", sz=7, color=MUT, align="right")
    c.setStrokeColor(GOLD); c.setLineWidth(1.5); c.line(0, H - HH, W, H - HH)

    cur_y = H - HH - 14

    # ── KPI cards ─────────────────────────────────────────────────────────────
    CARD_H = 64
    GAP    = 8
    n      = 4
    cw     = (UW - GAP * (n - 1)) / n

    kpis = [
        ("TOTAL VALUE",    f"{base_currency} {total:,.0f}", None,        TEXT),
        ("WEEK CHANGE",    _pct(week_change_pct),           week_change_pct, None),
        ("UNREALIZED P&L", _pct(pnl_pct),                  pnl_pct,     None),
        ("SHARPE RATIO",   f"{sharpe:.3f}",                 None,        BLUE),
    ]

    for i, (lbl, val, sv, forced) in enumerate(kpis):
        cx = ML + i * (cw + GAP)
        cy = cur_y - CARD_H
        p.box(cx, cy, cw, CARD_H, fill=CARD, r=5)
        # top accent strip
        strip = forced if forced else (_vc(sv) if sv is not None else GOLD)
        p.box(cx, cy + CARD_H - 4, cw, 4, fill=strip, r=3)
        p.t(cx + 9, cy + CARD_H - 18, lbl, sz=6.5, color=MUT2)
        vc = forced if forced else (_vc(sv) if sv is not None else TEXT)
        p.t(cx + 9, cy + 13, val, "Helvetica-Bold", 15, vc)

    cur_y -= CARD_H + 14

    # ── Two-column: metrics + weight chart ────────────────────────────────────
    LW = int(UW * 0.44)
    RW = UW - LW - 12
    LX = ML
    RX = ML + LW + 12

    left_start_y = cur_y
    right_start_y = cur_y

    cur_y  = p.section(LX, cur_y, LW, "PORTFOLIO METRICS")
    ry_bar = p.section(RX, right_start_y, RW, "WEIGHT ALLOCATION")

    mrows = [
        ("TWR (cumulative)",          _pct(twr, 2),       twr),
        ("Ann. Return",               _pct(ann_ret, 2),   ann_ret),
        ("Ann. Volatility",           f"{vol:.2f}%",      None),
        ("Sharpe Ratio",              f"{sharpe:.3f}",    sharpe - 0.5),
        ("Sortino Ratio",             f"{sortino:.3f}",   sortino - 0.7),
        ("Max Drawdown",              _pct(max_dd, 2),    max_dd),
        (f"Alpha vs {benchmark_ticker}", _pct(alpha, 2), alpha),
        ("Beta",                      f"{beta:.3f}",      None),
    ]
    if benchmark_cum is not None:
        bm_p   = benchmark_cum * 100
        excess = twr - bm_p
        mrows += [
            (f"{benchmark_ticker} Return", _pct(bm_p, 2),    bm_p),
            ("Excess Return",              _pct(excess, 2),   excess),
        ]
    if fear_greed and fear_greed.get("score") is not None:
        fg = fear_greed
        mrows.append(("Fear & Greed", f"{fg['score']}/100  {fg.get('rating','')}", None))

    RH = 14
    for i, (lbl, val, sv) in enumerate(mrows):
        ry = cur_y - (i + 1) * RH
        p.box(LX, ry, LW, RH, fill=CARD if i % 2 == 0 else BG)
        p.t(LX + 6, ry + 4, lbl, sz=7, color=MUT2)
        p.t(LX + LW - 5, ry + 4, val, "Helvetica-Bold", 7, _vc(sv) if sv is not None else TEXT, align="right")

    met_h = len(mrows) * RH

    # weight bars (right column)
    rows_s  = sorted(summary.rows, key=lambda r: r.weight, reverse=True)
    max_wt  = max((r.weight for r in rows_s), default=100)
    TKW     = 46
    BAR_MAX = RW - TKW - 30
    bh      = min(13, met_h / max(len(rows_s), 1) - 3)
    b_gap   = (met_h - bh * len(rows_s)) / max(len(rows_s) + 1, 1)

    for i, r in enumerate(rows_s):
        by    = ry_bar - (i + 1) * (bh + b_gap)
        blen  = (r.weight / max_wt) * BAR_MAX
        bx    = RX + TKW
        p.box(bx, by, BAR_MAX, bh, fill=BORD, r=2)
        if blen > 2:
            p.box(bx, by, blen, bh, fill=GOLD, r=2)
        p.t(RX, by + bh * 0.2, r.ticker[:8], "Helvetica-Bold", 7, GOLD)
        p.t(bx + BAR_MAX + 4, by + bh * 0.2, f"{r.weight:.1f}%", sz=6.5, color=TEXT)

    cur_y -= met_h + 14

    # ── Holdings table ────────────────────────────────────────────────────────
    cur_y = p.section(ML, cur_y, UW, "HOLDINGS")

    HCOLS = [
        ("TICKER",  ML + 5,       "left"),
        ("SHARES",  ML + 140,     "right"),
        ("PRICE",   ML + 225,     "right"),
        ("VALUE",   ML + 310,     "right"),
        ("WEIGHT",  ML + 385,     "right"),
        ("PNL %",   ML + UW - 3,  "right"),
    ]
    p.box(ML, cur_y - 13, UW, 13, fill=CARD2)
    for lbl, xp, al in HCOLS:
        p.t(xp, cur_y - 10, lbl, "Helvetica-Bold", 6, MUT2, align=al)
    cur_y -= 15

    HROW = 14
    for i, r in enumerate(summary.rows):
        pnl_r = r.unrealized_pnl_pct or 0.0
        ry    = cur_y - HROW
        p.box(ML, ry, UW, HROW, fill=CARD if i % 2 == 0 else BG)
        yt = ry + 4
        p.t(ML + 5,      yt, r.ticker,                "Helvetica-Bold", 8, GOLD)
        p.t(ML + 140,    yt, f"{r.shares:.3f}",       sz=8, align="right")
        p.t(ML + 225,    yt, f"{r.price_native:,.2f}", sz=8, align="right")
        p.t(ML + 310,    yt, f"{r.value_base:,.0f}",  sz=8, align="right")
        p.t(ML + 385,    yt, f"{r.weight:.1f}%",      sz=8, align="right")
        p.t(ML + UW - 3, yt, _pct(pnl_r, 1), "Helvetica-Bold", 8, _vc(pnl_r), align="right")
        cur_y = ry

    # ── Page 1 footer ─────────────────────────────────────────────────────────
    p.hline(ML, W - MR, 26, BORD)
    p.t(ML,     18, "Portfolio Management SA — Automated Weekly Report — Confidential", sz=6.5, color=MUT)
    p.t(W - MR, 18, f"Generated {gen_str}", sz=6.5, color=MUT, align="right")

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE 2
    # ══════════════════════════════════════════════════════════════════════════
    p.new_page()

    HH2 = 38
    p.box(0, H - HH2, W, HH2, fill=HDR)
    p.box(0, H - HH2, 6, HH2, fill=GOLD)
    c.setFillColor(HexColor("#1a1f2b"))
    c.beginPath()
    c.moveTo(W - 120, H); c.lineTo(W, H); c.lineTo(W, H - HH2); c.lineTo(W - 65, H - HH2)
    c.closePath(); c.fill()
    p.t(18, H - 24, "WEEKLY PORTFOLIO REPORT", "Helvetica-Bold", 12, GOLD)
    p.t(18, H - 36, "Portfolio Management SA  |  Confidential", sz=7, color=MUT2)
    p.t(W - MR, H - 18, date_str, sz=9, color=TEXT, align="right")
    p.t(W - MR, H - 32, "Page 2 / 2", sz=7, color=MUT, align="right")
    c.setStrokeColor(GOLD); c.setLineWidth(1.5); c.line(0, H - HH2, W, H - HH2)

    cur_y = H - HH2 - 14

    # ── Momentum heatmap ──────────────────────────────────────────────────────
    if momentum and summary.rows:
        cur_y = p.section(ML, cur_y, UW, "MOMENTUM ANALYSIS")

        PERIODS = ["1w", "1m", "3m", "6m", "1y"]
        PLBLS   = ["1W", "1M", "3M", "6M", "1Y"]
        TKW2    = 56
        CELL_W  = 68
        cell_xs = [ML + TKW2 + CELL_W * i + CELL_W // 2 for i in range(5)]
        wt_x    = ML + UW - 4

        p.box(ML, cur_y - 13, UW, 13, fill=CARD2)
        p.t(ML + 5, cur_y - 10, "TICKER", "Helvetica-Bold", 6.5, MUT2)
        for lbl, cx in zip(PLBLS, cell_xs):
            p.t(cx, cur_y - 10, lbl, "Helvetica-Bold", 6.5, MUT2, align="center")
        p.t(wt_x, cur_y - 10, "WT%", "Helvetica-Bold", 6.5, MUT2, align="right")
        cur_y -= 15

        MH = 16
        for i, r in enumerate(sorted(summary.rows, key=lambda x: x.weight, reverse=True)):
            t  = r.ticker
            tm = momentum.get(t, {})
            ry = cur_y - MH
            p.box(ML, ry, UW, MH, fill=CARD if i % 2 == 0 else BG)
            p.t(ML + 5, ry + 4, t, "Helvetica-Bold", 8, GOLD)

            for period, cx in zip(PERIODS, cell_xs):
                val  = tm.get(period)
                cw2  = CELL_W - 8
                p.box(cx - cw2 // 2, ry + 2, cw2, MH - 4, fill=_mom_bg(val), r=2)
                txt  = _pct(val, 1) if val is not None else "—"
                p.t(cx, ry + 5, txt, "Helvetica-Bold" if val is not None else "Helvetica",
                    7, _mom_fg(val), align="center")

            p.t(wt_x, ry + 5, f"{r.weight:.1f}%", sz=7.5, color=TEXT, align="right")
            cur_y = ry

        cur_y -= 10

    # ── Key Highlights ────────────────────────────────────────────────────────
    highlights: list[tuple[str, str, object]] = []

    if momentum and summary.rows:
        wd = [(r.ticker, momentum.get(r.ticker, {}).get("1w")) for r in summary.rows]
        wd = [(t, v) for t, v in wd if v is not None]
        if wd:
            wd.sort(key=lambda x: x[1], reverse=True)
            highlights.append(("Top winner (1W)",  f"{wd[0][0]}  {_pct(wd[0][1], 1)}",   wd[0][1]))
            highlights.append(("Top laggard (1W)", f"{wd[-1][0]}  {_pct(wd[-1][1], 1)}", wd[-1][1]))

    if fear_greed and fear_greed.get("score") is not None:
        fg = fear_greed
        highlights.append(("Market Sentiment", f"{fg['score']}/100 — {fg.get('rating','')}", None))

    if benchmark_cum is not None:
        bm_p   = benchmark_cum * 100
        excess = twr - bm_p
        highlights.append((f"Excess vs {benchmark_ticker}", _pct(excess, 2), excess))

    if highlights:
        cur_y = p.section(ML, cur_y, UW, "KEY HIGHLIGHTS")
        HL_RH = 14
        box_h = len(highlights) * HL_RH + 14
        p.box(ML, cur_y - box_h, UW, box_h, fill=CARD, r=4)
        p.box(ML, cur_y - box_h, 3, box_h, fill=GOLD)
        col_w = UW // 2
        for idx, (lbl, val, sv) in enumerate(highlights):
            col  = idx % 2
            row  = idx // 2
            hx   = ML + 10 + col * col_w
            hy   = cur_y - 12 - row * HL_RH
            p.t(hx, hy, lbl + ":", sz=7, color=MUT2)
            p.t(hx + 105, hy, val, "Helvetica-Bold", 7, _vc(sv) if sv is not None else BLUE)
        cur_y -= box_h + 10

    # ── Week Ahead ────────────────────────────────────────────────────────────
    if week_ahead:
        cur_y = p.section(ML, cur_y, UW, "WEEK AHEAD — KEY EVENTS & NEWS")

        FOOT = 38
        LH   = 10
        MCH  = 95

        lines: list[str] = []
        for para in week_ahead.split("\n"):
            para = para.strip()
            if not para:
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            wrapped = textwrap.wrap(para, MCH)
            lines.extend(wrapped or [""])

        # leave at least 120pt for AI analysis below
        max_lines = max(1, int((cur_y - FOOT - 130) / LH))
        lines  = lines[:max_lines]
        box_h  = len(lines) * LH + 16

        p.box(ML, cur_y - box_h, UW, box_h, fill=CARD, r=4)
        p.box(ML, cur_y - box_h, 3, box_h, fill=BLUE)   # blue left bar for news

        ty = cur_y - 14
        for line in lines:
            if ty < cur_y - box_h + 4:
                break
            is_h = line.startswith("KEY ") or line.startswith("EARNINGS") or line.startswith("RISKS")
            bullet = line.startswith("•") or line.startswith("-")
            clean = line.strip("-• ").strip()
            if clean:
                color = GOLD2 if is_h else (MUT2 if bullet else TEXT)
                prefix = "• " if bullet and not is_h else ""
                p.t(ML + 10, ty, prefix + clean,
                    "Helvetica-Bold" if is_h else "Helvetica",
                    7.5 if is_h else 7, color)
            ty -= LH

        cur_y -= box_h + 8

    # ── AI Analysis ───────────────────────────────────────────────────────────
    if ai_analysis:
        cur_y = p.section(ML, cur_y, UW, "AI WEEKLY ANALYSIS")

        FOOT = 38
        LH   = 10
        MCH  = 95

        lines: list[str] = []
        for para in ai_analysis.split("\n"):
            para = para.strip()
            if not para:
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            wrapped = textwrap.wrap(para, MCH)
            lines.extend(wrapped or [""])

        max_lines = max(1, int((cur_y - FOOT - 14) / LH))
        lines     = lines[:max_lines]
        box_h     = len(lines) * LH + 16

        p.box(ML, cur_y - box_h, UW, box_h, fill=CARD, r=4)
        p.box(ML, cur_y - box_h, 3, box_h, fill=GOLD)

        ty = cur_y - 14
        for line in lines:
            if ty < cur_y - box_h + 4:
                break
            is_h = line.startswith("**") or line.startswith("##") or (line.isupper() and len(line) > 3)
            clean = line.strip("#* ").strip()
            if clean:
                p.t(ML + 10, ty, clean,
                    "Helvetica-Bold" if is_h else "Helvetica",
                    7.5 if is_h else 7,
                    GOLD2 if is_h else TEXT)
            ty -= LH

    # ── Page 2 footer ─────────────────────────────────────────────────────────
    p.hline(ML, W - MR, 26, BORD)
    p.t(ML,     18, "Portfolio Management SA — Automated Weekly Report — Confidential", sz=6.5, color=MUT)
    p.t(W - MR, 18, f"Generated {gen_str}", sz=6.5, color=MUT, align="right")

    c.save()
    return buf.getvalue()
