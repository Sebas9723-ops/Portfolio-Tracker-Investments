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
  GROQ_API_KEY               Groq API key (free at console.groq.com)
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
    "GBPUSD=X": "GBP/USD",
}

# FX tickers that should NOT appear in the market indices display section
_FX_TICKERS = {"EURUSD=X", "GBPUSD=X"}


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
    Load portfolio positions with Shares and AvgCost.
    Primary source: Google Sheets (always up-to-date with transactions).
    Fallback: PORTFOLIO_JSON env var (GitHub Secret).
    Returns DataFrame: Ticker | Name | Shares | AvgCost
    """
    df = _load_from_sheets()
    if not df.empty:
        print(f"[Portfolio] Loaded {len(df)} positions from Google Sheets")
        return df

    print("[WARN] Sheets unavailable, falling back to PORTFOLIO_JSON")
    df = _load_from_portfolio_json()
    if df.empty:
        print("[WARN] PORTFOLIO_JSON also returned no positions")
    else:
        print(f"[Portfolio] Loaded {len(df)} positions from PORTFOLIO_JSON")
    return df


def _load_from_sheets() -> pd.DataFrame:
    """Load Ticker, Name, Shares, AvgCost from the private_positions Google Sheet."""
    creds_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "")
    sheet_id   = os.environ.get("SHEETS_SPREADSHEET_ID", "")
    ws_name    = os.environ.get("SHEETS_WORKSHEET", "private_positions")

    if not creds_json or not sheet_id:
        print("[Sheets] GCP_SERVICE_ACCOUNT_JSON or SHEETS_SPREADSHEET_ID not set")
        return pd.DataFrame()
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_json = _repair_json(creds_json)
        creds_dict = json.loads(creds_json)
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

        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly",
                  "https://www.googleapis.com/auth/drive.readonly"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        ws = gc.open_by_key(sheet_id).worksheet(ws_name)
        records = ws.get_all_records(value_render_option="UNFORMATTED_VALUE")
        df = pd.DataFrame(records)

        if df.empty or "Ticker" not in df.columns:
            print("[Sheets] Empty or missing Ticker column")
            return pd.DataFrame()

        df["Shares"]  = pd.to_numeric(df.get("Shares",  0), errors="coerce").fillna(0)
        df["AvgCost"] = pd.to_numeric(df.get("AvgCost", 0), errors="coerce").fillna(0)
        df["Ticker"]  = df["Ticker"].astype(str).str.strip()
        df["Name"]    = df.get("Name", df["Ticker"]).fillna(df["Ticker"]).astype(str)

        # Only positions with shares
        df = df[df["Shares"] > 0].copy()
        if df.empty:
            print("[Sheets] No positions with Shares > 0")
            return pd.DataFrame()

        print(f"[Sheets] {len(df)} positions: {', '.join(df['Ticker'].tolist())}")
        return df[["Ticker", "Name", "Shares", "AvgCost"]].reset_index(drop=True)

    except Exception as exc:
        print(f"[WARN] Sheets load failed: {exc}")
        return pd.DataFrame()


def _load_from_portfolio_json() -> pd.DataFrame:
    """Load portfolio from PORTFOLIO_JSON env var (GitHub Secret). Fallback only."""
    raw = os.environ.get("PORTFOLIO_JSON", "")
    if not raw:
        print("[WARN] PORTFOLIO_JSON secret not set")
        return pd.DataFrame(columns=["Ticker", "Name", "Shares", "AvgCost"])
    try:
        data = json.loads(raw)
        rows = [
            {"Ticker": p["ticker"], "Name": p.get("name", p["ticker"]),
             "Shares": float(p.get("shares", 0)), "AvgCost": float(p.get("avg_cost", 0))}
            for p in data
            if float(p.get("shares", 0)) > 0
        ]
        return pd.DataFrame(rows)
    except Exception as exc:
        print(f"[WARN] Could not parse PORTFOLIO_JSON: {exc}")
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
        raw = yf.download(tickers, period="10d", auto_adjust=True,
                          progress=False, group_by="column")
        if raw.empty:
            raise ValueError("Empty response from yfinance bulk download")

        # Normalize to a DataFrame with tickers as columns
        # Handle both (PriceType, Ticker) and (Ticker, PriceType) MultiIndex layouts
        if isinstance(raw.columns, pd.MultiIndex):
            lvl0 = raw.columns.get_level_values(0).unique().tolist()
            lvl1 = raw.columns.get_level_values(1).unique().tolist()
            if "Close" in lvl0:
                close = raw["Close"]                        # (PriceType, Ticker)
            elif "Close" in lvl1:
                close = raw.xs("Close", axis=1, level=1)   # (Ticker, PriceType)
            else:
                raise ValueError(f"Close not found in MultiIndex levels: {lvl0[:5]}")
        else:
            # Single ticker: flat columns
            close = raw[["Close"]].rename(columns={"Close": tickers[0]})

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
        print(f"[WARN] Bulk price fetch failed ({exc}), falling back to per-ticker...")

    # Per-ticker fallback (uses Ticker.history — more reliable than yf.download)
    missing = [t for t in tickers if t not in results]
    for t in missing:
        try:
            hist = yf.Ticker(t).history(period="10d", auto_adjust=True)
            if hist.empty:
                print(f"[WARN] No history for {t}")
                continue
            s = hist["Close"].dropna()
            if len(s) < 2:
                print(f"[WARN] Less than 2 data points for {t}")
                continue
            price = float(s.iloc[-1])
            prev  = float(s.iloc[-2])
            results[t] = {
                "price":      price,
                "prev_close": prev,
                "change_pct": (price - prev) / prev * 100 if prev else 0.0,
            }
            print(f"[Fallback] {t} price={price:.2f}")
        except Exception as exc2:
            print(f"[WARN] Price fetch failed for {t}: {exc2}")
        time.sleep(0.1)

    return results


_SUFFIX_CCY = {
    # European exchanges → EUR
    ".DE": "EUR", ".AS": "EUR", ".PA": "EUR", ".MI": "EUR",
    ".MC": "EUR", ".BR": "EUR", ".VI": "EUR", ".HE": "EUR",
    # NOTE: .L (LSE) intentionally omitted — some LSE stocks (e.g. IGLN.L)
    # quote in USD, so we let yfinance fast_info determine the currency.
    # Other
    ".TO": "CAD", ".AX": "AUD", ".HK": "HKD",
}

# Tickers whose yfinance currency differs from their exchange convention
_CURRENCY_OVERRIDE = {
    "IGLN.L": "USD",   # iShares Physical Gold ETC — quoted in USD on LSE
}


def fetch_currencies(tickers: list[str]) -> dict:
    """Return {ticker: currency} using exchange-suffix lookup (deterministic).
    Falls back to yfinance fast_info only for tickers with no known suffix."""
    info = {}
    unknown = []
    for t in tickers:
        matched = next((ccy for sfx, ccy in _SUFFIX_CCY.items()
                        if t.upper().endswith(sfx.upper())), None)
        if matched:
            info[t] = matched
        else:
            unknown.append(t)

    # Only call yfinance for tickers without a known exchange suffix
    for t in unknown:
        try:
            fi = yf.Ticker(t).fast_info
            info[t] = getattr(fi, "currency", "USD") or "USD"
        except Exception:
            info[t] = "USD"
        time.sleep(0.05)

    # Apply overrides last (highest priority)
    info.update({t: ccy for t, ccy in _CURRENCY_OVERRIDE.items() if t in tickers})

    print(f"[Currencies] {info}")
    return info


# ══════════════════════════════════════════════════════════════════════════════
# 3. NEWS — per-ticker headlines via yfinance
# ══════════════════════════════════════════════════════════════════════════════

def fetch_news(tickers: list[str], max_per_ticker: int = 3) -> dict[str, list[dict]]:
    """Returns {ticker: [{title, publisher, published}]}.
    Handles both legacy and new yfinance news structure (content-nested).
    """
    news_map: dict[str, list[dict]] = {}
    for t in tickers:
        try:
            raw_news = yf.Ticker(t).news or []
            items = []
            for item in raw_news[:max_per_ticker]:
                # New yfinance structure: item["content"]["title"]
                content = item.get("content", {})
                if content:
                    title     = content.get("title", "")
                    publisher = content.get("provider", {}).get("displayName", "")
                    pub_date  = content.get("pubDate", "")
                    try:
                        dt = datetime.datetime.fromisoformat(
                            pub_date.replace("Z", "+00:00")
                        ).strftime("%b %d %H:%M") if pub_date else ""
                    except Exception:
                        dt = ""
                    link = content.get("canonicalUrl", {}).get("url", "") or item.get("link", "")
                else:
                    # Legacy flat structure
                    title     = item.get("title", "")
                    publisher = item.get("publisher", "")
                    ts        = item.get("providerPublishTime", 0)
                    dt        = datetime.datetime.utcfromtimestamp(ts).strftime("%b %d %H:%M") if ts else ""
                    link      = item.get("link", "")

                if not title:
                    continue
                items.append({
                    "title":     title,
                    "publisher": publisher,
                    "published": dt,
                    "link":      link,
                })
            news_map[t] = items
        except Exception as exc:
            print(f"[WARN] News fetch failed for {t}: {exc}")
            news_map[t] = []
        time.sleep(0.15)
    return news_map


# ══════════════════════════════════════════════════════════════════════════════
# 4. PORTFOLIO SUMMARY DataFrame
# ══════════════════════════════════════════════════════════════════════════════

def build_summary(positions: pd.DataFrame, prices: dict, currencies: dict,
                  fx_rates: dict | None = None) -> pd.DataFrame:
    """Enrich positions with live prices, P&L, and weight.
    fx_rates: {ticker: price} for FX pairs (e.g. EURUSD=X, GBPUSD=X).
    Values are converted to BASE_CCY (USD) using FX rates.
    """
    fx_rates = fx_rates or {}
    eur_usd = fx_rates.get("EURUSD=X", {}).get("price", 1.0) or 1.0
    gbp_usd = fx_rates.get("GBPUSD=X", {}).get("price", 1.0) or 1.0
    print(f"[FX] EUR/USD={eur_usd:.4f}  GBP/USD={gbp_usd:.4f}")

    def to_usd(amount: float, ccy: str) -> float:
        if ccy == "EUR":
            return amount * eur_usd
        if ccy in ("GBP", "GBp"):   # GBp = pence (London)
            return amount * gbp_usd / (100 if ccy == "GBp" else 1)
        return amount  # USD or unknown → assume USD

    rows = []
    for _, pos in positions.iterrows():
        ticker   = str(pos["Ticker"]).strip()
        name     = str(pos.get("Name", ticker))
        shares   = float(pos.get("Shares",  0))
        avg_cost = float(pos.get("AvgCost", 0))
        p        = prices.get(ticker, {})
        price    = p.get("price")       # price in native currency
        chg      = p.get("change_pct")
        ccy      = currencies.get(ticker, "USD")

        # Convert native-currency value to USD
        value_native = shares * price if price is not None else None
        value        = to_usd(value_native, ccy) if value_native is not None else None
        vn_str = f"{value_native:.2f}" if value_native is not None else "N/A"
        v_str  = f"{value:.2f}"        if value        is not None else "N/A"
        print(f"  [{ticker}] ccy={ccy} price={price} shares={shares} "
              f"native={vn_str} usd={v_str}")

        # avg_cost is in native currency — convert to USD for consistent P&L
        cost_native = shares * avg_cost if avg_cost else None
        cost        = to_usd(cost_native, ccy) if cost_native is not None else None
        pnl         = value - cost if (value is not None and cost is not None) else None
        pnl_pct     = pnl / cost * 100 if (pnl is not None and cost and cost != 0) else None

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
        if ticker not in _FX_TICKERS and (p := indices.get(ticker))
    ]

    # News block
    news_lines = []
    for t, articles in news.items():
        if articles:
            news_lines.append(f"\n  [{t}]")
            for a in articles:
                news_lines.append(f"    - [{a['published']}] {a['title']} ({a['publisher']})")

    # Build per-position context with cost basis info
    pos_detail_lines = []
    for _, r in df.iterrows():
        val      = f"${r['Value']:,.2f}"      if r["Value"]  is not None else "N/A"
        wt       = f"{r['Weight %']:.1f}%"    if r["Weight %"] is not None else "N/A"
        day      = f"{r['Day %']:+.2f}%"      if r["Day %"]  is not None else "N/A"
        pnl_str  = (f"${r['P&L $']:+,.2f} ({r['P&L %']:+.1f}%)"
                    if r["P&L $"] is not None else "sin costo base")
        avg      = f"${r['Avg Cost']:.2f}"    if r["Avg Cost"] is not None else "N/A"
        pos_detail_lines.append(
            f"  • {r['Ticker']} | {r['Name']} | Divisa: {r['Currency']}\n"
            f"    Valor: {val} ({wt} del portafolio) | Precio: ${r['Price']:.2f} | "
            f"Costo promedio: {avg}\n"
            f"    Rendimiento hoy: {day} | P&L no realizado: {pnl_str}"
        )

    # FX rates for context (included in indices dict)
    fx_lines = []
    for ticker in ("EURUSD=X", "GBPUSD=X"):
        if ticker in indices:
            p = indices[ticker]
            label = "EUR/USD" if "EUR" in ticker else "GBP/USD"
            fx_lines.append(f"  • {label}: {p['price']:.4f} ({p['change_pct']:+.2f}% hoy)")

    return f"""Eres un CFA charterholder con 15 años de experiencia en gestión de portafolios multi-activo institucionales.
Fecha de análisis: {TODAY.strftime('%d de %B de %Y')} ({TODAY.strftime('%A')}).

════════════════════════════════════════════
DATOS DEL PORTAFOLIO  —  Valor Total: ${total:,.2f} {BASE_CCY}
════════════════════════════════════════════
{chr(10).join(pos_detail_lines) if pos_detail_lines else "  (Sin posiciones)"}

════════════════════════════════════════════
MERCADOS HOY
════════════════════════════════════════════
{chr(10).join(idx_lines) if idx_lines else "  (No disponible)"}

  Divisas:
{chr(10).join(fx_lines) if fx_lines else "  (No disponible)"}

════════════════════════════════════════════
NOTICIAS RELEVANTES (últimas 24h)
════════════════════════════════════════════
{chr(10).join(news_lines) if news_lines else "  (Sin noticias disponibles de yfinance)"}

════════════════════════════════════════════

INSTRUCCIONES: Genera un análisis institucional profundo y accionable. Cada sección debe ser sustancial (no bullet points vacíos). Usa los datos numéricos del portafolio. Sé específico — menciona tickers, precios, porcentajes. Escribe en español profesional estilo Bloomberg Intelligence / Goldman Sachs Morning Brief.

## 📊 RESUMEN EJECUTIVO
Describe el estado actual del portafolio: valor total, P&L del día en dólares y porcentaje ponderado, posición ganadora y perdedora del día. Contextualiza en función de los índices. ¿El portafolio superó o quedó por debajo del S&P 500 hoy?

## 🌍 CONTEXTO MACROECONÓMICO
Analiza: (1) qué señala el VIX sobre el sentimiento de riesgo, (2) qué implica el movimiento del 10Y yield para la renta fija y acciones growth, (3) el movimiento del USD/EUR para las posiciones europeas, (4) correlación del portafolio con el entorno macro de hoy. Sé específico con los niveles numéricos.

## 🔍 ANÁLISIS POR POSICIÓN
Para CADA posición del portafolio: (a) rendimiento del día en contexto, (b) noticias que lo explican si las hay, (c) implicación concreta para mantener/revisar esa posición, (d) si hay P&L disponible, evalúa si está en zona de ganancia/pérdida significativa. No omitas ninguna posición.

## 📈 ANÁLISIS DE ASIGNACIÓN Y DIVERSIFICACIÓN
Evalúa: (1) concentración por activo — ¿alguna posición domina demasiado?, (2) exposición geográfica (US vs Europa), (3) balance renta variable / renta fija / oro, (4) correlación implícita entre posiciones hoy, (5) si el portafolio tiene sesgos sectoriales o de factor (growth, value, dividend, momentum).

## ⚡ OPORTUNIDADES IDENTIFICADAS
3-4 oportunidades concretas y accionables con base en los datos de hoy. Para cada una: qué es la oportunidad, qué catalizador la activa, nivel de precio relevante o condición de entrada, y tamaño sugerido de ajuste.

## ⚠️ RIESGOS A VIGILAR
4-5 riesgos específicos con: (a) descripción del riesgo, (b) catalizador o evento que lo materializaría, (c) posición del portafolio más expuesta, (d) nivel o condición de alerta. Incluye riesgos macro, de liquidez, de divisa y específicos por activo.

## 🎯 PLAN DE ACCIÓN PARA LAS PRÓXIMAS 48 HORAS
Acciones concretas priorizadas: comprar / recortar / rebalancear / mantener. Para cada acción: ticker específico, dirección, justificación cuantitativa, nivel de precio o condición de ejecución, y tamaño sugerido como % del portafolio.

## 💡 PERSPECTIVA SEMANAL
Proyección para los próximos 5 días de trading: eventos clave a monitorear (datos macro, earnings, reuniones de bancos centrales), cómo podrían impactar cada posición, y el sesgo direccional recomendado (risk-on / risk-off / neutral).

Reglas: mínimo 600 palabras en total. Cero generalidades — cada afirmación debe estar anclada en un dato del portafolio o del mercado. Si no hay noticias para una posición, analiza su comportamiento de precio en contexto de mercado."""


def run_ai_analysis(prompt: str) -> str:
    """Call Groq LLM API for portfolio analysis."""
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return "⚠️ GROQ_API_KEY no configurada — análisis no disponible."
    try:
        from groq import Groq
        client = Groq(api_key=api_key)

        last_err = ""
        for model_name in (
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
        ):
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                )
                print(f"[Groq] Success with model: {model_name}")
                return response.choices[0].message.content
            except Exception as model_exc:
                last_err = str(model_exc)
                print(f"[Groq] {model_name} failed: {last_err[:200]}")
                continue  # always try next model

        return (
            "⚠️ Groq no respondió con ningún modelo.\n\n"
            f"Último error: {last_err[:300]}"
        )
    except Exception as exc:
        return f"⚠️ Error al importar groq SDK: {exc}\nInstala con: pip install groq"


def analyze_news_with_groq(news: dict) -> dict:
    """Call Groq to add a 2-3 sentence analysis to each news article.
    Returns the same news dict with an 'analysis' key added per article.
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return news

    # Flatten all articles with a global index
    flat: list[tuple[str, dict]] = []
    for ticker, articles in news.items():
        for a in articles:
            if a.get("title"):
                flat.append((ticker, a))

    if not flat:
        return news

    numbered = "\n".join(
        f"[{i}] [{ticker}] \"{a['title']}\" — {a.get('publisher', '')} ({a.get('published', '')})"
        for i, (ticker, a) in enumerate(flat)
    )

    prompt = f"""Eres un analista financiero de renta variable y renta fija.
Para cada noticia abajo, escribe UN PÁRRAFO CORTO (2-3 oraciones en español) que explique:
1. Qué ocurrió exactamente
2. Por qué importa para ese activo / sector
3. Qué implicación tiene para un inversor

Responde ÚNICAMENTE con líneas en este formato exacto, una por noticia, sin texto adicional:
[índice] Análisis aquí.

NOTICIAS:
{numbered}"""

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content or ""

        # Parse [index] analysis lines
        analyses: dict[int, str] = {}
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("[") and "]" in line:
                try:
                    idx = int(line[1:line.index("]")])
                    body = line[line.index("]") + 1:].strip()
                    if body:
                        analyses[idx] = body
                except ValueError:
                    pass

        # Write analysis back into the news dict (deep copy to avoid mutation issues)
        result: dict[str, list[dict]] = {t: [dict(a) for a in arts] for t, arts in news.items()}
        t_idx: dict[str, int] = {t: 0 for t in news}
        for i, (ticker, orig) in enumerate(flat):
            for a in result[ticker]:
                if a.get("title") == orig.get("title") and "analysis" not in a:
                    a["analysis"] = analyses.get(i, "")
                    break

        print(f"[Groq News] Analysed {len(analyses)}/{len(flat)} articles")
        return result

    except Exception as exc:
        print(f"[WARN] News analysis with Groq failed: {exc}")
        return news


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

    # Total usable width: 21cm - 2*(1.8cm margins) = 17.4cm
    COL_W = [1.5*cm, 3.8*cm, 1.0*cm, 2.0*cm, 2.3*cm, 1.4*cm, 1.5*cm, 1.7*cm, 2.2*cm]
    t_hdrs = ["Ticker", "Nombre", "Div", "Precio", "Valor", "Peso", "Hoy%", "P&L%", "P&L$"]
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
        if ticker in _FX_TICKERS:
            continue
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
            [(t, n) for t, n in MARKET_INDICES.items()
             if t in indices and t not in _FX_TICKERS], 1
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
                def _xe(s: str) -> str:
                    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

                title    = _xe(a.get("title", ""))
                pub      = _xe(a.get("publisher", ""))
                dt       = a.get("published", "")
                analysis = _xe(a.get("analysis", ""))
                link     = a.get("link", "").replace("&", "&amp;")

                # Title: clickable link if URL available
                if link:
                    title_part = (
                        f'<link href="{link}">'
                        f'<font color="#1a5fb4"><u>{title}</u></font>'
                        f'</link>'
                    )
                else:
                    title_part = f"<b>{title}</b>"

                meta = f"<font color='#888888' size='7'>{pub}  ·  {dt}</font>"

                if analysis:
                    body = (
                        f"{title_part}<br/>"
                        f"{meta}<br/>"
                        f"<font color='#333333' size='8'>{analysis}</font>"
                    )
                else:
                    body = f"{title_part}<br/>{meta}"

                story.append(Paragraph(body, s_news))
                story.append(Spacer(1, 4))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MGRAY))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Generado el {NOW.strftime('%d/%m/%Y %H:%M UTC')}  ·  Portfolio Tracker  ·  Análisis por Llama 3.3 70B (Groq)",
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
    print("[1/8] Loading portfolio from Google Sheets...")
    positions = load_portfolio()
    if positions.empty:
        print("[ABORT] No positions found. Exiting.")
        return
    tickers = positions["Ticker"].tolist()
    print(f"       {len(tickers)} positions: {', '.join(tickers)}")

    # ── 2. Prices ─────────────────────────────────────────────────────────────
    print("[2/8] Fetching prices...")
    all_tickers  = tickers + list(MARKET_INDICES.keys())
    all_prices   = fetch_prices(all_tickers)
    port_prices  = {t: all_prices[t] for t in tickers  if t in all_prices}
    index_prices = {t: all_prices[t] for t in MARKET_INDICES if t in all_prices}
    print(f"       Got prices for {len(port_prices)}/{len(tickers)} portfolio tickers")

    # ── 3. Currencies ─────────────────────────────────────────────────────────
    print("[3/8] Fetching ticker currencies...")
    currencies = fetch_currencies(tickers)

    # ── 4. Build summary ──────────────────────────────────────────────────────
    print("[4/8] Building portfolio summary...")
    fx_rates = {t: all_prices[t] for t in ("EURUSD=X", "GBPUSD=X") if t in all_prices}
    df = build_summary(positions, port_prices, currencies, fx_rates=fx_rates)
    total = df["_total"].iloc[0] if not df.empty else 0
    print(f"       Total portfolio value: ${total:,.2f} {BASE_CCY}")

    # ── 5. News ───────────────────────────────────────────────────────────────
    print("[5/8] Fetching news per ticker...")
    news = fetch_news(tickers, max_per_ticker=3)
    n_articles = sum(len(v) for v in news.values())
    print(f"       {n_articles} news articles fetched")

    # ── 6. News analysis ──────────────────────────────────────────────────────
    print("[6/8] Analysing news with Groq...")
    news = analyze_news_with_groq(news)

    # ── 7. Portfolio analysis ─────────────────────────────────────────────────
    print("[7/8] Calling Groq for portfolio analysis...")
    prompt   = build_prompt(df, news, index_prices)
    analysis = run_ai_analysis(prompt)
    print(f"       Analysis: {len(analysis)} characters")

    # ── 8. PDF ────────────────────────────────────────────────────────────────
    print("[8/8] Generating PDF...")
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
        f"<i>Análisis por Llama 3.3 70B · Portfolio Tracker</i>"
    )
    send_telegram(pdf_bytes, caption)

    print("\n[DONE] Report complete.\n")


if __name__ == "__main__":
    main()
