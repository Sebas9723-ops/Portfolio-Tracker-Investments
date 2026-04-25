"""
AI portfolio analysis via Groq (Llama 3.3 70B).
Generates a CFA-level daily brief in Spanish sent via Telegram.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

log = logging.getLogger(__name__)

_MARKET_INDICES = {
    "^GSPC":   "S&P 500",
    "^IXIC":   "Nasdaq",
    "^VIX":    "VIX",
    "^TNX":    "10Y Yield",
    "GC=F":    "Gold",
    "BTC-USD": "Bitcoin",
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
}


def _fetch_indices() -> dict:
    """Fetch today's market index prices via yfinance."""
    try:
        import yfinance as yf
        import time
        results = {}
        tickers = list(_MARKET_INDICES.keys())
        try:
            import pandas as pd
            raw = yf.download(tickers, period="5d", auto_adjust=True, progress=False)
            if not raw.empty and isinstance(raw.columns, pd.MultiIndex):
                close = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw.xs("Close", axis=1, level=1)
                for t in tickers:
                    if t in close.columns:
                        s = close[t].dropna()
                        if len(s) >= 2:
                            results[t] = {"price": float(s.iloc[-1]), "change_pct": (float(s.iloc[-1]) - float(s.iloc[-2])) / float(s.iloc[-2]) * 100}
        except Exception:
            pass
        # fallback per-ticker
        for t in tickers:
            if t not in results:
                try:
                    h = yf.Ticker(t).history(period="5d")
                    if not h.empty and len(h) >= 2:
                        results[t] = {"price": float(h["Close"].iloc[-1]), "change_pct": (float(h["Close"].iloc[-1]) - float(h["Close"].iloc[-2])) / float(h["Close"].iloc[-2]) * 100}
                    time.sleep(0.05)
                except Exception:
                    pass
        return results
    except Exception as exc:
        log.warning("Index fetch failed: %s", exc)
        return {}


def build_analysis_prompt(summary, metrics: dict, base_currency: str = "USD") -> str:
    """Build the Groq prompt from portfolio summary and performance metrics."""
    today = date.today()
    total = summary.total_value_base
    invested = summary.total_invested_base or 0.0
    pnl = summary.total_unrealized_pnl or 0.0
    day_change = summary.total_day_change_base or 0.0
    day_pct = (day_change / (total - day_change) * 100) if (total - day_change) > 0 else 0.0

    sharpe = metrics.get("sharpe") or 0.0
    ann_vol = (metrics.get("annualized_vol") or 0.0) * 100
    max_dd = (metrics.get("max_drawdown") or 0.0) * 100
    alpha = (metrics.get("alpha") or 0.0) * 100
    beta = metrics.get("beta") or 0.0
    ann_return = (metrics.get("annualized_return") or 0.0) * 100
    twr = metrics.get("twr") or 0.0

    # Positions block
    pos_lines = []
    for r in summary.rows:
        pnl_r = r.unrealized_pnl or 0.0
        pnl_pct_r = r.unrealized_pnl_pct or 0.0
        day_r = r.change_pct_1d or 0.0
        pos_lines.append(
            f"  • {r.ticker} ({r.name}): Valor={base_currency} {r.value_base:,.2f} | "
            f"Peso={r.weight:.1f}% | Hoy={day_r:+.2f}% | "
            f"P&L no realizado={base_currency} {pnl_r:+,.2f} ({pnl_pct_r:+.1f}%) | "
            f"Costo promedio={r.avg_cost_native:.2f} {r.cost_currency}"
        )

    # Market indices
    indices = _fetch_indices()
    idx_lines = []
    for ticker, name in _MARKET_INDICES.items():
        if ticker in ("EURUSD=X", "GBPUSD=X"):
            continue
        if ticker in indices:
            idx_lines.append(f"  • {name}: {indices[ticker]['price']:.2f} ({indices[ticker]['change_pct']:+.2f}% hoy)")

    fx_lines = []
    for ticker, label in [("EURUSD=X", "EUR/USD"), ("GBPUSD=X", "GBP/USD")]:
        if ticker in indices:
            fx_lines.append(f"  • {label}: {indices[ticker]['price']:.4f} ({indices[ticker]['change_pct']:+.2f}% hoy)")

    return f"""Eres un CFA charterholder con 15 años de experiencia en gestión de portafolios multi-activo institucionales.
Fecha de análisis: {today.strftime('%d de %B de %Y')} ({today.strftime('%A')}).

════════════════════════════════════════════
DATOS DEL PORTAFOLIO — Valor Total: {base_currency} {total:,.2f}
════════════════════════════════════════════
Capital invertido: {base_currency} {invested:,.2f}
P&L no realizado total: {base_currency} {pnl:+,.2f}
Cambio del día: {base_currency} {day_change:+,.2f} ({day_pct:+.2f}%)

Métricas de rendimiento:
  • TWR (total): {twr:+.2f}%
  • Retorno anualizado: {ann_return:+.2f}%
  • Volatilidad anualizada: {ann_vol:.2f}%
  • Sharpe ratio: {sharpe:.3f}
  • Max drawdown: {max_dd:.2f}%
  • Alpha vs VOO: {alpha:+.2f}% | Beta: {beta:.3f}

Posiciones abiertas:
{chr(10).join(pos_lines) if pos_lines else "  (Sin posiciones)"}

════════════════════════════════════════════
MERCADOS HOY
════════════════════════════════════════════
{chr(10).join(idx_lines) if idx_lines else "  (No disponible)"}

  Divisas:
{chr(10).join(fx_lines) if fx_lines else "  (No disponible)"}

════════════════════════════════════════════

INSTRUCCIONES: Genera un análisis institucional profundo y accionable. Sé específico — menciona tickers, precios, porcentajes. Escribe en español profesional estilo Bloomberg Intelligence. Máximo 500 palabras para que quepa en Telegram.

## 📊 RESUMEN EJECUTIVO
Estado del portafolio hoy: valor total, P&L del día, posición ganadora y perdedora. ¿Superó o quedó por debajo del S&P 500?

## 🌍 CONTEXTO MACRO
VIX, yield 10Y y EUR/USD: qué implican para las posiciones europeas y de growth.

## 🔍 POSICIONES DESTACADAS
Las 2-3 posiciones más relevantes hoy (mejor y peor desempeño) con explicación concreta.

## 🎯 ACCIÓN RECOMENDADA
1 acción concreta para las próximas 48h: ticker, dirección, justificación cuantitativa.

## ⚠️ RIESGO PRINCIPAL
El riesgo más urgente del portafolio hoy con nivel de alerta.

Reglas: máximo 500 palabras. Cero generalidades — cada afirmación anclada en un dato real."""


def run_groq_analysis(prompt: str, api_key: str = "") -> Optional[str]:
    """Call Groq Llama API. Returns analysis text or None on failure."""
    from app.config import get_settings
    key = api_key or get_settings().GROQ_API_KEY
    if not key:
        log.warning("GROQ_API_KEY not set — skipping AI analysis")
        return None
    try:
        from groq import Groq
        client = Groq(api_key=key)
        for model in ("llama-3.3-70b-versatile", "llama-3.1-8b-instant"):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=800,
                )
                log.info("Groq analysis done with model: %s", model)
                return resp.choices[0].message.content
            except Exception as exc:
                log.warning("Groq model %s failed: %s", model, exc)
    except Exception as exc:
        log.error("Groq analysis error: %s", exc)
    return None


def generate_daily_analysis(summary, metrics: dict, base_currency: str = "USD") -> Optional[str]:
    """Full pipeline: build prompt → call Groq → return analysis text."""
    prompt = build_analysis_prompt(summary, metrics, base_currency)
    return run_groq_analysis(prompt)
