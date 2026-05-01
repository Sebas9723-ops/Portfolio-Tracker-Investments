"""
Multi-agent AI pipeline inspired by AutoHedge:
  1. Director Agent       — generates trade thesis (WHY the engine chose these allocations)
  2. Risk Manager Agent   — qualitative risk assessment (concentration, regime, correlation)
  3. Research Agent       — per-ticker fundamentals + news analysis (batched into one Groq call)
  4. Macro Agent          — analyzes macro environment, suggests macro_overlay adjustments
  5. Portfolio Doctor     — holistic diagnosis: health score + VaR + drift → actionable bullets

Uses Groq Llama 3.3 70B. All agents run in sequence and return structured output.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_ticker_fundamentals(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch key fundamentals and recent news for each ticker via yfinance.
    Returns {ticker: {sector, market_cap_b, pe_ratio, week52_range, description, news_headlines}}
    """
    import yfinance as yf
    result: dict[str, dict] = {}
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            info = tk.info or {}
            # News headlines (max 3)
            news = []
            try:
                raw_news = tk.news or []
                news = [
                    n.get("content", {}).get("title", "") or n.get("title", "")
                    for n in raw_news[:3]
                    if n.get("content", {}).get("title") or n.get("title")
                ]
            except Exception:
                pass

            result[t] = {
                "sector":        info.get("sector") or info.get("category") or "N/A",
                "market_cap_b":  round(info.get("marketCap", 0) / 1e9, 1) if info.get("marketCap") else None,
                "pe_ratio":      round(info.get("trailingPE", 0), 1) if info.get("trailingPE") else None,
                "week52_high":   info.get("fiftyTwoWeekHigh"),
                "week52_low":    info.get("fiftyTwoWeekLow"),
                "current_price": info.get("regularMarketPrice") or info.get("previousClose"),
                "description":   (info.get("longBusinessSummary") or "")[:200],
                "name":          info.get("shortName") or info.get("longName") or t,
                "news":          news,
            }
        except Exception as exc:
            log.warning("Fundamentals fetch failed for %s: %s", t, exc)
            result[t] = {"sector": "N/A", "name": t, "news": []}
    return result


def _call_groq(prompt: str, max_tokens: int = 600) -> str | None:
    """Call Groq Llama API. Returns text or None on failure."""
    try:
        from app.config import get_settings
        from groq import Groq
        key = get_settings().GROQ_API_KEY
        if not key:
            log.warning("GROQ_API_KEY not set — skipping agent call")
            return None
        client = Groq(api_key=key)
        for model in ("llama-3.3-70b-versatile", "llama-3.1-8b-instant"):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                )
                return resp.choices[0].message.content
            except Exception as exc:
                log.warning("Groq model %s failed: %s", model, exc)
    except Exception as exc:
        log.error("Groq call error: %s", exc)
    return None


# ── Agent 1: Director Agent ────────────────────────────────────────────────────

def run_director_agent(
    allocations: list[dict],
    regime: str | None,
    regime_confidence: float,
    regime_probs: dict,
    profile: str,
    total_value: float,
    total_cash: float,
    expected_sharpe: float,
    cvar_95: float,
    base_currency: str = "USD",
) -> str | None:
    """
    Director Agent: generates a concise investment thesis explaining why
    the quant engine chose these specific allocations.
    Returns English narrative (150-200 words).
    """
    regime_map = {
        "bull_strong": "strong bull market",
        "bull_weak":   "weak bull market",
        "bear_mild":   "mild bear market",
        "crisis":      "crisis regime",
    }
    regime_label = regime_map.get(regime or "", regime or "unknown")

    profile_map = {
        "aggressive":   "aggressive (maximize expected return)",
        "base":         "balanced (Sharpe-optimal)",
        "conservative": "conservative (minimize variance)",
    }
    profile_label = profile_map.get(profile, profile)

    alloc_lines = []
    for a in sorted(allocations, key=lambda x: x.get("pct_of_capital", 0), reverse=True):
        t = a.get("ticker", "")
        pct = a.get("pct_of_capital", 0)
        exp_ret = a.get("expected_return_pct", 0)
        signals = a.get("signals", [])
        sig_str = ", ".join(signals) if signals else "—"
        alloc_lines.append(f"  • {t}: {pct:.1f}% of capital | expected μ={exp_ret:.1f}% | signals=[{sig_str}]")

    alloc_block = "\n".join(alloc_lines) if alloc_lines else "  (no allocations)"

    probs_str = " | ".join(f"{k}={v:.0%}" for k, v in regime_probs.items()) if regime_probs else "N/A"

    prompt = f"""You are the Director Agent of a quantitative hedge fund. Your role is to generate the INVESTMENT THESIS explaining the optimization engine's decisions.

CONTRIBUTION PLAN DATA:
- Detected regime: {regime_label} (confidence {regime_confidence*100:.0f}%)
- Regime probabilities: {probs_str}
- Investor profile: {profile_label}
- Capital to deploy: {base_currency} {total_cash:,.0f} on total portfolio of {base_currency} {total_value:,.0f}
- Expected post-deploy Sharpe: {expected_sharpe:.2f}
- Daily CVaR 95%: {cvar_95*100:.2f}%

ENGINE ALLOCATIONS (SLSQP + GJR-GARCH + HMM + BL-XGBoost):
{alloc_block}

INSTRUCTION: Write the investment thesis in professional Bloomberg Intelligence style English. Explain the REASONING behind these specific allocations — why this regime favors these tickers, what implication the {profile} profile has on portfolio construction, and what the main quantitative rationale is. Maximum 180 words. No bullet points — flowing prose."""

    return _call_groq(prompt, max_tokens=400)


# ── Agent 2: Risk Manager Agent ────────────────────────────────────────────────

def run_risk_agent(
    allocations: list[dict],
    regime: str | None,
    profile: str,
    cvar_95: float,
    total_value: float,
    total_cash: float,
    n_corr_alerts: int,
    correlation_alerts: list[dict],
) -> dict[str, Any] | None:
    """
    Risk Manager Agent: evaluates the proposed allocations for qualitative risks.
    Returns {risk_level: "verde"|"amarillo"|"rojo", narrative: str, top_risk: str}
    """
    alloc_lines = []
    for a in sorted(allocations, key=lambda x: x.get("pct_of_capital", 0), reverse=True):
        alloc_lines.append(
            f"  • {a.get('ticker')}: {a.get('pct_of_capital', 0):.1f}% | "
            f"current_weight={a.get('current_weight', 0)*100:.1f}% → target={a.get('target_weight', 0)*100:.1f}%"
        )

    corr_lines = []
    for ca in correlation_alerts[:5]:
        corr_lines.append(f"  • {ca.get('ticker_a')} ↔ {ca.get('ticker_b')}: corr={ca.get('correlation', 0):.2f}")

    top_alloc = max(allocations, key=lambda x: x.get("pct_of_capital", 0), default={})
    max_pct = top_alloc.get("pct_of_capital", 0)
    deployment_pct = total_cash / total_value * 100 if total_value > 0 else 0

    prompt = f"""You are the Risk Manager of a quantitative hedge fund. Evaluate the qualitative risk of this investment plan.

INVESTMENT PLAN:
- Regime: {regime or "unknown"} | Profile: {profile}
- Capital: ${total_cash:,.0f} ({deployment_pct:.1f}% of portfolio)
- Daily CVaR 95%: {cvar_95*100:.2f}%
- Correlation alerts: {n_corr_alerts}

Proposed allocations:
{chr(10).join(alloc_lines) if alloc_lines else "(none)"}

Active correlation alerts:
{chr(10).join(corr_lines) if corr_lines else "(none)"}

INSTRUCTION: Analyze qualitative risks. Respond EXACTLY in this JSON format (no markdown, no additional text):
{{
  "risk_level": "green|yellow|red",
  "top_risk": "<single sentence stating the main risk>",
  "narrative": "<60-80 words evaluating concentration, correlation, regime risk, and deployment size>"
}}

- green: risks under control, balanced plan
- yellow: at least one moderate risk deserving attention
- red: excessive concentration, adverse regime, or CVaR out of control"""

    raw = _call_groq(prompt, max_tokens=250)
    if not raw:
        return None

    # Parse JSON from response
    import json, re
    try:
        # Extract JSON block
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as exc:
        log.warning("Risk agent JSON parse failed: %s | raw: %s", exc, raw[:200])

    # Fallback: return raw as narrative
    return {"risk_level": "amarillo", "top_risk": "Ver análisis completo.", "narrative": raw[:300]}


# ── Agent 3: Research Agent ────────────────────────────────────────────────────

def run_research_agent(
    allocations: list[dict],
    fundamentals: dict[str, dict],
) -> dict[str, str] | None:
    """
    Research Agent: generates a 2-3 sentence per-ticker analysis using
    fundamentals + news, batched into a single Groq call.
    Returns {ticker: research_text}
    """
    if not allocations:
        return None

    ticker_blocks = []
    for a in allocations:
        t = a.get("ticker", "")
        f = fundamentals.get(t, {})
        name = f.get("name", t)
        sector = f.get("sector", "N/A")
        mcap = f"{f['market_cap_b']:.1f}B" if f.get("market_cap_b") else "N/A"
        pe = f"{f['pe_ratio']:.1f}x" if f.get("pe_ratio") else "N/A"
        w52h = f.get("week52_high")
        w52l = f.get("week52_low")
        price = f.get("current_price")
        w52_str = f"{w52l:.2f}–{w52h:.2f}" if w52h and w52l else "N/A"
        news = f.get("news", [])
        news_str = " | ".join(news[:2]) if news else "No recent news."

        ticker_blocks.append(
            f"### {t} ({name})\n"
            f"Sector: {sector} | Market Cap: {mcap} | P/E: {pe} | Price: {price} | 52w: {w52_str}\n"
            f"Allocation: {a.get('pct_of_capital', 0):.1f}% of capital | expected μ: {a.get('expected_return_pct', 0):.1f}%\n"
            f"Recent news: {news_str}"
        )

    blocks_text = "\n\n".join(ticker_blocks)

    prompt = f"""You are the Research Analyst of a hedge fund. For each ticker in the investment plan, write a concise research analysis.

TICKERS TO ANALYZE:
{blocks_text}

INSTRUCTION: For EACH ticker, write exactly 2-3 sentences in English that explain:
1. What the company/fund does and why it is relevant now
2. What the fundamentals and recent news imply for the thesis
3. One specific risk factor to watch

Respond EXACTLY in this JSON format (no markdown):
{{
  "TICKER1": "analysis here...",
  "TICKER2": "analysis here...",
  ...
}}

Use the exact ticker names as keys. Be specific and use real data from the context."""

    raw = _call_groq(prompt, max_tokens=800)
    if not raw:
        return None

    import json, re
    try:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as exc:
        log.warning("Research agent JSON parse failed: %s", exc)
    return None


# ── Agent 4: Contribution Research Agent ─────────────────────────────────────

def _fetch_ticker_research_data(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch momentum, fundamentals, quality, and valuation data per ticker via yfinance.
    Returns rich data dict for the Contribution Research Agent.
    """
    import yfinance as yf

    result: dict[str, dict] = {}
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            info = tk.info or {}
            hist = tk.history(period="1y")

            def _mom(n: int) -> float | None:
                if len(hist) < n + 1:
                    return None
                c0 = float(hist["Close"].iloc[-1])
                cn = float(hist["Close"].iloc[-(n + 1)])
                return round((c0 / cn - 1) * 100, 2) if cn else None

            # RSI(14)
            rsi = None
            if len(hist) >= 15:
                try:
                    delta = hist["Close"].diff()
                    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
                    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
                    rs = gain / loss
                    rsi_s = 100 - (100 / (1 + rs))
                    rsi = round(float(rsi_s.iloc[-1]), 1)
                except Exception:
                    pass

            # Analyst upside
            target = info.get("targetMeanPrice")
            price = info.get("regularMarketPrice") or info.get("previousClose")
            analyst_upside = round((target / price - 1) * 100, 1) if target and price else None

            result[t] = {
                "name":              info.get("shortName") or info.get("longName") or t,
                "sector":            info.get("sector") or info.get("category") or "N/A",
                "beta":              round(info.get("beta", 1.0), 2) if info.get("beta") else None,
                # Momentum
                "mom_1m":  _mom(21),
                "mom_3m":  _mom(63),
                "mom_6m":  _mom(126),
                "mom_12m": _mom(252),
                "rsi_14":  rsi,
                # Fundamentals / Growth
                "pe_ratio":       round(info.get("trailingPE", 0), 1) if info.get("trailingPE") else None,
                "pb_ratio":       round(info.get("priceToBook", 0), 2) if info.get("priceToBook") else None,
                "revenue_growth": round(info.get("revenueGrowth", 0) * 100, 1) if info.get("revenueGrowth") else None,
                "eps_growth":     round(info.get("earningsGrowth", 0) * 100, 1) if info.get("earningsGrowth") else None,
                # Quality
                "roe":           round(info.get("returnOnEquity", 0) * 100, 1) if info.get("returnOnEquity") else None,
                "debt_equity":   round(info.get("debtToEquity", 0), 1) if info.get("debtToEquity") else None,
                "profit_margin": round(info.get("profitMargins", 0) * 100, 1) if info.get("profitMargins") else None,
                "current_ratio": round(info.get("currentRatio", 0), 2) if info.get("currentRatio") else None,
                # Valuation
                "analyst_upside":        analyst_upside,
                "analyst_recommendation": info.get("recommendationKey"),
                "peg_ratio":             round(info.get("pegRatio", 0), 2) if info.get("pegRatio") else None,
            }
        except Exception as exc:
            log.warning("Research data fetch failed for %s: %s", t, exc)
            result[t] = {"name": t, "sector": "N/A"}
    return result


def run_contribution_research_agent(
    allocations: list[dict],
    profile: str,
    base_currency: str = "USD",
) -> dict[str, Any] | None:
    """
    Contribution Research Agent: evaluates each ticker across 4 signal dimensions
    (momentum, fundamentals, quality, valuation) weighted by investor profile.

    Returns per-ticker:
      {score: 0-100, momentum_signal, fundamental_signal, quality_signal,
       valuation_signal, weight_adjustment: float, key_insight: str}
    """
    tickers = [a["ticker"] for a in allocations if a.get("ticker")]
    if not tickers:
        return None

    research_data = _fetch_ticker_research_data(tickers)

    # Profile-specific weights for each signal dimension
    PROFILE_WEIGHTS = {
        "conservative": {"momentum": 0.15, "fundamentals": 0.25, "quality": 0.40, "valuation": 0.20},
        "base":         {"momentum": 0.25, "fundamentals": 0.30, "quality": 0.25, "valuation": 0.20},
        "aggressive":   {"momentum": 0.45, "fundamentals": 0.30, "quality": 0.10, "valuation": 0.15},
    }
    pw = PROFILE_WEIGHTS.get(profile, PROFILE_WEIGHTS["base"])

    profile_desc = {
        "conservative": "conservative — prioritizes quality (ROE, margins, low debt) and reasonable valuation; penalizes speculative momentum and high beta",
        "base":         "balanced — balances momentum, fundamental growth, quality and valuation without extreme biases",
        "aggressive":   "aggressive — maximizes expected return; overweights strong momentum and growth; tolerates high valuations if growth justifies it",
    }

    ticker_blocks = []
    for a in allocations:
        t = a.get("ticker", "")
        d = research_data.get(t, {})
        quant_pct = a.get("pct_of_capital", 0)

        def _fmt(v, suffix=""):
            return f"{v}{suffix}" if v is not None else "N/A"

        block = (
            f"### {t} ({d.get('name', t)}) — Quant allocation: {quant_pct:.1f}%\n"
            f"Sector: {d.get('sector', 'N/A')} | Beta: {_fmt(d.get('beta'))}\n"
            f"MOMENTUM: 1m={_fmt(d.get('mom_1m'), '%')} 3m={_fmt(d.get('mom_3m'), '%')} "
            f"6m={_fmt(d.get('mom_6m'), '%')} 12m={_fmt(d.get('mom_12m'), '%')} | RSI14={_fmt(d.get('rsi_14'))}\n"
            f"FUNDAMENTALS: P/E={_fmt(d.get('pe_ratio'))} | PEG={_fmt(d.get('peg_ratio'))} | "
            f"Rev.Growth={_fmt(d.get('revenue_growth'), '%')} | EPS.Growth={_fmt(d.get('eps_growth'), '%')}\n"
            f"QUALITY: ROE={_fmt(d.get('roe'), '%')} | D/E={_fmt(d.get('debt_equity'))} | "
            f"Margin={_fmt(d.get('profit_margin'), '%')} | CurrentRatio={_fmt(d.get('current_ratio'))}\n"
            f"VALUATION: Analyst upside={_fmt(d.get('analyst_upside'), '%')} | "
            f"Recommendation={_fmt(d.get('analyst_recommendation'))} | P/B={_fmt(d.get('pb_ratio'))}"
        )
        ticker_blocks.append(block)

    blocks_text = "\n\n".join(ticker_blocks)

    prompt = f"""You are the Contribution Research Agent of a quantitative hedge fund. Evaluate the tickers in the contribution plan based on quantitative and qualitative signals, weighted by the investor profile.

PROFILE: {profile_desc.get(profile, profile)}

EVALUATION WEIGHTS FOR PROFILE {profile.upper()}:
- Momentum (price): {pw['momentum']*100:.0f}%
- Fundamentals (growth): {pw['fundamentals']*100:.0f}%
- Quality (ROE, margins, debt): {pw['quality']*100:.0f}%
- Valuation (analyst upside, P/B): {pw['valuation']*100:.0f}%

TICKERS AND DATA:
{blocks_text}

INSTRUCTION: Evaluate each ticker according to the profile weights. Respond EXACTLY in this JSON format (no markdown, no additional text):
{{
  "TICKER1": {{
    "score": <number 0-100, weighted total score>,
    "momentum_signal": "<bullish | neutral | bearish>",
    "fundamental_signal": "<strong | moderate | weak>",
    "quality_signal": "<high | medium | low>",
    "valuation_signal": "<undervalued | fair | overvalued>",
    "weight_adjustment": <float 0.5-1.5; 1.0=keep quant weight, >1.0=increase weight, <1.0=reduce weight>,
    "key_insight": "<maximum 12 words: the most critical factor for this specific profile>"
  }}
}}

Weight_adjustment rules for profile {profile}:
- If momentum is bullish AND aggressive profile → bigger boost (up to 1.4)
- If quality is low AND conservative profile → strong penalty (down to 0.6)
- If overvalued AND conservative profile → moderate penalty (0.75-0.85)
- If score > 75 → weight_adjustment ≥ 1.1
- If score < 40 → weight_adjustment ≤ 0.85
- Use exact ticker names as JSON keys."""

    raw = _call_groq(prompt, max_tokens=1000)
    if not raw:
        return None

    import json, re
    try:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as exc:
        log.warning("Contribution research agent JSON parse failed: %s | raw: %s", exc, raw[:300])
    return None


# ── Agent 5: Macro Agent ──────────────────────────────────────────────────────

def _fetch_macro_indicators() -> dict[str, dict]:
    """Fetch key macro indicators via yfinance."""
    import yfinance as yf
    indicators = {
        "VIX":      "^VIX",
        "10Y Yield": "^TNX",
        "DXY":      "DX-Y.NYB",
        "S&P 500":  "^GSPC",
        "Gold":     "GC=F",
        "Crude Oil": "CL=F",
    }
    result: dict[str, dict] = {}
    for name, symbol in indicators.items():
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if hist.empty:
                continue
            current = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current
            change_pct = (current - prev) / prev * 100 if prev else 0
            result[name] = {"value": round(current, 2), "change_pct": round(change_pct, 2)}
        except Exception:
            pass
    return result


def run_macro_agent(
    portfolio_tickers: list[str],
    portfolio_weights: dict[str, float],
    base_currency: str = "USD",
) -> dict[str, Any] | None:
    """
    Macro Agent: analyzes current macro environment and suggests macro_overlay adjustments.
    Returns {macro_regime: str, narrative: str, suggested_overlay: {ticker: float}}
    """
    macro_data = _fetch_macro_indicators()
    if not macro_data:
        log.warning("Macro agent: no macro data available")
        return None

    macro_lines = "\n".join(
        f"  • {name}: {data['value']} ({data['change_pct']:+.2f}% today)"
        for name, data in macro_data.items()
    )
    portfolio_lines = "\n".join(
        f"  • {t}: {w * 100:.1f}%"
        for t, w in sorted(portfolio_weights.items(), key=lambda x: x[1], reverse=True)
    )

    prompt = f"""You are the Macro Analyst of a quantitative hedge fund. Analyze the current macroeconomic environment and suggest overlay adjustments for the portfolio.

CURRENT MACRO INDICATORS:
{macro_lines}

PORTFOLIO ({base_currency}):
{portfolio_lines}

INSTRUCTION: Respond EXACTLY in this JSON format (no markdown, no additional text):
{{
  "macro_regime": "<risk_on | risk_off | stagflation | goldilocks | crisis>",
  "narrative": "<50-70 words in English: current macro state and its implication for this specific portfolio>",
  "suggested_overlay": {{
    "TICKER": <number between 0.5 and 2.0 where 1.0=neutral>
  }}
}}

The overlay multiplies expected returns in the optimizer. Only include tickers with clear conviction (different from 1.0). Maximum 3 tickers. If the environment is neutral, return empty suggested_overlay {{}}."""

    raw = _call_groq(prompt, max_tokens=350)
    if not raw:
        return None

    import json, re
    try:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as exc:
        log.warning("Macro agent JSON parse failed: %s | raw: %s", exc, raw[:200])
    return None


# ── Agent 5: Portfolio Doctor ─────────────────────────────────────────────────

def run_portfolio_doctor_agent(
    health_score: float,
    health_components: dict[str, float],
    var_1d: float,
    cvar_1d: float,
    max_stress_loss_pct: float,
    avg_drift_pct: float,
    risk_level: str = "amarillo",
    base_currency: str = "USD",
) -> dict[str, Any] | None:
    """
    Portfolio Doctor: holistic diagnosis combining all risk/health metrics.
    Returns {urgency: str, diagnosis: str, actions: [str]}
    """
    components_lines = "\n".join(
        f"  • {k}: {v:.1f}/25 pts" for k, v in health_components.items()
    )

    prompt = f"""You are the Portfolio Doctor of a hedge fund. Your role is to give a clear and actionable diagnosis of the portfolio's health this week.

CURRENT METRICS:
- Total Health Score: {health_score:.1f}/100
- Components:
{components_lines}
- 1-day VaR 95%: {base_currency} {var_1d:,.0f}
- 1-day CVaR 95%: {base_currency} {cvar_1d:,.0f}
- Worst stress test scenario: -{max_stress_loss_pct:.1f}%
- Average drift vs optimal: {avg_drift_pct:.1f}%
- Risk level (Risk Manager): {risk_level}

INSTRUCTION: Respond EXACTLY in this JSON format (no markdown, no additional text):
{{
  "urgency": "<low | medium | high>",
  "diagnosis": "<2 sentences in English summarizing the current state of the portfolio>",
  "actions": [
    "<concrete and specific action 1>",
    "<concrete and specific action 2>",
    "<concrete and specific action 3>"
  ]
}}

- low: healthy portfolio, routine monitoring
- medium: attention points requiring action in the coming days
- high: immediate action recommended this week
Actions must be specific (e.g. "Reduce concentration in X because drift is Y%"), not generic."""

    raw = _call_groq(prompt, max_tokens=350)
    if not raw:
        return None

    import json, re
    try:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as exc:
        log.warning("Doctor agent JSON parse failed: %s | raw: %s", exc, raw[:200])
    return None


# ── Full Pipeline ──────────────────────────────────────────────────────────────

def run_full_agent_pipeline(
    allocations: list[dict],
    regime: str | None,
    regime_confidence: float,
    regime_probs: dict,
    profile: str,
    total_value: float,
    total_cash: float,
    expected_sharpe: float,
    cvar_95: float,
    n_corr_alerts: int,
    correlation_alerts: list[dict],
    base_currency: str = "USD",
) -> dict[str, Any]:
    """
    Orchestrates Director → Risk → Research agents.
    Returns combined result dict. Each agent failure is handled gracefully.
    """
    tickers = [a["ticker"] for a in allocations if a.get("ticker")]

    # Fetch fundamentals once (used by Research Agent)
    fundamentals: dict = {}
    if tickers:
        try:
            fundamentals = _fetch_ticker_fundamentals(tickers)
        except Exception as exc:
            log.warning("Fundamentals fetch failed: %s", exc)

    # Agent 1: Director
    thesis = None
    try:
        thesis = run_director_agent(
            allocations=allocations,
            regime=regime,
            regime_confidence=regime_confidence,
            regime_probs=regime_probs,
            profile=profile,
            total_value=total_value,
            total_cash=total_cash,
            expected_sharpe=expected_sharpe,
            cvar_95=cvar_95,
            base_currency=base_currency,
        )
    except Exception as exc:
        log.error("Director agent failed: %s", exc)

    # Agent 2: Risk Manager
    risk = None
    try:
        risk = run_risk_agent(
            allocations=allocations,
            regime=regime,
            profile=profile,
            cvar_95=cvar_95,
            total_value=total_value,
            total_cash=total_cash,
            n_corr_alerts=n_corr_alerts,
            correlation_alerts=correlation_alerts,
        )
    except Exception as exc:
        log.error("Risk agent failed: %s", exc)

    # Agent 3: Research
    research = None
    try:
        research = run_research_agent(
            allocations=allocations,
            fundamentals=fundamentals,
        )
    except Exception as exc:
        log.error("Research agent failed: %s", exc)

    return {
        "thesis":     thesis,
        "risk":       risk,
        "research":   research,
        "tickers_analyzed": tickers,
    }
