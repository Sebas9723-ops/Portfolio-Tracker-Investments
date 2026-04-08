#!/usr/bin/env python3
"""
Daily AI Portfolio Report
─────────────────────────
1. Load portfolio positions from Google Sheets
2. Fetch current prices + market indices via yfinance
3. Fetch per-ticker news via yfinance
4. Generate analysis with Claude (claude-sonnet-4-6)
5. Render a Bloomberg-style PDF with reportlab
6. Send the PDF + caption to Telegram

Required environment variables:
  GCP_SERVICE_ACCOUNT_JSON   Full GCP service account JSON string
  SHEETS_SPREADSHEET_ID      Google Sheets spreadsheet ID
  SHEETS_WORKSHEET           Worksheet name (default: private_positions)
  GEMINI_API_KEY             Google Gemini API key (free at aistudio.google.com)
  TELEGRAM_BOT_TOKEN         Telegram bot token from @BotFather
  TELEGRAM_CHAT_ID           Telegram chat ID (your personal or group chat)
  BASE_CURRENCY              Base currency code (default: USD)
"""

import datetime
import io
import json
import os
import time

import pandas as pd
import yfinance as yf

# ── Globals ────────────────────────────────────────────────────────────────────

TODAY = datetime.date.today()
NOW = datetime.datetime.utcnow()
BASE_CCY = os.environ.get("BASE_CURRENCY", "USD")

MARKET_INDICES = {
    "^GSPC":   "S&P 500",
    "^IXIC":   "Nasdaq",
    "^DJI":    "Dow Jones",
    "^VIX":    "VIX",
    "^TNX":    "10Y Yield",
    "GC=F":    "Gold",
    "CL=F":    "WTI Oil",
    "BTC-USD": "Bitcoin",
    "EURUSD=X": "EUR/USD",
}


def _repair_json(raw: str) -> str:
    """Remove actual newlines that are OUTSIDE JSON string values.
    These are copy-paste artifacts (word-wrap). Newlines inside strings
    (e.g. within the private_key value) are preserved."""
    result = []
    in_string = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and in_string and i + 1 < len(raw):
            result.append(ch)
            result.append(raw[i + 1])
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
        if ch in ("\n", "\r") and not in_string:
            i += 1
            continue
        result.append(ch)
        i += 1
    return "".join(result)


# ══════════════════════════════════════════════════════════════════════════════
# 1. GOOGLE SHEETS — load portfolio positions
# ══════════════════════════════════════════════════════════════════════════════

def load_portfolio() -> pd.DataFrame:
    """
    Read private_positions worksheet.
    Returns DataFrame: Ticker | Name | Shares | AvgCost
    """
    creds_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "")
    sheet_id   = os.environ.get("SHEETS_SPREADSHEET_ID", "")
    ws_name    = os.environ.get("SHEETS_WORKSHEET", "private_positions")

    if not creds_json or not sheet_id:
        print("[WARN] GCP credentials or sheet ID missing — portfolio will be empty")
        return pd.DataFrame(columns=["Ticker", "Name", "Shares", "AvgCost"])

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        # Fix JSON broken by copy-paste newlines, then fix private key format
        creds_json = _repair_json(creds_json)
        creds_dict = json.loads(creds_json)

        # Ensure private_key has actual newlines (handles \\n literal or stripped key)
        pk = creds_dict.get("private_key", "")
        if pk:
            if "\\n" in pk and "\n" not in pk:
                pk = pk.replace("\\n", "\n")
            if "\n" not in pk:
                pk = pk.replace("-----BEGIN PRIVATE KEY-----",
                                "-----BEGIN PRIVATE KEY-----\n")
                pk = pk.replace("-----END PRIVATE KEY-----",
                                "\n-----END PRIVATE KEY-----\n")
            creds_dict["private_key"] = pk
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheet_id)
        ws = sh.worksheet(ws_name)
        records = ws.get_all_records()
        df = pd.DataFrame(records)
        if df.empty:
            return df
        df["Shares"]  = pd.to_numeric(df.get("Shares",  0), errors="coerce").fillna(0)
        df["AvgCost"] = pd.to_numeric(df.get("AvgCost", 0), errors="coerce").fillna(0)
        # Remove zero-share rows
        df = df[df["Shares"] > 0].reset_index(drop=True)
        print(f"[Sheets] Loaded {len(df)} positions")
        return df
    except Exception as exc:
        print(f"[ERROR] Google Sheets load failed: {exc}")
        return pd.DataFrame(columns=["Ticker", "Name", "Shares", "AvgCost"])


# ══════════════════════════════════════════════════════════════════════════════
# 2. MARKET DATA — prices, daily changes, currencies
# ══════════════════════════════════════════════════════════════════════════════

def fetch_prices(tickers: list[str]) -> dict:
    """
    Bulk download last 5 days for all tickers.
    Returns {ticker: {price, prev_close, change_pct}}.
    """
    if not tickers:
        return {}
    results = {}
    try:
        raw = yf.download(tickers, period="5d", auto_adjust=True,
                          progress=False, threads=True)
        if raw.empty:
            return results
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        if hasattr(close, "columns") and len(tickers) == 1:
            close.columns = tickers
        for t in tickers:
            if t not in close.columns:
                continue
            s = close[t].dropna()
            if len(s) < 2:
                continue
            price = float(s.iloc[-1])
            prev  = float(s.iloc[-2])
            results[t] = {
                "price":      price,
                "prev_close": prev,
                "change_pct": (price - prev) / prev * 100 if prev else 0.0,
            }
    except Exception as exc:
        print(f"[ERROR] Price fetch failed: {exc}")
    return results


def fetch_currencies(tickers: list[str]) -> dict:
    """Returns {ticker: currency_str} using fast_info."""
    info = {}
    for t in tickers:
        try:
            fi = yf.Ticker(t).fast_info
            info[t] = getattr(fi, "currency", "USD") or "USD"
        except Exception:
            info[t] = "USD"
        time.sleep(0.05)
    return info


# ══════════════════════════════════════════════════════════════════════════════
# 3. NEWS — per-ticker headlines via yfinance
# ══════════════════════════════════════════════════════════════════════════════

def fetch_news(tickers: list[str], max_per_ticker: int = 3) -> dict[str, list[dict]]:
    """Returns {ticker: [{title, publisher, published}]}."""
    news_map: dict[str, list[dict]] = {}
    for t in tickers:
        try:
            raw_news = yf.Ticker(t).news or []
            items = []
            for item in raw_news[:max_per_ticker]:
                ts = item.get("providerPublishTime", 0)
                dt = datetime.datetime.utcfromtimestamp(ts).strftime("%b %d %H:%M") if ts else ""
                items.append({
                    "title":     item.get("title", ""),
                    "publisher": item.get("publisher", ""),
                    "published": dt,
                    "link":      item.get("link", ""),
                })
            news_map[t] = items
        except Exception:
            news_map[t] = []
        time.sleep(0.15)
    return news_map


# ══════════════════════════════════════════════════════════════════════════════
# 4. PORTFOLIO SUMMARY DataFrame
# ══════════════════════════════════════════════════════════════════════════════

def build_summary(positions: pd.DataFrame, prices: dict, currencies: dict) -> pd.DataFrame:
    """Enrich positions with live prices, P&L, and weight."""
    rows = []
    for _, pos in positions.iterrows():
        ticker   = str(pos["Ticker"]).strip()
        name     = str(pos.get("Name", ticker))
        shares   = float(pos.get("Shares",  0))
        avg_cost = float(pos.get("AvgCost", 0))
        p        = prices.get(ticker, {})
        price    = p.get("price")
        chg      = p.get("change_pct")
        ccy      = currencies.get(ticker, "USD")

        value    = shares * price          if price                    else None
        cost     = shares * avg_cost       if avg_cost                 else None
        pnl      = value  - cost           if (value and cost)         else None
        pnl_pct  = pnl / cost * 100        if (pnl is not None and cost and cost != 0) else None

        rows.append({
            "Ticker":    ticker,
            "Name":      name,
            "Currency":  ccy,
            "Shares":    shares,
            "Price":     price,
            "Value":     value,
            "Avg Cost":  avg_cost or None,
            "Cost Basis":cost,
            "P&L $":     pnl,
            "P&L %":     pnl_pct,
            "Day %":     chg,
        })

    df = pd.DataFrame(rows)
    total = df["Value"].sum() if not df.empty else 0
    df["Weight %"] = df["Value"] / total * 100 if total else None
    df["_total"]   = total
    return df


# ══════════════════════════════════════════════════════════════════════════════
# 5. CLAUDE — AI analysis
# ══════════════════════════════════════════════════════════════════════════════

def build_prompt(df: pd.DataFrame, news: dict, indices: dict) -> str:
    total = df["_total"].iloc[0] if not df.empty else 0

    # Positions block
    pos_lines = []
    for _, r in df.iterrows():
        val  = f"${r['Value']:,.2f}"   if r["Value"]  else "N/A"
        wt   = f"{r['Weight %']:.1f}%" if r["Weight %"] is not None else "N/A"
        day  = f"{r['Day %']:+.2f}%"   if r["Day %"]  is not None else "N/A"
        pnl  = f"${r['P&L $']:+,.2f} ({r['P&L %']:+.1f}%)" if r["P&L $"] is not None else "N/A"
        pos_lines.append(
            f"  • {r['Ticker']} ({r['Name']}): Valor={val} | Peso={wt} | Hoy={day} | P&L no realizado={pnl}"
        )

    # Indices block
    idx_lines = [
        f"  • {name}: {p['price']:.2f} ({p['change_pct']:+.2f}% hoy)"
        for ticker, name in MARKET_INDICES.items()
        if (p := indices.get(ticker))
    ]

    # News block
    news_lines = []
    for t, articles in news.items():
        if articles:
            news_lines.append(f"\n  [{t}]")
            for a in articles:
                news_lines.append(f"    - [{a['published']}] {a['title']} ({a['publisher']})")

    return f"""Eres un gestor de portafolios profesional con experiencia en gestión de activos institucionales.
Genera el análisis diario del portafolio del {TODAY.strftime('%d de %B de %Y')} en español.

═══════════════════════════════════════
PORTAFOLIO  (Valor Total: ${total:,.2f} {BASE_CCY})
═══════════════════════════════════════
{chr(10).join(pos_lines) if pos_lines else "  (Sin posiciones)"}

═══════════════════════════════════════
MERCADOS HOY
═══════════════════════════════════════
{chr(10).join(idx_lines) if idx_lines else "  (No disponible)"}

═══════════════════════════════════════
NOTICIAS RELEVANTES (últimas 24h)
═══════════════════════════════════════
{chr(10).join(news_lines) if news_lines else "  (Sin noticias)"}

═══════════════════════════════════════

Genera un análisis diario profesional con EXACTAMENTE estas secciones y encabezados:

## 📊 RESUMEN EJECUTIVO
[2-3 oraciones sobre el estado del portafolio hoy. Menciona el P&L del día y contexto general.]

## 🌍 CONTEXTO DE MERCADO
[Análisis del entorno macro y cómo los movimientos del mercado de hoy afectan específicamente este portafolio.]

## 🔍 ANÁLISIS POR POSICIÓN
[Para cada posición con noticias: qué pasó, por qué importa, implicación concreta para el portafolio. Omite posiciones sin noticias relevantes.]

## ⚡ OPORTUNIDADES IDENTIFICADAS
[3 puntos concretos y accionables basados en los datos de hoy]

## ⚠️ RIESGOS A VIGILAR
[3 riesgos específicos con catalizadores concretos para los próximos días]

## 🎯 ACCIONES SUGERIDAS
[3 acciones concretas: comprar / vender / rebalancear / mantener con justificación específica y niveles de precio si aplica]

## 💡 CONCLUSIÓN
[1-2 oraciones de cierre con la perspectiva general]

Reglas: sé específico, usa los datos del portafolio, referencia noticias concretas, evita generalidades.
Tono: profesional e institucional, estilo Bloomberg Intelligence."""


def run_ai_analysis(prompt: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return "⚠️ GEMINI_API_KEY no configurada — análisis no disponible."
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        return response.text
    except Exception as exc:
        return f"⚠️ Error al llamar a Gemini API: {exc}"


# ══════════════════════════════════════════════════════════════════════════════
# 6. PDF GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def generate_pdf(df: pd.DataFrame, analysis: str, news: dict, indices: dict) -> bytes:
    from reportlab.lib import colors as rlc
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_JUSTIFY, TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph,
        Spacer, HRFlowable, PageBreak,
    )

    # ── Palette ──────────────────────────────────────────────────────────────
    NAVY      = rlc.HexColor("#0b1729")
    GOLD      = rlc.HexColor("#f3a712")
    LGRAY     = rlc.HexColor("#f4f5f7")
    MGRAY     = rlc.HexColor("#888888")
    DARK      = rlc.HexColor("#1a1a1a")
    GREEN     = rlc.HexColor("#1a7a1a")
    RED       = rlc.HexColor("#cc2020")
    DIVIDER   = rlc.HexColor("#dddddd")

    def S(name, **kw):
        return ParagraphStyle(name, **kw)

    s_body    = S("sb",   fontName="Helvetica",      fontSize=9,  textColor=DARK,  leading=13, spaceAfter=3, alignment=TA_JUSTIFY)
    s_bullet  = S("sbul", fontName="Helvetica",      fontSize=9,  textColor=DARK,  leading=13, spaceAfter=3, leftIndent=14)
    s_section = S("ss",   fontName="Helvetica-Bold", fontSize=11, textColor=NAVY,  leading=14, spaceBefore=12, spaceAfter=4)
    s_note    = S("sn",   fontName="Helvetica-Oblique", fontSize=7.5, textColor=MGRAY, leading=10, alignment=TA_CENTER)
    s_hdr_l   = S("shl",  fontName="Helvetica-Bold", fontSize=20, textColor=rlc.white, leading=24)
    s_hdr_r   = S("shr",  fontName="Helvetica-Bold", fontSize=11, textColor=GOLD,  leading=14, alignment=TA_RIGHT)
    s_mlabel  = S("sml",  fontName="Helvetica",      fontSize=7.5, textColor=MGRAY, leading=10, alignment=TA_CENTER)
    s_mval    = S("smv",  fontName="Helvetica-Bold", fontSize=13, textColor=DARK,  leading=16, alignment=TA_CENTER)
    s_msub    = S("sms",  fontName="Helvetica",      fontSize=8,  textColor=MGRAY, leading=10, alignment=TA_CENTER)
    s_ticker  = S("stk",  fontName="Helvetica-Bold", fontSize=10, textColor=NAVY,  leading=13, spaceBefore=8, spaceAfter=3)
    s_news    = S("snws", fontName="Helvetica",      fontSize=8.5, textColor=DARK, leading=12, leftIndent=10, spaceAfter=5)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=1.5*cm, bottomMargin=2*cm,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
    )
    story = []
    total = df["_total"].iloc[0] if not df.empty else 0

    # ── Header bar ────────────────────────────────────────────────────────────
    hdr = Table([[
        Paragraph("PORTFOLIO  <font color='#f3a712'>DAILY BRIEF</font>", s_hdr_l),
        Paragraph(
            f"{TODAY.strftime('%d %b %Y').upper()}<br/>"
            f"<font size='9'>{TODAY.strftime('%A')}</font>",
            s_hdr_r
        ),
    ]], colWidths=["72%", "28%"])
    hdr.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), NAVY),
        ("LEFTPADDING",  (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING",   (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 14),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 8))

    # ── KPI strip ─────────────────────────────────────────────────────────────
    n_pos   = len(df)
    day_pnl = sum(
        (r["Value"] or 0) * (r["Day %"] or 0) / 100
        for _, r in df.iterrows()
        if r["Value"] and r["Day %"] is not None
    )
    total_pnl = df["P&L $"].sum() if "P&L $" in df and df["P&L $"].notna().any() else None
    day_sign  = "+" if day_pnl >= 0 else ""

    def kpi_cell(label, val_str, sub_str=""):
        inner = [
            Paragraph(label, s_mlabel),
            Paragraph(val_str, s_mval),
        ]
        if sub_str:
            inner.append(Paragraph(sub_str, s_msub))
        return inner

    kpi_data = [[
        kpi_cell("VALOR TOTAL",       f"${total:,.2f} {BASE_CCY}"),
        kpi_cell("P&L HOY",           f"{day_sign}${abs(day_pnl):,.2f}",
                 f"{day_sign}{day_pnl/total*100:.2f}%" if total else ""),
        kpi_cell("P&L NO REALIZADO",  f"${total_pnl:+,.2f}" if total_pnl is not None else "—"),
        kpi_cell("POSICIONES",        str(n_pos)),
        kpi_cell("GENERADO",          NOW.strftime("%H:%M UTC")),
    ]]
    kpi_table = Table(kpi_data, colWidths=["20%"]*5)
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), LGRAY),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("LINEAFTER",    (0, 0), (3, -1), 0.5, DIVIDER),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 10))

    # ── Holdings table ────────────────────────────────────────────────────────
    story.append(Paragraph("POSICIONES", s_section))

    COL_W = [1.4*cm, 4.2*cm, 1.0*cm, 2.0*cm, 2.3*cm, 1.5*cm, 1.7*cm, 1.7*cm, 2.2*cm]
    t_hdrs = ["Ticker", "Nombre", "Divisa", "Precio", "Valor", "Peso", "Hoy%", "P&L%", "P&L$"]
    t_rows = [t_hdrs]

    for _, r in df.iterrows():
        t_rows.append([
            r["Ticker"],
            str(r["Name"])[:24],
            r["Currency"],
            f"${r['Price']:.2f}"        if r["Price"]   else "—",
            f"${r['Value']:,.2f}"       if r["Value"]   else "—",
            f"{r['Weight %']:.1f}%"     if r["Weight %"] is not None else "—",
            f"{r['Day %']:+.2f}%"       if r["Day %"]   is not None else "—",
            f"{r['P&L %']:+.1f}%"       if r["P&L %"]   is not None else "—",
            f"${r['P&L $']:+,.2f}"      if r["P&L $"]   is not None else "—",
        ])

    ts = [
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), rlc.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("ALIGN",         (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN",         (0, 0), (1, -1), "LEFT"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [rlc.white, LGRAY]),
        ("GRID",          (0, 0), (-1, -1), 0.25, DIVIDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]
    # Color code Day% and P&L% columns
    for i, (_, r) in enumerate(df.iterrows(), 1):
        for col_idx, val in [(6, r["Day %"]), (7, r["P&L %"]), (8, r["P&L $"])]:
            if val is not None:
                ts.append(("TEXTCOLOR", (col_idx, i), (col_idx, i), GREEN if val >= 0 else RED))

    htable = Table(t_rows, colWidths=COL_W, repeatRows=1)
    htable.setStyle(TableStyle(ts))
    story.append(htable)
    story.append(Spacer(1, 10))

    # ── Market Indices ────────────────────────────────────────────────────────
    story.append(Paragraph("MERCADOS", s_section))

    idx_rows = [["Índice", "Precio", "Cambio"]]
    for ticker, name in MARKET_INDICES.items():
        p = indices.get(ticker)
        if not p:
            continue
        idx_rows.append([name, f"{p['price']:,.2f}", f"{p['change_pct']:+.2f}%"])

    if len(idx_rows) > 1:
        idx_ts = [
            ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR",     (0, 0), (-1, 0), rlc.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
            ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [rlc.white, LGRAY]),
            ("GRID",          (0, 0), (-1, -1), 0.25, DIVIDER),
        ]
        for i, (ticker, _) in enumerate(
            [(t, n) for t, n in MARKET_INDICES.items() if t in indices], 1
        ):
            chg = indices[ticker]["change_pct"]
            idx_ts.append(("TEXTCOLOR", (2, i), (2, i), GREEN if chg >= 0 else RED))

        idx_table = Table(idx_rows, colWidths=[6*cm, 3*cm, 3*cm])
        idx_table.setStyle(TableStyle(idx_ts))
        story.append(idx_table)

    story.append(PageBreak())

    # ── AI Analysis ───────────────────────────────────────────────────────────
    story.append(Paragraph("ANÁLISIS IA · CLAUDE", s_section))
    story.append(HRFlowable(width="100%", thickness=1.5, color=GOLD, spaceAfter=8))

    for line in analysis.split("\n"):
        line = line.rstrip()
        if not line:
            story.append(Spacer(1, 3))
            continue
        # Escape XML special chars
        safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if line.startswith("## "):
            story.append(Paragraph(safe[3:].strip(), s_section))
        elif line.startswith(("- ", "• ")):
            story.append(Paragraph(f"• {safe[2:].strip()}", s_bullet))
        else:
            story.append(Paragraph(safe, s_body))

    story.append(Spacer(1, 12))

    # ── News by ticker ────────────────────────────────────────────────────────
    has_news = any(v for v in news.values())
    if has_news:
        story.append(Paragraph("NOTICIAS POR POSICIÓN", s_section))
        story.append(HRFlowable(width="100%", thickness=1.5, color=GOLD, spaceAfter=8))

        for ticker, articles in news.items():
            if not articles:
                continue
            story.append(Paragraph(ticker, s_ticker))
            for a in articles:
                title = a["title"].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                pub   = a.get("publisher", "")
                dt    = a.get("published", "")
                story.append(Paragraph(
                    f"<b>{title}</b><br/>"
                    f"<font color='#888888' size='7'>{pub}  ·  {dt}</font>",
                    s_news
                ))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MGRAY))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Generado el {NOW.strftime('%d/%m/%Y %H:%M UTC')}  ·  Portfolio Tracker  ·  Análisis por Gemini 2.0 Flash (Google)",
        s_note
    ))

    doc.build(story)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# 7. TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

def send_telegram(pdf_bytes: bytes, caption: str) -> bool:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id   = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not bot_token or not chat_id:
        print("[WARN] Telegram credentials missing — skipping send")
        return False

    try:
        import requests
        filename = f"portfolio_brief_{TODAY.strftime('%Y%m%d')}.pdf"
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendDocument",
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"document": (filename, pdf_bytes, "application/pdf")},
            timeout=30,
        )
        data = resp.json()
        if resp.status_code == 200 and data.get("ok"):
            print(f"[Telegram] Sent: {filename}")
            return True
        print(f"[ERROR] Telegram API: {resp.text}")
        return False
    except Exception as exc:
        print(f"[ERROR] Telegram send: {exc}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 8. MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"\n{'='*60}")
    print(f"  PORTFOLIO DAILY REPORT  ·  {TODAY}  ·  {NOW.strftime('%H:%M')} UTC")
    print(f"{'='*60}\n")

    # ── 1. Portfolio ──────────────────────────────────────────────────────────
    print("[1/7] Loading portfolio from Google Sheets...")
    positions = load_portfolio()
    if positions.empty:
        print("[ABORT] No positions found. Exiting.")
        return
    tickers = positions["Ticker"].tolist()
    print(f"       {len(tickers)} positions: {', '.join(tickers)}")

    # ── 2. Prices ─────────────────────────────────────────────────────────────
    print("[2/7] Fetching prices...")
    all_tickers  = tickers + list(MARKET_INDICES.keys())
    all_prices   = fetch_prices(all_tickers)
    port_prices  = {t: all_prices[t] for t in tickers  if t in all_prices}
    index_prices = {t: all_prices[t] for t in MARKET_INDICES if t in all_prices}
    print(f"       Got prices for {len(port_prices)}/{len(tickers)} portfolio tickers")

    # ── 3. Currencies ─────────────────────────────────────────────────────────
    print("[3/7] Fetching ticker currencies...")
    currencies = fetch_currencies(tickers)

    # ── 4. Build summary ──────────────────────────────────────────────────────
    print("[4/7] Building portfolio summary...")
    df = build_summary(positions, port_prices, currencies)
    total = df["_total"].iloc[0] if not df.empty else 0
    print(f"       Total portfolio value: ${total:,.2f} {BASE_CCY}")

    # ── 5. News ───────────────────────────────────────────────────────────────
    print("[5/7] Fetching news per ticker...")
    news = fetch_news(tickers, max_per_ticker=3)
    n_articles = sum(len(v) for v in news.values())
    print(f"       {n_articles} news articles fetched")

    # ── 6. Claude analysis ────────────────────────────────────────────────────
    print("[6/7] Calling Claude for AI analysis...")
    prompt   = build_prompt(df, news, index_prices)
    analysis = run_ai_analysis(prompt)
    print(f"       Analysis: {len(analysis)} characters")

    # ── 7. PDF ────────────────────────────────────────────────────────────────
    print("[7/7] Generating PDF...")
    pdf_bytes = generate_pdf(df, analysis, news, index_prices)
    out_path  = f"/tmp/portfolio_brief_{TODAY.strftime('%Y%m%d')}.pdf"
    with open(out_path, "wb") as f:
        f.write(pdf_bytes)
    print(f"       PDF saved: {out_path} ({len(pdf_bytes):,} bytes)")

    # ── Telegram ──────────────────────────────────────────────────────────────
    day_pnl = sum(
        (r["Value"] or 0) * (r["Day %"] or 0) / 100
        for _, r in df.iterrows()
        if r["Value"] and r["Day %"] is not None
    )
    sign = "📈" if day_pnl >= 0 else "📉"
    caption = (
        f"<b>{sign} Portfolio Daily Brief — {TODAY.strftime('%d %b %Y')}</b>\n\n"
        f"💼 Valor: <b>${total:,.2f} {BASE_CCY}</b>\n"
        f"{sign} P&amp;L hoy: <b>${day_pnl:+,.2f}</b>\n"
        f"📊 {len(tickers)} posiciones · {n_articles} noticias analizadas\n\n"
        f"<i>Análisis por Gemini 2.0 Flash · Portfolio Tracker</i>"
    )
    send_telegram(pdf_bytes, caption)

    print("\n[DONE] Report complete.\n")


if __name__ == "__main__":
    main()
