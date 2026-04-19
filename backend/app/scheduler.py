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
    scheduler.start()
    log.info(
        "Schedulers started — snapshot: 17:30 Bogota | quant: 16:05 New York"
    )
    return scheduler
