from fastapi import APIRouter, Depends, HTTPException
from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client
from app.models.portfolio import PortfolioSummary, PositionCreate, PositionUpdate, Snapshot, SnapshotCreate
from app.services.market_data import get_quotes
from app.services.fx_service import get_fx_rates
from app.compute.portfolio_builder import build_portfolio
from app.services.exchange_classifier import get_native_currency
from datetime import date

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _get_settings_for_user(user_id: str) -> dict:
    db = get_admin_client()
    res = db.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    return res.data or {}


@router.get("", response_model=PortfolioSummary)
def get_portfolio(user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    settings = _get_settings_for_user(user_id)
    base_currency = settings.get("base_currency", "USD")

    # Load positions
    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    if not positions:
        from app.models.portfolio import PortfolioSummary
        from datetime import datetime, timezone
        return PortfolioSummary(
            rows=[], total_value_base=0, base_currency=base_currency,
            as_of=datetime.now(timezone.utc),
        )

    # Load transactions for avg cost
    tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
    transactions = tx_res.data or []

    # Fetch live prices
    tickers = [p["ticker"] for p in positions]
    quotes = get_quotes(tickers)

    # Build FX rates — include both exchange native currencies (for price) and
    # position DB currencies (for avg cost, which the user may have entered in a
    # different currency, e.g. USD for a XETRA-listed ETF bought via XTB)
    exchange_currencies = [get_native_currency(t) for t in tickers]
    pos_currencies = [p.get("currency") or get_native_currency(p["ticker"]) for p in positions]
    currencies = list(set(exchange_currencies + pos_currencies))
    fx_rates = get_fx_rates(currencies, base=base_currency)

    return build_portfolio(positions, quotes, fx_rates, base_currency, transactions)


@router.get("/positions")
def get_positions(user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    res = db.table("positions").select("*").eq("user_id", user_id).execute()
    return res.data or []


@router.post("/positions", status_code=201)
def create_position(body: PositionCreate, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    data = body.model_dump()
    data["user_id"] = user_id
    res = db.table("positions").upsert(data, on_conflict="user_id,ticker").execute()
    return res.data[0] if res.data else {}


@router.put("/positions/{ticker}")
def update_position(ticker: str, body: PositionUpdate, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    update = {k: v for k, v in body.model_dump().items() if v is not None}
    res = db.table("positions").update(update).eq("user_id", user_id).eq("ticker", ticker).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Position not found")
    return res.data[0]


@router.delete("/positions/{ticker}", status_code=204)
def delete_position(ticker: str, user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    db.table("positions").delete().eq("user_id", user_id).eq("ticker", ticker).execute()


# ── Snapshots ─────────────────────────────────────────────────────────────────

@router.get("/snapshots", response_model=list[Snapshot])
def list_snapshots(user_id: str = Depends(get_user_id)):
    db = get_admin_client()
    res = db.table("portfolio_snapshots").select("*").eq("user_id", user_id)\
        .order("snapshot_date", desc=True).limit(365).execute()
    return res.data or []


@router.post("/snapshots", status_code=201, response_model=Snapshot)
def save_snapshot(body: SnapshotCreate, user_id: str = Depends(get_user_id)):
    snapshot_date = body.snapshot_date or str(date.today())
    db = get_admin_client()
    settings = _get_settings_for_user(user_id)
    base_currency = settings.get("base_currency", "USD")

    # Build current portfolio
    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
    transactions = tx_res.data or []

    tickers = [p["ticker"] for p in positions]
    quotes = get_quotes(tickers) if tickers else {}
    if tickers:
        exchange_currencies = [get_native_currency(t) for t in tickers]
        pos_currencies = [p.get("currency") or get_native_currency(p["ticker"]) for p in positions]
        currencies = list(set(exchange_currencies + pos_currencies))
    else:
        currencies = []
    fx_rates = get_fx_rates(currencies, base=base_currency) if currencies else {}
    summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)

    row = {
        "user_id": user_id,
        "snapshot_date": snapshot_date,
        "total_value_base": summary.total_value_base,
        "base_currency": base_currency,
        "holdings": [r.model_dump() for r in summary.rows],
        "metadata": body.notes,
    }
    res = db.table("portfolio_snapshots").upsert(row, on_conflict="user_id,snapshot_date").execute()
    return res.data[0] if res.data else row
