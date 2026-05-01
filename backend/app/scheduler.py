"""
Background schedulers:
  - Daily portfolio snapshot at 17:30 America/Bogota (after market close in Colombia)
  - Daily quant optimization at 16:00 America/New_York (US market close)
    Pre-caches QuantResult for each user so POST /contribution-plan is fast.
"""
import logging
from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)


def _snapshot_all_users() -> None:
    """Build and persist today's portfolio snapshot for every user in the DB."""
    from app.db.supabase_client import get_admin_client
    from app.services.market_data import get_quotes
    from app.services.fx_service import get_fx_rates
    from app.services.exchange_classifier import get_native_currency
    from app.compute.portfolio_builder import build_portfolio

    db = get_admin_client()
    today = str(date.today())

    # Collect all distinct user_ids that have at least one position
    pos_res = db.table("positions").select("user_id").execute()
    user_ids = list({row["user_id"] for row in (pos_res.data or [])})

    if not user_ids:
        log.info("Snapshot job: no users with positions, skipping.")
        return

    log.info(f"Snapshot job: saving snapshots for {len(user_ids)} user(s) on {today}")

    for user_id in user_ids:
        try:
            # Settings
            settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
            settings = settings_res.data or {}
            base_currency = settings.get("base_currency", "USD")

            # Positions + transactions
            positions = (db.table("positions").select("*").eq("user_id", user_id).execute().data or [])
            transactions = (db.table("transactions").select("*").eq("user_id", user_id).execute().data or [])

            tickers = [p["ticker"] for p in positions]
            if not tickers:
                continue

            quotes = get_quotes(tickers)
            exchange_currencies = [get_native_currency(t) for t in tickers]
            pos_currencies = [p.get("currency") or get_native_currency(p["ticker"]) for p in positions]
            currencies = list(set(exchange_currencies + pos_currencies))
            fx_rates = get_fx_rates(currencies, base=base_currency)

            summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)

            row = {
                "user_id": user_id,
                "snapshot_date": today,
                "total_value_base": summary.total_value_base,
                "base_currency": base_currency,
                "holdings": [r.model_dump() for r in summary.rows],
                "metadata": "auto",
            }
            db.table("portfolio_snapshots").upsert(row, on_conflict="user_id,snapshot_date").execute()
            log.info(f"  ✓ {user_id[:8]}… — {base_currency} {summary.total_value_base:,.2f}")

        except Exception as exc:
            log.error(f"  ✗ {user_id[:8]}… — snapshot failed: {exc}")


def _optimize_all_users() -> None:
    """
    Pre-cache QuantResult for every user with an active portfolio.
    Runs daily at 16:00 America/New_York (US market close).
    Does NOT generate a contribution plan — no cash input required.
    """
    from app.db.supabase_client import get_admin_client
    from app.services.quant_engine import QuantEngine
    from app.db.quant_results import (
        save_quant_result, load_user_bl_views,
    )

    db = get_admin_client()
    engine = QuantEngine()

    # All distinct users with at least one position
    pos_res = db.table("positions").select("user_id").execute()
    user_ids = list({row["user_id"] for row in (pos_res.data or [])})

    if not user_ids:
        log.info("Quant optimization job: no users with positions, skipping.")
        return

    log.info("Quant optimization job: pre-caching for %d user(s)", len(user_ids))

    for user_id in user_ids:
        try:
            settings_res = (
                db.table("user_settings")
                .select("*")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            settings = settings_res.data or {}
            profile = settings.get("investor_profile", "base")
            if profile not in ("conservative", "base", "aggressive"):
                profile = "base"
            rfr = float(settings.get("risk_free_rate", 0.045))

            positions = (
                db.table("positions")
                .select("*")
                .eq("user_id", user_id)
                .execute()
                .data or []
            )
            if not positions:
                continue

            portfolio: dict = {p["ticker"]: {"value_base": 0.0} for p in positions}

            # Motor 1 & 2
            ticker_weight_rules = settings.get("ticker_weight_rules") or {}
            combination_ranges = settings.get("combination_ranges") or {}
            constraints_motor1: dict = {}
            for ticker, rule in ticker_weight_rules.get(profile, {}).items():
                if isinstance(rule, dict):
                    constraints_motor1[ticker] = {
                        "floor": float(rule.get("floor", 0.0)),
                        "cap": float(rule.get("cap", 1.0)),
                    }
            constraints_motor2 = combination_ranges.get(profile, []) or []

            bl_views = load_user_bl_views(user_id)

            engine.rfr = rfr
            result = engine.run_full_optimization(
                portfolio=portfolio,
                profile=profile,
                bl_views=bl_views,
                constraints_motor1=constraints_motor1,
                constraints_motor2=constraints_motor2,
            )
            save_quant_result(user_id, result, profile)
            log.info(
                "  ✓ %s… — %s regime (%.0f%% conf), Sharpe %.2f",
                user_id[:8],
                result.regime,
                result.regime_confidence * 100,
                result.expected_sharpe,
            )
        except Exception as exc:
            log.error("  ✗ %s… — quant optimization failed: %s", user_id[:8], exc)


def _send_telegram_report_all_users() -> None:
    """Send a daily portfolio snapshot via Telegram for every user with positions."""
    from app.db.supabase_client import get_admin_client
    from app.services.market_data import get_quotes, get_historical_multi, get_risk_free_rate
    from app.services.fx_service import get_fx_rates
    from app.services.exchange_classifier import get_native_currency
    from app.compute.portfolio_builder import build_portfolio
    from app.compute.returns import build_portfolio_returns, compute_twr, cum_return_series
    from app.compute.risk import compute_extended_ratios
    from app.services.telegram_service import send_daily_report

    db = get_admin_client()

    pos_res = db.table("positions").select("user_id").execute()
    user_ids = list({row["user_id"] for row in (pos_res.data or [])})

    if not user_ids:
        log.info("Telegram report: no users with positions, skipping.")
        return

    log.info("Telegram report: sending for %d user(s)", len(user_ids))

    for user_id in user_ids:
        try:
            settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
            settings = settings_res.data or {}
            base_currency = settings.get("base_currency", "USD")
            rfr = float(settings.get("risk_free_rate", get_risk_free_rate()))
            bm_ticker = settings.get("preferred_benchmark", "VOO")

            positions = db.table("positions").select("*").eq("user_id", user_id).execute().data or []
            transactions = db.table("transactions").select("*").eq("user_id", user_id).execute().data or []
            tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
            if not tickers:
                continue

            quotes = get_quotes(tickers)
            all_tickers_hist = list(set(tickers + [bm_ticker]))
            exchange_currencies = [get_native_currency(t) for t in tickers]
            pos_currencies = [p.get("currency") or get_native_currency(p["ticker"]) for p in positions]
            currencies = list(set(exchange_currencies + pos_currencies))
            fx_rates = get_fx_rates(currencies, base=base_currency)

            summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)

            # Performance metrics (1y lookback for speed)
            hist = get_historical_multi(all_tickers_hist, period="1y")
            total_shares = sum(float(p["shares"]) for p in positions if float(p.get("shares", 0)) > 0)
            weights = {
                p["ticker"]: float(p["shares"]) / total_shares
                for p in positions if float(p.get("shares", 0)) > 0
            } if total_shares > 0 else {}
            portfolio_returns = build_portfolio_returns(
                {t: hist[t] for t in tickers if t in hist},
                weights,
            )
            bm_hist = hist.get(bm_ticker)
            import pandas as pd
            if bm_hist is not None and not bm_hist.empty:
                col = "Close" if "Close" in bm_hist.columns else bm_hist.columns[0]
                bm_returns = bm_hist[col].pct_change().dropna()
            else:
                bm_returns = pd.Series(dtype=float)

            ratios = compute_extended_ratios(portfolio_returns, bm_returns, rfr)
            twr = compute_twr(portfolio_returns)
            ratios["twr"] = twr * 100

            bm_cum = None
            if not bm_returns.empty:
                bm_cum = float((1 + bm_returns).prod() - 1)

            # AI analysis via Groq/Llama
            ai_text = None
            try:
                from app.services.ai_analysis import generate_daily_analysis
                ai_text = generate_daily_analysis(summary, ratios, base_currency)
            except Exception as ai_exc:
                log.warning("  AI analysis failed: %s", ai_exc)

            # Alerts check
            try:
                from app.services.alerts_service import send_alerts_if_needed
                snapshots_res = (
                    db.table("portfolio_snapshots")
                    .select("snapshot_date,total_value_base")
                    .eq("user_id", user_id)
                    .order("snapshot_date", desc=False)
                    .limit(5)
                    .execute()
                )
                snapshots = snapshots_res.data or []
                send_alerts_if_needed(summary, ratios, snapshots, base_currency)
            except Exception as alert_exc:
                log.warning("  Alerts check failed: %s", alert_exc)

            ok = send_daily_report(
                summary=summary,
                metrics=ratios,
                base_currency=base_currency,
                benchmark_ticker=bm_ticker,
                benchmark_cum=bm_cum,
                ai_analysis=ai_text,
            )
            log.info("  %s %s… — Telegram report sent", "✓" if ok else "✗", user_id[:8])

        except Exception as exc:
            log.error("  ✗ %s… — Telegram report failed: %s", user_id[:8], exc)


def _check_drift_alerts_all_users() -> None:
    """
    Check portfolio drift vs optimal weights for each user with drift alerts enabled.
    Sends email if any position drifts beyond the user's alert threshold.
    Runs daily at 17:00 America/Bogota.
    """
    from app.db.supabase_client import get_admin_client
    from app.db.quant_results import load_latest_quant_result
    from app.services.email_service import send_drift_alert
    from app.services.portfolio_service import load_portfolio_data

    db = get_admin_client()
    pos_res = db.table("positions").select("user_id").execute()
    user_ids = list({row["user_id"] for row in (pos_res.data or [])})
    log.info("Drift alert check: %d user(s)", len(user_ids))

    for user_id in user_ids:
        try:
            settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
            settings = settings_res.data or {}

            if not settings.get("drift_alerts_enabled"):
                continue
            alert_email = settings.get("drift_alert_email", "")
            if not alert_email:
                continue

            alert_threshold = float(settings.get("drift_alert_threshold") or 0.08)
            qr = load_latest_quant_result(user_id)
            if not qr:
                continue

            optimal_weights = qr.get("optimal_weights") or {}
            if not optimal_weights:
                continue

            try:
                summary, tickers, _ = load_portfolio_data(user_id)
            except Exception:
                continue

            total_value = float(summary.total_value_base)
            base_currency = settings.get("base_currency", "USD")
            current_weights = {
                r.ticker: r.value_base / total_value if total_value > 0 else 0.0
                for r in summary.rows
            }

            drifts = []
            for t in set(list(current_weights.keys()) + list(optimal_weights.keys())):
                cw = current_weights.get(t, 0.0)
                ow = float(optimal_weights.get(t, 0.0))
                drift = ow - cw
                if abs(drift) > alert_threshold:
                    drifts.append({
                        "ticker": t,
                        "current_pct": cw * 100,
                        "target_pct": ow * 100,
                        "drift_pct": drift * 100,
                    })

            if drifts:
                drifts.sort(key=lambda d: abs(d["drift_pct"]), reverse=True)
                ok = send_drift_alert(alert_email, drifts, total_value, base_currency)
                log.info("  %s %s… — drift alert sent (%d positions)", "✓" if ok else "✗", user_id[:8], len(drifts))
        except Exception as exc:
            log.error("  ✗ %s… — drift alert failed: %s", user_id[:8], exc)


def _run_dca_for_all_users() -> None:
    """
    Run DCA contribution plan for all users whose day_of_month matches today.
    Runs daily at 09:05 America/Bogota — only executes for matching users.
    """
    from datetime import date
    from app.db.supabase_client import get_admin_client

    today_day = date.today().day
    db = get_admin_client()
    res = (
        db.table("dca_schedule")
        .select("*")
        .eq("day_of_month", today_day)
        .eq("active", True)
        .execute()
    )
    schedules = res.data or []
    if not schedules:
        log.info("DCA job: no schedules for day %d", today_day)
        return

    log.info("DCA job: %d schedule(s) to run for day %d", len(schedules), today_day)

    for sched in schedules:
        user_id = sched["user_id"]
        try:
            from app.routers.contribution import run_contribution_plan, ContributionRequest
            req = ContributionRequest(
                available_cash=float(sched["amount"]),
                profile=sched.get("profile", "base"),
                time_horizon=sched.get("time_horizon", "long"),
                tc_model=sched.get("tc_model", "broker"),
            )
            run_contribution_plan(req, user_id=user_id)
            db.table("dca_schedule").update({"last_run_at": "now()"}).eq("user_id", user_id).execute()
            log.info("  ✓ %s… — DCA run complete (%.2f)", user_id[:8], sched["amount"])
        except Exception as exc:
            log.error("  ✗ %s… — DCA run failed: %s", user_id[:8], exc)


def _run_weekly_agents() -> None:
    """
    Weekly AI agent run (Sundays 18:00 Bogota):
      1. Macro Agent  — fetches macro indicators, suggests macro_overlay, auto-applies if user has no manual override
      2. Portfolio Doctor — holistic health + VaR + drift diagnosis
    Results saved to agent_results table for frontend retrieval.
    """
    from app.db.supabase_client import get_admin_client
    from app.db.quant_results import load_latest_quant_result
    from app.db.agent_results import save_agent_result
    from app.services.agent_pipeline import run_macro_agent, run_portfolio_doctor_agent
    from app.services.market_data import get_quotes
    from app.services.fx_service import get_fx_rates
    from app.services.exchange_classifier import get_native_currency
    from app.compute.portfolio_builder import build_portfolio

    db = get_admin_client()
    pos_res = db.table("positions").select("user_id").execute()
    user_ids = list({row["user_id"] for row in (pos_res.data or [])})

    if not user_ids:
        log.info("Weekly agents: no users with positions, skipping.")
        return

    log.info("Weekly agents: running for %d user(s)", len(user_ids))

    for user_id in user_ids:
        try:
            settings_res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
            settings = settings_res.data or {}
            base_currency = settings.get("base_currency", "USD")

            positions = db.table("positions").select("*").eq("user_id", user_id).execute().data or []
            tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
            if not tickers:
                continue

            # Build current portfolio weights
            shares = {p["ticker"]: float(p["shares"]) for p in positions if float(p.get("shares", 0)) > 0}
            total_shares = sum(shares.values())
            weights = {t: shares[t] / total_shares for t in tickers} if total_shares > 0 else {}

            # Load latest quant result for health metrics
            qr = load_latest_quant_result(user_id)
            expected_sharpe = float((qr or {}).get("expected_sharpe") or 1.0)
            cvar_95 = float((qr or {}).get("cvar_95") or 0.02)
            optimal_weights = (qr or {}).get("optimal_weights") or {}

            # Compute avg drift
            avg_drift = 0.0
            if optimal_weights:
                drifts = [abs(float(optimal_weights.get(t, 0)) - weights.get(t, 0)) for t in set(list(weights) + list(optimal_weights))]
                avg_drift = (sum(drifts) / len(drifts) * 100) if drifts else 0.0

            # Simplified health score from quant metrics
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

            # ── Macro Agent ────────────────────────────────────────────────────
            macro_result = None
            try:
                macro_result = run_macro_agent(tickers, weights, base_currency)
                if macro_result:
                    save_agent_result(user_id, "macro", macro_result, triggered_by="scheduler")
                    # Auto-apply suggested overlay if user has no manual overlay set
                    suggested = macro_result.get("suggested_overlay") or {}
                    existing_overlay = settings.get("macro_overlay") or {}
                    if suggested and not existing_overlay:
                        db.table("user_settings").update({"macro_overlay": suggested}).eq("user_id", user_id).execute()
                        log.info("  ✓ %s… — macro overlay auto-applied: %s", user_id[:8], suggested)
                    log.info("  ✓ %s… — macro agent done (%s)", user_id[:8], macro_result.get("macro_regime", "?"))
            except Exception as exc:
                log.error("  ✗ %s… — macro agent failed: %s", user_id[:8], exc)

            # ── Portfolio Doctor ───────────────────────────────────────────────
            try:
                # Portfolio value for VaR estimate
                quotes = get_quotes(tickers)
                exchange_currencies = [get_native_currency(t) for t in tickers]
                fx_rates = get_fx_rates(list(set(exchange_currencies)), base=base_currency)
                transactions = db.table("transactions").select("*").eq("user_id", user_id).execute().data or []
                summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)
                total_value = float(summary.total_value_base)

                var_1d = total_value * cvar_95 * 0.8
                cvar_1d = total_value * cvar_95

                risk_level = "yellow"
                if macro_result and isinstance(macro_result, dict):
                    macro_regime = macro_result.get("macro_regime", "")
                    if macro_regime == "crisis":
                        risk_level = "red"
                    elif macro_regime in ("risk_on", "goldilocks"):
                        risk_level = "green"

                doctor_result = run_portfolio_doctor_agent(
                    health_score=health_score,
                    health_components=health_components,
                    var_1d=var_1d,
                    cvar_1d=cvar_1d,
                    max_stress_loss_pct=cvar_95 * 300,
                    avg_drift_pct=avg_drift,
                    risk_level=risk_level,
                    base_currency=base_currency,
                )
                if doctor_result:
                    save_agent_result(user_id, "doctor", doctor_result, triggered_by="scheduler")
                    log.info("  ✓ %s… — portfolio doctor done (urgency=%s)", user_id[:8], doctor_result.get("urgency", "?"))
            except Exception as exc:
                log.error("  ✗ %s… — portfolio doctor failed: %s", user_id[:8], exc)

        except Exception as exc:
            log.error("  ✗ %s… — weekly agents failed: %s", user_id[:8], exc)


def _backfill_prediction_prices() -> None:
    """
    Backfill price_30d, price_60d, price_90d in prediction_log for rows
    where the target date has passed but price is still NULL.
    Runs daily at 17:45 America/Bogota.
    """
    from datetime import date, timedelta
    from app.db.supabase_client import get_admin_client
    from app.services.market_data import get_historical_multi

    db = get_admin_client()
    today = date.today()

    # Load rows that need backfilling
    res = db.table("prediction_log").select("id,ticker,run_at,price_30d,price_60d,price_90d").execute()
    rows = res.data or []
    if not rows:
        return

    # Group tickers that need prices
    needs_update: list[dict] = []
    for r in rows:
        run_date = date.fromisoformat(r["run_at"][:10]) if r.get("run_at") else None
        if not run_date:
            continue
        need = {}
        if r.get("price_30d") is None and (today - run_date).days >= 30:
            need["price_30d"] = run_date + timedelta(days=30)
        if r.get("price_60d") is None and (today - run_date).days >= 60:
            need["price_60d"] = run_date + timedelta(days=60)
        if r.get("price_90d") is None and (today - run_date).days >= 90:
            need["price_90d"] = run_date + timedelta(days=90)
        if need:
            needs_update.append({"id": r["id"], "ticker": r["ticker"], "run_date": run_date, "need": need})

    if not needs_update:
        log.info("Prediction backfill: nothing to update")
        return

    # Fetch historical data per ticker
    all_tickers = list({r["ticker"] for r in needs_update})
    try:
        hist = get_historical_multi(all_tickers, period="1y")
    except Exception as exc:
        log.error("Prediction backfill: hist fetch failed: %s", exc)
        return

    def _price_on(ticker: str, target_date: date) -> float | None:
        df = hist.get(ticker)
        if df is None or df.empty:
            return None
        col = "Close" if "Close" in df.columns else df.columns[0]
        # Find closest date on or after target
        import pandas as pd
        target_ts = pd.Timestamp(target_date)
        after = df[col].dropna()
        after = after[after.index >= target_ts]
        if after.empty:
            return None
        return float(after.iloc[0])

    updated = 0
    for item in needs_update:
        updates: dict = {}
        for col, target_date in item["need"].items():
            p = _price_on(item["ticker"], target_date)
            if p is not None:
                updates[col] = p
                # Compute realized return if entry_price is available
        if updates:
            try:
                db.table("prediction_log").update(updates).eq("id", item["id"]).execute()
                updated += 1
            except Exception as exc:
                log.warning("Prediction backfill update failed for %s: %s", item["id"], exc)

    log.info("Prediction backfill: updated %d rows", updated)


def start_scheduler() -> BackgroundScheduler:
    """Create and start the APScheduler instance. Returns it so the caller can shut it down."""
    scheduler = BackgroundScheduler(timezone="America/Bogota")
    scheduler.add_job(
        _snapshot_all_users,
        trigger=CronTrigger(hour=17, minute=30, timezone="America/Bogota"),
        id="daily_snapshot",
        replace_existing=True,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        _optimize_all_users,
        trigger=CronTrigger(hour=16, minute=5, timezone="America/New_York"),
        id="daily_quant_optimization",
        replace_existing=True,
        misfire_grace_time=1800,  # allow up to 30-min late fire
    )
    scheduler.add_job(
        _send_telegram_report_all_users,
        trigger=CronTrigger(hour=17, minute=35, timezone="America/Bogota"),
        id="daily_telegram_report",
        replace_existing=True,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        _check_drift_alerts_all_users,
        trigger=CronTrigger(hour=17, minute=0, timezone="America/Bogota"),
        id="daily_drift_alerts",
        replace_existing=True,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        _run_dca_for_all_users,
        trigger=CronTrigger(hour=9, minute=5, timezone="America/Bogota"),
        id="daily_dca",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _backfill_prediction_prices,
        trigger=CronTrigger(hour=17, minute=45, timezone="America/Bogota"),
        id="daily_prediction_backfill",
        replace_existing=True,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        _run_weekly_agents,
        trigger=CronTrigger(day_of_week="sun", hour=18, minute=0, timezone="America/Bogota"),
        id="weekly_agents",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    log.info(
        "Schedulers started — snapshot: 17:30 Bogota | quant: 16:05 New York | telegram: 17:35 Bogota | drift-alerts: 17:00 Bogota | dca: 09:05 Bogota | prediction-backfill: 17:45 Bogota | weekly-agents: Sun 18:00 Bogota"
    )
    return scheduler
