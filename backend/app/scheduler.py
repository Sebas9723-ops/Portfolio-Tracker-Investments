"""
Daily portfolio snapshot scheduler.
Runs at 17:30 Colombia time (UTC-5 = 22:30 UTC) every day.
Saves one snapshot per user; upserts on (user_id, snapshot_date) so re-runs are idempotent.
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


def start_scheduler() -> BackgroundScheduler:
    """Create and start the APScheduler instance. Returns it so the caller can shut it down."""
    scheduler = BackgroundScheduler(timezone="America/Bogota")
    scheduler.add_job(
        _snapshot_all_users,
        trigger=CronTrigger(hour=17, minute=30, timezone="America/Bogota"),
        id="daily_snapshot",
        replace_existing=True,
        misfire_grace_time=600,   # allow up to 10-min late fire if server was down
    )
    scheduler.start()
    log.info("Snapshot scheduler started — fires daily at 17:30 America/Bogota")
    return scheduler
