"""
Agent endpoints:
  POST /api/agents/analyze       — run 3-agent pipeline on a contribution plan
  GET  /api/agents/last-results  — retrieve latest scheduled agent results (macro, doctor)
  POST /api/agents/run-now       — manually trigger macro + doctor agents
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth.dependencies import get_user_id
from app.services.agent_pipeline import run_full_agent_pipeline, run_contribution_research_agent
from app.db.agent_results import save_agent_result, load_latest_agent_result

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentAnalysisRequest(BaseModel):
    # Contribution plan allocations (from POST /api/contribution-plan response)
    allocations: list[dict]
    regime: str | None = None
    regime_confidence: float = 0.0
    regime_probs: dict = {}
    profile: str = "base"
    total_value: float = 0.0
    total_cash: float = 0.0
    expected_sharpe: float = 0.0
    cvar_95: float = 0.02
    n_corr_alerts: int = 0
    correlation_alerts: list[dict] = []
    base_currency: str = "USD"


@router.get("/last-results")
def last_results(user_id: str = Depends(get_user_id)) -> dict[str, Any]:
    """Return latest macro, doctor, and target-research agent results for this user."""
    from app.db.agent_results import load_latest_target_research
    macro = load_latest_agent_result(user_id, "macro")
    doctor = load_latest_agent_result(user_id, "doctor")
    # Target research: load per-profile (no max_age filter here — just show latest)
    research_targets = {
        p: load_latest_agent_result(user_id, f"target_research_{p}")
        for p in ("conservative", "base", "aggressive")
    }
    return {
        "macro": macro,
        "doctor": doctor,
        "research_targets": research_targets,
    }


@router.post("/run-now")
def run_now(user_id: str = Depends(get_user_id)) -> dict[str, Any]:
    """Manually trigger Macro + Portfolio Doctor agents for the current user."""
    from app.db.supabase_client import get_admin_client
    from app.db.quant_results import load_latest_quant_result
    from app.services.agent_pipeline import run_macro_agent, run_portfolio_doctor_agent
    from app.services.market_data import get_quotes
    from app.services.fx_service import get_fx_rates
    from app.services.exchange_classifier import get_native_currency
    from app.compute.portfolio_builder import build_portfolio

    db = get_admin_client()
    settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    settings = settings_res.data or {}
    base_currency = settings.get("base_currency", "USD")

    positions = db.table("positions").select("*").eq("user_id", user_id).execute().data or []
    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
    if not tickers:
        return {"macro": None, "doctor": None, "error": "No positions found"}

    shares = {p["ticker"]: float(p["shares"]) for p in positions if float(p.get("shares", 0)) > 0}
    total_shares = sum(shares.values())
    weights = {t: shares[t] / total_shares for t in tickers} if total_shares > 0 else {}

    qr = load_latest_quant_result(user_id)
    expected_sharpe = float((qr or {}).get("expected_sharpe") or 1.0)
    cvar_95 = float((qr or {}).get("cvar_95") or 0.02)
    optimal_weights = (qr or {}).get("optimal_weights") or {}

    avg_drift = 0.0
    if optimal_weights:
        drifts = [abs(float(optimal_weights.get(t, 0)) - weights.get(t, 0)) for t in set(list(weights) + list(optimal_weights))]
        avg_drift = (sum(drifts) / len(drifts) * 100) if drifts else 0.0

    sharpe_score = min(25.0, max(0.0, expected_sharpe * 10.0))
    cvar_score = max(0.0, 25.0 - cvar_95 * 500)
    drift_score = max(0.0, 25.0 - avg_drift * 2.5)
    n = len(weights)
    hhi = sum(w ** 2 for w in weights.values()) if weights else 1.0
    hhi_score = max(0.0, 25.0 - (hhi - 1 / n if n > 0 else hhi) * 100) if n > 0 else 0.0
    health_score = sharpe_score + cvar_score + drift_score + hhi_score
    health_components = {
        "Sharpe": sharpe_score,
        "Diversificación": hhi_score,
        "CVaR headroom": cvar_score,
        "Drift": drift_score,
    }

    quotes = get_quotes(tickers)
    exchange_currencies = [get_native_currency(t) for t in tickers]
    fx_rates = get_fx_rates(list(set(exchange_currencies)), base=base_currency)
    transactions = db.table("transactions").select("*").eq("user_id", user_id).execute().data or []
    summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)
    total_value = float(summary.total_value_base)

    errors: list[str] = []

    try:
        macro_result = run_macro_agent(tickers, weights, base_currency)
    except Exception as exc:
        macro_result = None
        errors.append(f"Macro agent error: {exc}")

    if macro_result:
        try:
            save_agent_result(user_id, "macro", macro_result, triggered_by="manual")
        except Exception as exc:
            errors.append(f"Save macro failed: {exc}")
    else:
        if not any("Macro" in e for e in errors):
            errors.append("Macro agent returned None — check GROQ_API_KEY and yfinance connectivity")

    risk_level = "yellow"
    if macro_result:
        regime = macro_result.get("macro_regime", "")
        if regime == "crisis":
            risk_level = "red"
        elif regime in ("risk_on", "goldilocks"):
            risk_level = "green"

    try:
        doctor_result = run_portfolio_doctor_agent(
            health_score=health_score,
            health_components=health_components,
            var_1d=total_value * cvar_95 * 0.8,
            cvar_1d=total_value * cvar_95,
            max_stress_loss_pct=cvar_95 * 300,
            avg_drift_pct=avg_drift,
            risk_level=risk_level,
            base_currency=base_currency,
        )
    except Exception as exc:
        doctor_result = None
        errors.append(f"Doctor agent error: {exc}")

    if doctor_result:
        try:
            save_agent_result(user_id, "doctor", doctor_result, triggered_by="manual")
        except Exception as exc:
            errors.append(f"Save doctor failed: {exc}")
    else:
        if not any("Doctor" in e for e in errors):
            errors.append("Doctor agent returned None — check GROQ_API_KEY")

    return {"macro": macro_result, "doctor": doctor_result, "errors": errors}


@router.post("/refresh-targets")
def refresh_targets(user_id: str = Depends(get_user_id)) -> dict[str, Any]:
    """
    Manually trigger Target Research Agent for all 3 profiles.
    Runs the full ML + CVXPY pipeline and persists fresh target weights.
    These are then used by the contribution planner as a tracking anchor.
    """
    from app.db.supabase_client import get_admin_client
    from app.db.quant_results import load_user_bl_views
    from app.services.agent_pipeline import run_target_research_agent
    from app.services.portfolio_service import load_portfolio_data

    db = get_admin_client()
    settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    settings = settings_res.data or {}
    rfr = float(settings.get("risk_free_rate", 0.045))
    horizon = settings.get("default_time_horizon", "long")
    if horizon not in ("short", "medium", "long"):
        horizon = "long"
    ticker_weight_rules = settings.get("ticker_weight_rules") or {}
    combination_ranges = settings.get("combination_ranges") or {}

    try:
        summary, tickers, _ = load_portfolio_data(user_id)
    except Exception as exc:
        return {"error": f"Failed to load portfolio: {exc}", "results": {}}

    if not tickers:
        return {"error": "No positions found", "results": {}}

    rows_by_ticker = {r.ticker: r for r in summary.rows}
    portfolio: dict = {
        t: {"value_base": float(rows_by_ticker[t].value_base) if t in rows_by_ticker else 0.0}
        for t in tickers
    }
    bl_views = load_user_bl_views(user_id)

    results: dict[str, Any] = {}
    errors: list[str] = []
    for profile in ("conservative", "base", "aggressive"):
        profile_rules = ticker_weight_rules.get(profile, {})
        c1 = {
            t: {"floor": float(r.get("floor", 0.0)), "cap": float(r.get("cap", 1.0))}
            for t, r in profile_rules.items() if isinstance(r, dict)
        }
        c2 = combination_ranges.get(profile, []) or []
        res = run_target_research_agent(
            user_id=user_id,
            profile=profile,
            portfolio=portfolio,
            constraints_motor1=c1,
            constraints_motor2=c2,
            bl_views=bl_views,
            rfr=rfr,
            time_horizon=horizon,
        )
        if res:
            results[profile] = {
                "regime": res.get("regime"),
                "expected_sharpe": res.get("expected_sharpe"),
                "n_targets": len(res.get("optimal_weights", {})),
            }
        else:
            errors.append(f"{profile}: agent returned None")

    return {"results": results, "errors": errors}


class ContributionResearchRequest(BaseModel):
    allocations: list[dict]
    profile: str = "base"
    base_currency: str = "USD"


@router.post("/contribution-research")
def contribution_research(
    req: ContributionResearchRequest,
    user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """
    Contribution Research Agent: evaluates each ticker in the contribution plan
    across momentum, fundamentals, quality, and valuation signals weighted by profile.
    Returns per-ticker {score, signals, weight_adjustment, key_insight}.
    """
    result = run_contribution_research_agent(
        allocations=req.allocations,
        profile=req.profile,
        base_currency=req.base_currency,
    )
    return result or {}


def _run_weekly_report_bg(user_id: str) -> None:
    """Heavy work — runs in a background thread so the HTTP response is immediate."""
    import pandas as pd
    import logging
    import traceback
    _log = logging.getLogger(__name__)
    _log.info("send-weekly-report bg: starting for user %s", user_id[:8])
    try:
        from app.db.supabase_client import get_admin_client
        from app.services.market_data import get_quotes, get_historical_multi, get_risk_free_rate
        from app.services.fx_service import get_fx_rates
        from app.services.exchange_classifier import get_native_currency
        from app.compute.portfolio_builder import build_portfolio
        from app.compute.returns import build_portfolio_returns, compute_twr
        from app.compute.risk import compute_extended_ratios
        from app.services.ai_analysis import generate_weekly_analysis
        from app.services.email_service import send_weekly_report_email
        from app.services.telegram_service import send_document, send_weekly_report

        db = get_admin_client()
        settings = (db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute().data or {})
        base_currency = settings.get("base_currency", "USD")
        rfr = float(settings.get("risk_free_rate") or get_risk_free_rate())
        bm_ticker = settings.get("preferred_benchmark", "VOO")
        report_email = settings.get("drift_alert_email", "")

        _log.info("send-weekly-report bg: email=%s base=%s", report_email or "(none)", base_currency)

        if not report_email:
            _log.warning("send-weekly-report bg: no drift_alert_email set for user %s", user_id[:8])
            return

        positions = db.table("positions").select("*").eq("user_id", user_id).execute().data or []
        tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
        if not tickers:
            _log.warning("send-weekly-report bg: no positions for %s", user_id[:8])
            return

        _log.info("send-weekly-report bg: %d tickers — fetching data", len(tickers))
        transactions = db.table("transactions").select("*").eq("user_id", user_id).execute().data or []
        quotes = get_quotes(tickers)
        exchange_currencies = [get_native_currency(t) for t in tickers]
        pos_currencies = [p.get("currency") or get_native_currency(p["ticker"]) for p in positions]
        fx_rates = get_fx_rates(list(set(exchange_currencies + pos_currencies)), base=base_currency)
        summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)

        _log.info("send-weekly-report bg: fetching 1Y historical data")
        hist = get_historical_multi(list(set(tickers + [bm_ticker])), period="1y")
        total_shares = sum(float(p["shares"]) for p in positions if float(p.get("shares", 0)) > 0)
        weights_hist = {p["ticker"]: float(p["shares"]) / total_shares for p in positions if float(p.get("shares", 0)) > 0} if total_shares > 0 else {}
        portfolio_returns = build_portfolio_returns({t: hist[t] for t in tickers if t in hist}, weights_hist)

        bm_hist = hist.get(bm_ticker)
        if bm_hist is not None and not bm_hist.empty:
            bm_col = "Close" if "Close" in bm_hist.columns else bm_hist.columns[0]
            bm_returns = bm_hist[bm_col].pct_change().dropna()
        else:
            bm_returns = pd.Series(dtype=float)

        ratios = compute_extended_ratios(portfolio_returns, bm_returns, rfr)
        ratios["twr"] = compute_twr(portfolio_returns) * 100
        bm_cum = float((1 + bm_returns).prod() - 1) if not bm_returns.empty else None

        momentum: dict = {}
        for t in tickers:
            df_h = hist.get(t)
            if df_h is None or df_h.empty:
                continue
            col = "Close" if "Close" in df_h.columns else df_h.columns[0]
            prices = df_h[col].dropna()
            if prices.empty:
                continue
            current = float(prices.iloc[-1])
            def _ret(n, p=prices, c=current):
                return (c / float(p.iloc[-n]) - 1) * 100 if len(p) > n else None
            momentum[t] = {"1w": _ret(5), "1m": _ret(21), "3m": _ret(63), "6m": _ret(126), "1y": _ret(252)}

        week_change_pct = None
        try:
            snaps = db.table("portfolio_snapshots").select("snapshot_date,total_value_base").eq("user_id", user_id).order("snapshot_date", desc=True).limit(8).execute().data or []
            if len(snaps) >= 5:
                val_7d_ago = float(snaps[min(6, len(snaps) - 1)]["total_value_base"])
                if val_7d_ago > 0:
                    week_change_pct = (float(summary.total_value_base) / val_7d_ago - 1) * 100
        except Exception:
            pass

        fear_greed = None
        try:
            import urllib.request as _ureq, json as _jmod
            _req = _ureq.Request("https://api.alternative.me/fng/?limit=1&format=json", headers={"User-Agent": "Mozilla/5.0"})
            with _ureq.urlopen(_req, timeout=5) as _r:
                _fg_entry = (_jmod.loads(_r.read()).get("data") or [{}])[0]
            fear_greed = {"score": int(_fg_entry.get("value", 0)), "rating": _fg_entry.get("value_classification", "")}
        except Exception:
            pass

        _log.info("send-weekly-report bg: generating AI analysis")
        weekly_ai = None
        try:
            weekly_ai = generate_weekly_analysis(
                summary=summary, metrics=ratios, base_currency=base_currency,
                momentum=momentum, fear_greed=fear_greed,
                macro_result=None, doctor_result=None, week_change_pct=week_change_pct,
            )
        except Exception as ai_exc:
            _log.warning("send-weekly-report bg: AI analysis failed: %s", ai_exc)

        # Generate PDF
        # Week-ahead news & events
        _log.info("send-weekly-report bg: fetching week-ahead news")
        week_ahead: str | None = None
        try:
            from app.services.ai_analysis import fetch_week_ahead_news, generate_week_ahead_summary
            news_data  = fetch_week_ahead_news(tickers)
            week_ahead = generate_week_ahead_summary(
                tickers, news_data["headlines"], news_data["earnings"]
            )
        except Exception as news_exc:
            _log.warning("send-weekly-report bg: week-ahead news failed: %s", news_exc)

        _log.info("send-weekly-report bg: generating PDF")
        pdf_bytes: bytes | None = None
        try:
            from app.services.pdf_report import generate_portfolio_pdf
            from datetime import datetime
            pdf_bytes = generate_portfolio_pdf(
                summary=summary, metrics=ratios, base_currency=base_currency,
                benchmark_ticker=bm_ticker, benchmark_cum=bm_cum,
                momentum=momentum, fear_greed=fear_greed,
                week_change_pct=week_change_pct, ai_analysis=weekly_ai,
                week_ahead=week_ahead,
            )
            _log.info("send-weekly-report bg: PDF generated (%d bytes)", len(pdf_bytes))
        except Exception as pdf_exc:
            _log.warning("send-weekly-report bg: PDF generation failed: %s", pdf_exc)

        # Send PDF to Telegram
        from datetime import datetime
        if pdf_bytes:
            filename = f"portfolio_report_{datetime.now().strftime('%Y%m%d')}.pdf"
            caption = f"Weekly Portfolio Report — {datetime.now().strftime('%Y-%m-%d')}"
            ok_tg = send_document(pdf_bytes, filename=filename, caption=caption)
            _log.info("send-weekly-report bg: Telegram PDF %s", "SENT" if ok_tg else "FAILED")
        else:
            # Fallback: send text messages
            ok_tg = send_weekly_report(
                summary=summary, metrics=ratios, base_currency=base_currency,
                benchmark_ticker=bm_ticker, benchmark_cum=bm_cum,
                momentum=momentum, fear_greed=fear_greed,
                week_change_pct=week_change_pct, ai_analysis=weekly_ai,
            )
            _log.info("send-weekly-report bg: Telegram text %s", "SENT" if ok_tg else "FAILED")

        # Email (if configured)
        if report_email:
            _log.info("send-weekly-report bg: sending email to %s", report_email)
            ok_email = send_weekly_report_email(
                to=report_email, summary=summary, metrics=ratios, base_currency=base_currency,
                benchmark_ticker=bm_ticker, benchmark_cum=bm_cum,
                momentum=momentum, fear_greed=fear_greed,
                week_change_pct=week_change_pct, ai_analysis=weekly_ai,
            )
            _log.info("send-weekly-report bg: email %s to %s", "SENT" if ok_email else "FAILED", report_email)

    except Exception as exc:
        _log.error("send-weekly-report bg ERROR: %s\n%s", exc, traceback.format_exc())


@router.post("/test-email")
def test_email_now(user_id: str = Depends(get_user_id)) -> dict[str, Any]:
    """Send a quick test email immediately to verify email delivery is working."""
    import os
    from app.db.supabase_client import get_admin_client
    from app.services.email_service import send_email, get_email_provider

    db = get_admin_client()
    settings = (db.table("user_settings").select("drift_alert_email").eq("user_id", user_id).maybe_single().execute().data or {})
    report_email = settings.get("drift_alert_email", "")

    provider = get_email_provider()
    sg_key = bool(os.getenv("SENDGRID_API_KEY"))
    smtp_host = os.getenv("EMAIL_HOST", "")

    if not report_email:
        return {"ok": False, "error": "No drift_alert_email configured in user settings"}
    if provider == "none":
        return {
            "ok": False,
            "error": "No email provider configured. Set SENDGRID_API_KEY in Render.",
            "SENDGRID_API_KEY": sg_key,
            "EMAIL_HOST": bool(smtp_host),
        }

    ok = send_email(
        to=report_email,
        subject="Test email — Portfolio Tracker",
        body_html="<p style='font-family:monospace'>Email delivery is working via <b>" + provider + "</b>. Weekly reports will arrive at this address.</p>",
    )
    return {"ok": ok, "to": report_email, "provider": provider}


@router.post("/send-weekly-report")
def send_weekly_report_now(user_id: str = Depends(get_user_id)) -> dict[str, Any]:
    """Fire the weekly report in a background thread and return immediately."""
    import threading
    t = threading.Thread(target=_run_weekly_report_bg, args=(user_id,), daemon=True)
    t.start()
    return {"ok": True, "results": {"status": "queued — email will arrive in ~2 min"}}


@router.post("/analyze")
def analyze(
    req: AgentAnalysisRequest,
    user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """
    Run Director Agent (thesis) + Risk Manager Agent + Research Agent per ticker.
    Accepts the contribution plan response payload from the frontend.
    Returns {thesis, risk: {risk_level, top_risk, narrative}, research: {ticker: text}}
    """
    return run_full_agent_pipeline(
        allocations=req.allocations,
        regime=req.regime,
        regime_confidence=req.regime_confidence,
        regime_probs=req.regime_probs,
        profile=req.profile,
        total_value=req.total_value,
        total_cash=req.total_cash,
        expected_sharpe=req.expected_sharpe,
        cvar_95=req.cvar_95,
        n_corr_alerts=req.n_corr_alerts,
        correlation_alerts=req.correlation_alerts,
        base_currency=req.base_currency,
    )
