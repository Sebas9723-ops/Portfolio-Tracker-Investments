from fastapi import APIRouter, Depends, HTTPException, Query
from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client
from app.models.portfolio import PortfolioSummary, PositionCreate, PositionUpdate, Snapshot, SnapshotCreate
from app.services.market_data import get_quotes
from app.services.fx_service import get_fx_rates, _FX_PAIR_MAP, _FALLBACK_RATES
from app.compute.portfolio_builder import build_portfolio
from app.services.exchange_classifier import get_native_currency, yf_ticker
from datetime import date, timedelta

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


# ── Portfolio history (auto, no snapshots needed) ─────────────────────────────

@router.get("/history")
def get_portfolio_history(
    start: str = Query(default="2026-03-01"),
    user_id: str = Depends(get_user_id),
):
    """
    Reconstructs daily portfolio value from historical prices + transactions.
    No manual snapshots required. Returns [{date, value}] sorted by date.
    """
    import pandas as pd
    import yfinance as yf

    db = get_admin_client()
    settings = _get_settings_for_user(user_id)
    base_currency = settings.get("base_currency", "USD")

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    if not positions:
        return []

    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
    if not tickers:
        return []

    current_shares = {p["ticker"]: float(p.get("shares", 0)) for p in positions}

    tx_res = (
        db.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .order("date")
        .execute()
    )
    transactions = tx_res.data or []

    end_str = str(date.today() + timedelta(days=1))

    # ── Historical prices ──────────────────────────────────────────────────────
    yf_map = {yf_ticker(t): t for t in tickers}
    try:
        raw = yf.download(
            list(yf_map.keys()),
            start=start,
            end=end_str,
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
        if isinstance(raw.columns, pd.MultiIndex):
            price_df = raw["Close"].rename(columns=yf_map)
        elif "Close" in raw.columns:
            orig = list(yf_map.values())[0]
            price_df = raw[["Close"]].rename(columns={"Close": orig})
        else:
            return []
        price_df = price_df.ffill()
    except Exception:
        return []

    if price_df.empty:
        return []

    # ── Historical FX rates ────────────────────────────────────────────────────
    exchange_currencies = list(set(get_native_currency(t) for t in tickers))
    non_base = [c for c in exchange_currencies if c != base_currency]

    # Build fx_df aligned to price_df index
    fx_df = pd.DataFrame(index=price_df.index)
    for ccy in exchange_currencies:
        if ccy == base_currency:
            fx_df[ccy] = 1.0

    if non_base:
        fx_symbols = [_FX_PAIR_MAP.get(c, f"{c}{base_currency}=X") for c in non_base if _FX_PAIR_MAP.get(c)]
        if fx_symbols:
            try:
                fx_raw = yf.download(
                    fx_symbols,
                    start=start,
                    end=end_str,
                    interval="1d",
                    auto_adjust=False,
                    progress=False,
                )
                if isinstance(fx_raw.columns, pd.MultiIndex):
                    fx_closes = fx_raw["Close"]
                elif "Close" in fx_raw.columns:
                    fx_closes = fx_raw[["Close"]].rename(columns={"Close": fx_symbols[0]})
                else:
                    fx_closes = fx_raw
                fx_closes = fx_closes.ffill()
                for ccy in non_base:
                    sym = _FX_PAIR_MAP.get(ccy, f"{ccy}{base_currency}=X")
                    if sym in fx_closes.columns:
                        fx_df[ccy] = fx_closes[sym].reindex(price_df.index).ffill()
                    else:
                        fx_df[ccy] = _FALLBACK_RATES.get(ccy, 1.0)
            except Exception:
                for ccy in non_base:
                    fx_df[ccy] = _FALLBACK_RATES.get(ccy, 1.0)
        else:
            for ccy in non_base:
                fx_df[ccy] = _FALLBACK_RATES.get(ccy, 1.0)

    # ── Reconstruct shares held on each day ────────────────────────────────────
    # Replay BUY/SELL transactions before start_date to get the initial state
    running: dict[str, float] = {t: 0.0 for t in tickers}
    for tx in transactions:
        tx_date = (tx.get("date") or "")[:10]
        if tx_date >= start:
            break
        ticker = tx.get("ticker", "")
        if ticker not in running:
            continue
        qty = float(tx.get("quantity", 0))
        if tx.get("action") == "BUY":
            running[ticker] += qty
        elif tx.get("action") == "SELL":
            running[ticker] = max(0.0, running[ticker] - qty)

    # If no transactions at all before start, fall back to current shares
    if all(v == 0.0 for v in running.values()):
        running = dict(current_shares)

    # Index transactions >= start_date by date
    changes: dict[str, dict[str, float]] = {}
    for tx in transactions:
        tx_date = (tx.get("date") or "")[:10]
        if tx_date < start:
            continue
        ticker = tx.get("ticker", "")
        if ticker not in tickers:
            continue
        qty = float(tx.get("quantity", 0))
        delta = qty if tx.get("action") == "BUY" else -qty
        changes.setdefault(tx_date, {})[ticker] = changes.get(tx_date, {}).get(ticker, 0) + delta

    # ── Build daily series ─────────────────────────────────────────────────────
    result = []
    for day in price_df.index:
        day_str = str(day.date())

        if day_str in changes:
            for ticker, delta in changes[day_str].items():
                running[ticker] = max(0.0, running.get(ticker, 0) + delta)

        total = 0.0
        for ticker in tickers:
            shares = running.get(ticker, 0.0)
            if shares <= 0 or ticker not in price_df.columns:
                continue
            price = price_df[ticker].get(day)
            if price is None or pd.isna(price):
                continue
            ccy = get_native_currency(ticker)
            fx = float(fx_df[ccy].get(day, 1.0)) if ccy in fx_df.columns else 1.0
            if pd.isna(fx):
                fx = _FALLBACK_RATES.get(ccy, 1.0)
            total += shares * float(price) * fx

        if total > 0:
            result.append({"date": day_str, "value": round(total, 2)})

    return result


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
