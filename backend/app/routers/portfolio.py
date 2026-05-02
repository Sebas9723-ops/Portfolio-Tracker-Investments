from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from app.auth.dependencies import get_user_id
from app.db.supabase_client import get_admin_client
from app.models.portfolio import PortfolioSummary, PositionCreate, PositionUpdate, Snapshot, SnapshotCreate
from app.services.market_data import get_quotes
from app.services.fx_service import get_fx_rates, _FX_PAIR_MAP, _FALLBACK_RATES
from app.compute.portfolio_builder import build_portfolio, compute_realized_pnl
from app.services.exchange_classifier import get_native_currency, yf_ticker
from app.services import cache
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

    summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)
    summary.pending_tickers = [
        p["ticker"] for p in positions if float(p.get("shares", 0)) == 0
    ]
    return summary


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

    tx_res = (
        db.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .order("date")
        .execute()
    )
    transactions = tx_res.data or []

    # Current tickers (shares > 0)
    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]

    # ALL tickers ever bought/sold — needed to reconstruct history for sold positions.
    # Without this, selling a ticker causes a false $0 drop in historical value.
    all_tx_tickers = list({
        tx["ticker"] for tx in transactions
        if tx.get("ticker") and tx.get("action") in ("BUY", "SELL")
    })
    all_tickers = list(set(tickers + all_tx_tickers))

    if not all_tickers:
        return []

    current_shares = {p["ticker"]: float(p.get("shares", 0)) for p in positions}

    # Use today as exclusive end so the last bar is yesterday's confirmed close.
    # Today's live value is already shown in the portfolio header; including
    # today's incomplete intraday bar causes a misleading drop in the chart.
    end_str = str(date.today())

    # ── Historical prices ──────────────────────────────────────────────────────
    # Use all_tickers (includes sold positions) so history is never broken.
    yf_map = {yf_ticker(t): t for t in all_tickers}
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
        # Deduplicate: yfinance occasionally returns two rows for the same
        # calendar date (tz-aware timestamps that collapse to the same date).
        # lightweight-charts requires strictly ascending dates, so keep the last.
        price_df.index = price_df.index.normalize()
        price_df = price_df[~price_df.index.duplicated(keep="last")]
        # Drop the last row when it corresponds to today's date (UTC).
        if len(price_df) > 1:
            last_row_date = price_df.index[-1].date()
            if last_row_date >= date.today():
                price_df = price_df.iloc[:-1]
    except Exception:
        return []

    if price_df.empty:
        return []

    # ── Historical FX rates ────────────────────────────────────────────────────
    exchange_currencies = list(set(get_native_currency(t) for t in all_tickers))
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
    # Replay BUY/SELL transactions before start_date to get the initial state.
    # Use all_tickers so sold positions are tracked correctly in history.
    running: dict[str, float] = {t: 0.0 for t in all_tickers}
    for tx in transactions:
        tx_date = (tx.get("date") or "")[:10]
        if tx_date >= start:
            break
        ticker = tx.get("ticker", "")
        if ticker not in running:
            running[ticker] = 0.0
        qty = float(tx.get("quantity", 0))
        if tx.get("action") == "BUY":
            running[ticker] += qty
        elif tx.get("action") == "SELL":
            running[ticker] = max(0.0, running[ticker] - qty)

    # Fall back to current shares only when there are zero BUY/SELL transactions.
    has_buy_sell = any(tx.get("action") in ("BUY", "SELL") for tx in transactions)
    if not has_buy_sell and all(v == 0.0 for v in running.values()):
        running = dict(current_shares)

    # Index BUY/SELL transactions >= start_date by date.
    # DIVIDEND and other actions must be excluded — they do not change share count
    # and treating them as sells would collapse positions on dividend dates.
    changes: dict[str, dict[str, float]] = {}
    for tx in transactions:
        if tx.get("action") not in ("BUY", "SELL"):
            continue
        tx_date = (tx.get("date") or "")[:10]
        if tx_date < start:
            continue
        ticker = tx.get("ticker", "")
        qty = float(tx.get("quantity", 0))
        delta = qty if tx.get("action") == "BUY" else -qty
        changes.setdefault(tx_date, {})[ticker] = changes.get(tx_date, {}).get(ticker, 0) + delta

    # ── Capital invested step function from BUY transactions ──────────────────
    # Accumulate invested capital using historical FX at each transaction date.
    # BUY transactions before start_date count toward the opening balance.
    has_buy_txs = any(tx.get("action") == "BUY" for tx in transactions)
    cumulative_invested = 0.0
    if has_buy_txs:
        for tx in transactions:
            if tx.get("action") != "BUY":
                continue
            tx_date = (tx.get("date") or "")[:10]
            if tx_date >= start:
                break
            qty = float(tx.get("quantity", 0))
            price_n = float(tx.get("price_native", 0) or 0)
            fee_n = float(tx.get("fee_native", 0) or 0)
            tx_ticker = tx.get("ticker", "")
            tx_ccy = tx.get("currency") or get_native_currency(tx_ticker)
            # Use current FX as best approximation for pre-window transactions
            fx_cur = _FALLBACK_RATES.get(tx_ccy, 1.0) if base_currency != tx_ccy else 1.0
            cumulative_invested += (qty * price_n + fee_n) * fx_cur

    # Index BUY transactions >= start_date for the day loop
    capital_changes: dict[str, list[dict]] = {}
    if has_buy_txs:
        for tx in transactions:
            if tx.get("action") != "BUY":
                continue
            tx_date = (tx.get("date") or "")[:10]
            if tx_date < start:
                continue
            tx_ticker = tx.get("ticker", "")
            qty = float(tx.get("quantity", 0))
            price_n = float(tx.get("price_native", 0) or 0)
            fee_n = float(tx.get("fee_native", 0) or 0)
            tx_ccy = tx.get("currency") or get_native_currency(tx_ticker)
            capital_changes.setdefault(tx_date, []).append({
                "amount_native": qty * price_n + fee_n,
                "currency": tx_ccy,
            })

    # ── Build daily series ─────────────────────────────────────────────────────
    result = []
    for day in price_df.index:
        day_str = str(day.date())

        if day_str in changes:
            for ticker, delta in changes[day_str].items():
                running[ticker] = max(0.0, running.get(ticker, 0) + delta)

        # Apply capital events for this day using historical FX
        if day_str in capital_changes:
            for event in capital_changes[day_str]:
                ccy = event["currency"]
                if base_currency == ccy:
                    fx_inv = 1.0
                elif ccy in fx_df.columns:
                    fx_inv = float(fx_df[ccy].get(day, _FALLBACK_RATES.get(ccy, 1.0)))
                    if pd.isna(fx_inv):
                        fx_inv = _FALLBACK_RATES.get(ccy, 1.0)
                else:
                    fx_inv = _FALLBACK_RATES.get(ccy, 1.0)
                cumulative_invested += event["amount_native"] * fx_inv

        total = 0.0
        for ticker in all_tickers:
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

    # ── Load capital snapshots and interpolate invested per day ───────────────
    snap_res = (
        db.table("portfolio_snapshots")
        .select("snapshot_date,invested_base")
        .eq("user_id", user_id)
        .not_.is_("invested_base", "null")
        .order("snapshot_date")
        .execute()
    )
    capital_snaps = {s["snapshot_date"]: s["invested_base"] for s in (snap_res.data or []) if s.get("invested_base")}

    if capital_snaps:
        # Forward-fill: for each day, use the most recent snapshot on or before that date
        snap_dates = sorted(capital_snaps.keys())
        for point in result:
            d = point["date"]
            # Find last snapshot <= d
            invested_val = None
            for sd in snap_dates:
                if sd <= d:
                    invested_val = capital_snaps[sd]
                else:
                    break
            if invested_val is not None:
                point["invested"] = round(invested_val, 2)

    # Guarantee strict ascending order and no duplicate dates so the chart
    # never throws an assertion error regardless of yfinance quirks.
    result.sort(key=lambda x: x["date"])
    seen: set[str] = set()
    deduped = []
    for item in result:
        if item["date"] not in seen:
            seen.add(item["date"])
            deduped.append(item)
    return deduped


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


# ── Capital snapshot (auto-saved when positions change in Manage) ─────────────

@router.post("/capital-snapshot", status_code=200)
def save_capital_snapshot(user_id: str = Depends(get_user_id)):
    """
    Calculates total_invested_base (shares × avg_cost × FX) for the current
    positions and upserts it into portfolio_snapshots for today's date.
    Called automatically by the frontend whenever a position is saved.
    """
    snapshot_date = str(date.today())
    db = get_admin_client()
    settings = _get_settings_for_user(user_id)
    base_currency = settings.get("base_currency", "USD")

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []

    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
    exchange_currencies = [get_native_currency(t) for t in tickers]
    pos_currencies = [p.get("currency") or get_native_currency(p["ticker"]) for p in positions]
    currencies = list(set(exchange_currencies + pos_currencies))
    fx_rates = get_fx_rates(currencies, base=base_currency) if currencies else {}

    invested = 0.0
    for p in positions:
        shares = float(p.get("shares", 0))
        avg_cost = float(p.get("avg_cost_native") or 0)
        if shares <= 0 or avg_cost <= 0:
            continue
        pos_ccy = p.get("currency") or get_native_currency(p["ticker"])
        fx = fx_rates.get(pos_ccy, 1.0)
        invested += shares * avg_cost * fx

    # Upsert: if a snapshot already exists for today, update invested_base only
    existing = (
        db.table("portfolio_snapshots")
        .select("id")
        .eq("user_id", user_id)
        .eq("snapshot_date", snapshot_date)
        .maybe_single()
        .execute()
    )
    if existing.data:
        db.table("portfolio_snapshots").update({"invested_base": round(invested, 2)}).eq("id", existing.data["id"]).execute()
    else:
        db.table("portfolio_snapshots").insert({
            "user_id": user_id,
            "snapshot_date": snapshot_date,
            "base_currency": base_currency,
            "invested_base": round(invested, 2),
        }).execute()

    return {"snapshot_date": snapshot_date, "invested_base": round(invested, 2)}


@router.post("/capital-snapshot/backfill", status_code=200)
def backfill_capital_snapshots(user_id: str = Depends(get_user_id)):
    """
    One-time backfill: reads all positions with their created_at dates,
    builds a cumulative capital step function, and inserts snapshots for
    each date a new position was added. Skips dates already in snapshots.
    Uses current FX as best approximation for historical invested amounts.
    """
    db = get_admin_client()
    settings = _get_settings_for_user(user_id)
    base_currency = settings.get("base_currency", "USD")

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = [p for p in (pos_res.data or []) if float(p.get("shares", 0)) > 0 and p.get("avg_cost_native")]

    if not positions:
        return {"created": 0}

    # Build FX rates once using current rates
    all_ccys = list({p.get("currency") or get_native_currency(p["ticker"]) for p in positions})
    fx_rates = get_fx_rates(all_ccys, base=base_currency) if all_ccys else {}

    # Sort positions by created_at date
    def pos_date(p: dict) -> str:
        raw = p.get("created_at") or ""
        return raw[:10]  # YYYY-MM-DD

    positions_sorted = sorted(positions, key=pos_date)

    # Build cumulative invested at each unique date
    # Group by date → sum up all positions created on or before each date
    unique_dates = sorted({pos_date(p) for p in positions_sorted if pos_date(p)})

    # Check which dates already have snapshots
    existing_res = (
        db.table("portfolio_snapshots")
        .select("snapshot_date")
        .eq("user_id", user_id)
        .not_.is_("invested_base", "null")
        .execute()
    )
    existing_dates = {r["snapshot_date"] for r in (existing_res.data or [])}

    created = 0
    for d in unique_dates:
        if d in existing_dates:
            continue
        # Sum invested for all positions created on or before this date
        invested = 0.0
        for p in positions_sorted:
            if pos_date(p) > d:
                break
            shares = float(p.get("shares", 0))
            avg_cost = float(p.get("avg_cost_native") or 0)
            pos_ccy = p.get("currency") or get_native_currency(p["ticker"])
            fx = fx_rates.get(pos_ccy, 1.0)
            invested += shares * avg_cost * fx

        if invested > 0:
            db.table("portfolio_snapshots").insert({
                "user_id": user_id,
                "snapshot_date": d,
                "base_currency": base_currency,
                "invested_base": round(invested, 2),
            }).execute()
            created += 1

    return {"created": created, "dates": unique_dates}


# ── ETF region override map (explicit overrides, takes priority) ──────────────
_REGION_OVERRIDES: dict[str, dict[str, float]] = {
    "VWCE.DE": {"North America": 0.62, "Europe": 0.18, "Pacific": 0.11, "Emerging Markets": 0.09},
}

# ── Category → region inference ───────────────────────────────────────────────
_CATEGORY_REGION: dict[str, dict[str, float]] = {
    # US categories
    "large blend":              {"North America": 1.0},
    "large growth":             {"North America": 1.0},
    "large value":              {"North America": 1.0},
    "mid-cap blend":            {"North America": 1.0},
    "mid-cap growth":           {"North America": 1.0},
    "small blend":              {"North America": 1.0},
    "small growth":             {"North America": 1.0},
    "technology":               {"North America": 1.0},
    # Global
    "world stock":              {"North America": 0.62, "Europe": 0.18, "Pacific": 0.11, "Emerging Markets": 0.09},
    "foreign large blend":      {"Europe": 0.45, "Pacific": 0.30, "Emerging Markets": 0.25},
    "foreign large growth":     {"Europe": 0.45, "Pacific": 0.30, "Emerging Markets": 0.25},
    # Emerging
    "diversified emerging mkts":{"Emerging Markets": 1.0},
    "china region":             {"Emerging Markets": 1.0},
    "india equity":             {"Emerging Markets": 1.0},
    "latin america stock":      {"Emerging Markets": 1.0},
    # Regional
    "europe stock":             {"Europe": 1.0},
    "eurozone stock":           {"Europe": 1.0},
    "japan stock":              {"Pacific": 1.0},
    "pacific/asia stock":       {"Pacific": 0.70, "Emerging Markets": 0.30},
    # Commodities
    "precious metals":          {"Gold": 1.0},
    "commodities broad basket": {"Commodities": 1.0},
}

# Keywords to match in longName (checked in order, first match wins)
_NAME_KEYWORDS: list[tuple[list[str], dict[str, float]]] = [
    (["gold", "silver", "precious", "physical gold", "physical silver"],
     {"Gold": 1.0}),
    (["commodity", "commodities"],
     {"Commodities": 1.0}),
    (["all-world", "all world", "acwi", "global equity", "world etf", "ftse global"],
     {"North America": 0.62, "Europe": 0.18, "Pacific": 0.11, "Emerging Markets": 0.09}),
    (["emerging market", "emerging mkts", "msci em ", "msci emerging"],
     {"Emerging Markets": 1.0}),
    (["europe small", "european small", "msci europe", "stoxx europe", "euro stoxx",
      "ftse europe", "spdr europe", "european defence", "european defense"],
     {"Europe": 1.0}),
    (["s&p 500", "s&p500", "nasdaq 100", "nasdaq-100", "dow jones", "russell 2000",
      "russell 1000", "us equity", "us stock"],
     {"North America": 1.0}),
    (["japan", "nikkei", "topix"],
     {"Pacific": 1.0}),
    (["asia pacific", "asia-pacific"],
     {"Pacific": 0.70, "Emerging Markets": 0.30}),
    (["china", "hong kong", "india", "brazil", "latam", "latin america"],
     {"Emerging Markets": 1.0}),
]


def _infer_regions(ticker: str, info: dict) -> dict[str, float]:
    """Infer region allocation from yfinance info (category + longName)."""
    # 1. Explicit override
    if ticker in _REGION_OVERRIDES:
        return _REGION_OVERRIDES[ticker]

    # 2. Category match
    category = (info.get("category") or "").lower().strip()
    if category and category in _CATEGORY_REGION:
        return _CATEGORY_REGION[category]

    # 3. longName keyword match
    name = (info.get("longName") or info.get("shortName") or "").lower()
    for keywords, regions in _NAME_KEYWORDS:
        if any(kw in name for kw in keywords):
            return regions

    # 4. quoteType fallback — ETF with no match → assume broad US/global
    return {"North America": 1.0}


_SECTOR_LABELS: dict[str, str] = {
    "realestate":             "Real Estate",
    "consumer_cyclical":      "Consumer Cyclical",
    "basic_materials":        "Basic Materials",
    "consumer_defensive":     "Consumer Defensive",
    "technology":             "Technology",
    "communication_services": "Communication Services",
    "financial_services":     "Financial Services",
    "utilities":              "Utilities",
    "industrials":            "Industrials",
    "energy":                 "Energy",
    "healthcare":             "Healthcare",
}


def _fetch_etf_breakdown(ticker: str) -> tuple[str, dict, dict]:
    """Fetch sector + region data for a single ETF. Runs in thread pool."""
    import yfinance as yf
    cache_key = f"etf_breakdown:{ticker}"
    cached = cache.get(cache_key)
    if cached:
        return ticker, cached["sector_weights"], cached["info"]

    yft = yf_ticker(ticker)
    yf_obj = yf.Ticker(yft)

    sector_weights: dict[str, float] = {}
    try:
        fd = yf_obj.funds_data
        for key, pct in fd.sector_weightings.items():
            label = _SECTOR_LABELS.get(key, key.replace("_", " ").title())
            sector_weights[label] = float(pct)
    except Exception:
        sector_weights = {}

    try:
        info = yf_obj.info or {}
    except Exception:
        info = {}

    cache.set(cache_key, {"sector_weights": sector_weights, "info": info}, ttl=3600)
    return ticker, sector_weights, info


@router.get("/realized-pnl")
def get_realized_pnl(user_id: str = Depends(get_user_id)):
    """Realized P&L per ticker from closed SELL transactions (FIFO, native currency)."""
    db = get_admin_client()
    res = db.table("transactions").select("*").eq("user_id", user_id).execute()
    return compute_realized_pnl(res.data or [])


@router.get("/dividend-forecast")
def get_dividend_forecast(user_id: str = Depends(get_user_id)):
    """Estimate forward annual dividend income using yfinance trailing yields."""
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor

    db = get_admin_client()
    settings = _get_settings_for_user(user_id)
    base_currency = settings.get("base_currency", "USD")

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    if not positions:
        return {"positions": [], "total_annual": 0.0, "monthly": 0.0, "base_currency": base_currency}

    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
    quotes = get_quotes(tickers)
    exchange_currencies = [get_native_currency(t) for t in tickers]
    pos_currencies = [p.get("currency") or get_native_currency(p["ticker"]) for p in positions]
    currencies = list(set(exchange_currencies + pos_currencies))
    fx_rates = get_fx_rates(currencies, base=base_currency) if currencies else {}
    tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
    transactions = tx_res.data or []
    summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)

    value_map = {row.ticker: row.value_base for row in summary.rows}
    name_map = {row.ticker: (row.name or row.ticker) for row in summary.rows}

    def _fetch_yield(ticker: str) -> tuple[str, float]:
        try:
            info = yf.Ticker(yf_ticker(ticker)).info
            y = (info.get("trailingAnnualDividendYield") or info.get("dividendYield") or 0.0)
            return ticker, float(y or 0.0)
        except Exception:
            return ticker, 0.0

    with ThreadPoolExecutor(max_workers=8) as pool:
        yields = dict(pool.map(_fetch_yield, tickers))

    result = []
    for ticker in tickers:
        val = value_map.get(ticker, 0.0)
        dy = yields.get(ticker, 0.0)
        result.append({
            "ticker": ticker,
            "name": name_map.get(ticker, ticker),
            "value_base": round(val, 2),
            "dividend_yield": round(dy * 100, 3),
            "annual_income": round(val * dy, 2),
        })

    result.sort(key=lambda x: -x["annual_income"])
    total_annual = sum(r["annual_income"] for r in result)
    return {
        "positions": result,
        "total_annual": round(total_annual, 2),
        "monthly": round(total_annual / 12, 2),
        "base_currency": base_currency,
    }


@router.get("/report.pdf")
def download_report(
    period: str = Query(default="1y"),
    user_id: str = Depends(get_user_id),
):
    """Generate and download a PDF portfolio report."""
    import io
    from app.services.pdf_service import generate_portfolio_report
    from app.services.market_data import get_historical_multi, get_risk_free_rate
    from app.compute.returns import build_portfolio_returns, compute_twr
    from app.compute.risk import compute_extended_ratios

    db = get_admin_client()
    settings = _get_settings_for_user(user_id)
    base_currency = settings.get("base_currency", "USD")
    bm_ticker = settings.get("preferred_benchmark", "VOO")
    rfr = float(settings.get("risk_free_rate") or get_risk_free_rate())

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
    transactions = tx_res.data or []
    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]

    quotes = get_quotes(tickers) if tickers else {}
    exchange_currencies = [get_native_currency(t) for t in tickers]
    pos_currencies = [p.get("currency") or get_native_currency(p["ticker"]) for p in positions]
    currencies = list(set(exchange_currencies + pos_currencies))
    fx_rates = get_fx_rates(currencies, base=base_currency) if currencies else {}
    summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)

    # Compute analytics metrics
    metrics: dict = {"twr": 0.0}
    try:
        import pandas as pd
        all_tickers = list(set(tickers + [bm_ticker]))
        hist = get_historical_multi(all_tickers, period=period)
        weights = {r.ticker: r.weight / 100 for r in summary.rows}
        portfolio_returns = build_portfolio_returns(
            {t: hist[t] for t in tickers if t in hist},
            weights,
        )
        bm_hist = hist.get(bm_ticker)
        bm_returns = (
            bm_hist[bm_hist.columns[0]].pct_change().dropna()
            if bm_hist is not None and not bm_hist.empty else pd.Series(dtype=float)
        )
        ratios = compute_extended_ratios(portfolio_returns, bm_returns, rfr)
        twr = compute_twr(portfolio_returns)
        metrics = {**ratios, "twr": twr * 100, "benchmark_ticker": bm_ticker}
    except Exception:
        pass

    pdf_bytes = generate_portfolio_report(summary, metrics, base_currency, bm_ticker)
    filename = f"portfolio_report_{date.today()}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import/positions")
async def import_positions_csv(
    file: UploadFile = File(...),
    mode: str = Query(default="upsert", description="upsert or skip"),
    user_id: str = Depends(get_user_id),
):
    """
    Bulk-import positions from CSV.
    Required columns: ticker, shares
    Optional columns: avg_cost_native, currency, name
    Returns {imported, skipped, errors}
    """
    import csv, io

    content = await file.read()
    text = content.decode("utf-8-sig").strip()
    reader = csv.DictReader(io.StringIO(text))

    required = {"ticker", "shares"}
    if not reader.fieldnames or not required.issubset({f.strip().lower() for f in reader.fieldnames}):
        raise HTTPException(
            status_code=422,
            detail=f"CSV must contain columns: {', '.join(required)}. Got: {reader.fieldnames}",
        )

    db = get_admin_client()
    imported = 0
    skipped = 0
    errors: list[dict] = []

    for i, raw_row in enumerate(reader, start=2):
        row = {k.strip().lower(): v.strip() for k, v in raw_row.items() if k}
        ticker = (row.get("ticker") or "").upper().strip()
        shares_str = row.get("shares", "")

        if not ticker:
            errors.append({"row": i, "error": "Missing ticker"})
            continue
        try:
            shares = float(shares_str)
            if shares < 0:
                raise ValueError("negative shares")
        except (ValueError, TypeError):
            errors.append({"row": i, "ticker": ticker, "error": f"Invalid shares: {shares_str!r}"})
            continue

        avg_cost = None
        avg_str = row.get("avg_cost_native", "")
        if avg_str:
            try:
                avg_cost = float(avg_str)
            except ValueError:
                errors.append({"row": i, "ticker": ticker, "error": f"Invalid avg_cost_native: {avg_str!r}"})
                continue

        currency = row.get("currency", "").upper() or get_native_currency(ticker)
        name = row.get("name", "") or ticker

        record: dict = {
            "user_id": user_id,
            "ticker": ticker,
            "shares": shares,
            "currency": currency,
            "name": name,
        }
        if avg_cost is not None:
            record["avg_cost_native"] = avg_cost

        try:
            if mode == "skip":
                existing = (
                    db.table("positions")
                    .select("ticker")
                    .eq("user_id", user_id)
                    .eq("ticker", ticker)
                    .maybe_single()
                    .execute()
                )
                if existing.data:
                    skipped += 1
                    continue
                db.table("positions").insert(record).execute()
            else:
                db.table("positions").upsert(record, on_conflict="user_id,ticker").execute()
            imported += 1
        except Exception as exc:
            errors.append({"row": i, "ticker": ticker, "error": str(exc)})

    return {"imported": imported, "skipped": skipped, "errors": errors, "total_rows": imported + skipped + len(errors)}


@router.get("/export/positions.csv")
def export_positions_csv(user_id: str = Depends(get_user_id)):
    """Download current positions as a CSV file."""
    import csv, io

    db = get_admin_client()
    settings = _get_settings_for_user(user_id)
    base_currency = settings.get("base_currency", "USD")

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    tickers = [p["ticker"] for p in positions if float(p.get("shares", 0)) > 0]
    quotes = get_quotes(tickers) if tickers else {}
    exchange_currencies = [get_native_currency(t) for t in tickers] if tickers else []
    pos_currencies = [p.get("currency") or get_native_currency(p["ticker"]) for p in positions]
    currencies = list(set(exchange_currencies + pos_currencies))
    fx_rates = get_fx_rates(currencies, base=base_currency) if currencies else {}
    tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
    transactions = tx_res.data or []
    summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Ticker", "Name", "Shares", "Avg Cost", "Cost Currency",
                     f"Price ({base_currency})", f"Value ({base_currency})",
                     "Weight (%)", f"Unrealized P&L ({base_currency})", "Unrealized P&L (%)"])
    for row in sorted(summary.rows, key=lambda r: -r.value_base):
        writer.writerow([
            row.ticker,
            row.name or "",
            round(row.shares, 4),
            round(row.avg_cost_native or 0, 4),
            row.cost_currency or base_currency,
            round(row.price_base, 4),
            round(row.value_base, 2),
            round(row.weight, 2),
            round(row.unrealized_pnl or 0, 2),
            round(row.unrealized_pnl_pct or 0, 2),
        ])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=positions_{date.today()}.csv"},
    )


@router.get("/breakdown")
def get_portfolio_breakdown(user_id: str = Depends(get_user_id)):
    """Sector and region breakdown weighted by current portfolio value."""
    from concurrent.futures import ThreadPoolExecutor

    db = get_admin_client()
    settings = _get_settings_for_user(user_id)
    base_currency = settings.get("base_currency", "USD")

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    if not positions:
        return {"sectors": {}, "regions": {}}

    tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
    transactions = tx_res.data or []
    tickers = [p["ticker"] for p in positions]
    quotes = get_quotes(tickers)
    exchange_currencies = [get_native_currency(t) for t in tickers]
    pos_currencies = [p.get("currency") or get_native_currency(p["ticker"]) for p in positions]
    currencies = list(set(exchange_currencies + pos_currencies))
    fx_rates = get_fx_rates(currencies, base=base_currency)
    summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)

    total = summary.total_value_base
    if total == 0:
        return {"sectors": {}, "regions": {}}

    # Fetch all ETF data in parallel
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_fetch_etf_breakdown, [r.ticker for r in summary.rows]))

    etf_data = {ticker: (sw, info) for ticker, sw, info in results}

    sectors: dict[str, float] = {}
    regions: dict[str, float] = {}

    for row in summary.rows:
        w = row.value_base / total
        ticker = row.ticker
        sector_weights, info = etf_data.get(ticker, ({}, {}))

        if sector_weights:
            for label, pct in sector_weights.items():
                sectors[label] = sectors.get(label, 0) + pct * w * 100
        else:
            sectors["Other/Commodity"] = sectors.get("Other/Commodity", 0) + w * 100

        region_alloc = _infer_regions(ticker, info)
        for region, pct in region_alloc.items():
            regions[region] = regions.get(region, 0) + pct * w * 100

    sectors = {k: round(v, 2) for k, v in sorted(sectors.items(), key=lambda x: -x[1]) if v > 0.1}
    regions = {k: round(v, 2) for k, v in sorted(regions.items(), key=lambda x: -x[1]) if v > 0.1}

    return {"sectors": sectors, "regions": regions}


# ── Geographic Exposure ───────────────────────────────────────────────────────

@router.get("/geographic-exposure")
def geographic_exposure(user_id: str = Depends(get_user_id)):
    """
    Detailed geographic exposure: aggregated regions + per-ticker breakdown.
    Uses same inference logic as /breakdown.
    """
    from concurrent.futures import ThreadPoolExecutor

    db = get_admin_client()
    settings = _get_settings_for_user(user_id)
    base_currency = settings.get("base_currency", "USD")

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    if not positions:
        return {"regions": {}, "by_ticker": [], "base_currency": base_currency}

    tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
    transactions = tx_res.data or []
    tickers = [p["ticker"] for p in positions]
    quotes = get_quotes(tickers)
    exchange_currencies = [get_native_currency(t) for t in tickers]
    pos_currencies = [p.get("currency") or get_native_currency(p["ticker"]) for p in positions]
    fx_rates = get_fx_rates(list(set(exchange_currencies + pos_currencies)), base=base_currency)
    summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)

    total = summary.total_value_base
    if total == 0:
        return {"regions": {}, "by_ticker": [], "base_currency": base_currency}

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_fetch_etf_breakdown, [r.ticker for r in summary.rows]))
    etf_data = {ticker: (sw, info) for ticker, sw, info in results}

    regions: dict[str, float] = {}
    by_ticker = []

    for row in summary.rows:
        w = row.value_base / total
        ticker = row.ticker
        _, info = etf_data.get(ticker, ({}, {}))
        region_alloc = _infer_regions(ticker, info)

        by_ticker.append({
            "ticker": ticker,
            "name": row.name or ticker,
            "weight_pct": round(w * 100, 2),
            "regions": {r: round(p * 100, 1) for r, p in region_alloc.items()},
        })

        for region, pct in region_alloc.items():
            regions[region] = regions.get(region, 0) + pct * w * 100

    regions = {k: round(v, 2) for k, v in sorted(regions.items(), key=lambda x: -x[1]) if v > 0.1}

    return {
        "regions": regions,
        "by_ticker": sorted(by_ticker, key=lambda x: -x["weight_pct"]),
        "base_currency": base_currency,
    }


# ── ETF Look-Through / Overlap ────────────────────────────────────────────────

@router.get("/etf-overlap")
def etf_overlap(user_id: str = Depends(get_user_id)):
    """
    ETF look-through: fetches top holdings per ETF, weighted by portfolio weight,
    and identifies overlapping positions across multiple ETFs.
    """
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor

    db = get_admin_client()
    settings = _get_settings_for_user(user_id)
    base_currency = settings.get("base_currency", "USD")

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = pos_res.data or []
    if not positions:
        return {"top_holdings": [], "by_etf": [], "overlap_pct": 0.0, "n_etfs_with_data": 0}

    tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
    transactions = tx_res.data or []
    tickers = [p["ticker"] for p in positions]
    quotes = get_quotes(tickers)
    exchange_currencies = [get_native_currency(t) for t in tickers]
    pos_currencies = [p.get("currency") or get_native_currency(p["ticker"]) for p in positions]
    fx_rates = get_fx_rates(list(set(exchange_currencies + pos_currencies)), base=base_currency)
    summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)

    total = summary.total_value_base
    if total == 0:
        return {"top_holdings": [], "by_etf": [], "overlap_pct": 0.0, "n_etfs_with_data": 0}

    weights = {row.ticker: row.value_base / total for row in summary.rows}

    def _fetch_holdings(ticker: str) -> tuple[str, list[dict]]:
        cache_key = f"etf_holdings:{ticker}"
        cached = cache.get(cache_key)
        if cached is not None:
            return ticker, cached

        try:
            obj = yf.Ticker(yf_ticker(ticker))
            fd = obj.funds_data
            holdings_df = fd.top_holdings

            if holdings_df is None or (hasattr(holdings_df, "__len__") and len(holdings_df) == 0):
                cache.set(cache_key, [], ttl=3600)
                return ticker, []

            holdings = []
            if hasattr(holdings_df, "iterrows"):
                for sym, row_data in holdings_df.iterrows():
                    pct_raw = float(row_data.get("holdingPercent", 0) or 0)
                    # yfinance returns as decimal (0.07 = 7%) or already percent
                    pct = pct_raw * 100 if pct_raw < 1.5 else pct_raw
                    name = str(row_data.get("holdingName", sym) or sym)
                    if pct > 0:
                        holdings.append({"symbol": str(sym), "name": name, "pct": round(pct, 3)})

            holdings.sort(key=lambda x: -x["pct"])
            holdings = holdings[:20]
            cache.set(cache_key, holdings, ttl=3600)
            return ticker, holdings
        except Exception:
            cache.set(cache_key, [], ttl=3600)
            return ticker, []

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_fetch_holdings, [row.ticker for row in summary.rows]))
    holdings_by_etf = {ticker: holdings for ticker, holdings in results}

    # Aggregate weighted holdings across ETFs
    agg: dict[str, dict] = {}
    for row in summary.rows:
        etf_ticker = row.ticker
        etf_w = weights.get(etf_ticker, 0.0)
        for h in holdings_by_etf.get(etf_ticker, []):
            sym = h["symbol"]
            contribution = (h["pct"] / 100.0) * etf_w * 100.0
            if sym not in agg:
                agg[sym] = {
                    "symbol": sym,
                    "name": h["name"],
                    "total_weight_pct": 0.0,
                    "sources": [],
                    "n_etfs": 0,
                }
            agg[sym]["total_weight_pct"] += contribution
            agg[sym]["sources"].append({
                "etf": etf_ticker,
                "etf_weight_pct": round(etf_w * 100, 1),
                "holding_pct": h["pct"],
            })
            agg[sym]["n_etfs"] += 1

    for sym in agg:
        agg[sym]["total_weight_pct"] = round(agg[sym]["total_weight_pct"], 3)

    top_holdings = sorted(agg.values(), key=lambda x: -x["total_weight_pct"])[:30]

    by_etf = [
        {
            "ticker": row.ticker,
            "name": row.name or row.ticker,
            "portfolio_weight_pct": round(weights.get(row.ticker, 0) * 100, 2),
            "top_holdings": holdings_by_etf.get(row.ticker, [])[:10],
            "has_data": len(holdings_by_etf.get(row.ticker, [])) > 0,
        }
        for row in sorted(summary.rows, key=lambda r: -weights.get(r.ticker, 0))
    ]

    multi_etf = [h for h in top_holdings if h["n_etfs"] >= 2]
    overlap_pct = round(sum(h["total_weight_pct"] for h in multi_etf), 2)
    n_with_data = sum(1 for b in by_etf if b["has_data"])

    return {
        "top_holdings": top_holdings,
        "by_etf": by_etf,
        "overlap_pct": overlap_pct,
        "n_etfs_with_data": n_with_data,
        "base_currency": base_currency,
    }


# ── Performance Multi-Timeframe per Ticker ────────────────────────────────────

@router.get("/performance-timeframes")
def performance_timeframes(user_id: str = Depends(get_user_id)):
    """
    Per-ticker returns across 1W, 1M, 3M, 6M, YTD, 1Y timeframes.
    Uses historical price data from yfinance.
    """
    import yfinance as yf
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date as _date

    db = get_admin_client()
    pos_res = db.table("positions").select("ticker,shares").eq("user_id", user_id).execute()
    positions = [p for p in (pos_res.data or []) if float(p.get("shares", 0)) > 0]
    if not positions:
        return {"rows": [], "as_of": str(_date.today())}

    tickers = [p["ticker"] for p in positions]

    today = _date.today()
    ytd_start = _date(today.year, 1, 1)

    PERIODS = {
        "1W":  today - timedelta(days=7),
        "1M":  today - timedelta(days=30),
        "3M":  today - timedelta(days=91),
        "6M":  today - timedelta(days=182),
        "YTD": ytd_start,
        "1Y":  today - timedelta(days=365),
    }

    def _fetch_returns(ticker: str) -> dict:
        row: dict = {"ticker": ticker}
        try:
            yft = yf_ticker(ticker)
            df = yf.download(yft, period="1y", interval="1d", auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df = df["Close"]
                if isinstance(df, pd.DataFrame):
                    df = df.iloc[:, 0]
            elif "Close" in df.columns:
                df = df["Close"]
            else:
                return row

            df = df.dropna()
            if df.empty:
                return row

            current_price = float(df.iloc[-1])
            row["current_price"] = round(current_price, 4)

            for period_name, start_date in PERIODS.items():
                try:
                    subset = df[df.index >= pd.Timestamp(start_date)]
                    if len(subset) < 2:
                        row[period_name] = None
                        continue
                    start_price = float(subset.iloc[0])
                    ret = (current_price / start_price - 1) * 100
                    row[period_name] = round(ret, 2)
                except Exception:
                    row[period_name] = None
        except Exception:
            pass
        return row

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(_fetch_returns, tickers))

    return {"rows": rows, "as_of": str(today), "periods": list(PERIODS.keys())}


# ── ETF Inverse Lookup — which portfolio ETFs hold a given ticker ──────────────

@router.get("/etf-exposure/{target_ticker}")
def etf_exposure_for_ticker(
    target_ticker: str,
    user_id: str = Depends(get_user_id),
):
    """
    Given a ticker, find which ETFs in the user's portfolio hold it
    and the effective exposure (ETF weight × holding %).
    """
    import yfinance as yf

    target = target_ticker.upper().strip()
    db = get_admin_client()
    settings = _get_settings_for_user(user_id)
    base_currency = settings.get("base_currency", "USD")

    pos_res = db.table("positions").select("*").eq("user_id", user_id).execute()
    positions = [p for p in (pos_res.data or []) if float(p.get("shares", 0)) > 0]
    if not positions:
        return {"target": target, "exposures": [], "total_effective_pct": 0.0}

    tx_res = db.table("transactions").select("*").eq("user_id", user_id).execute()
    transactions = tx_res.data or []
    tickers = [p["ticker"] for p in positions]
    quotes = get_quotes(tickers)
    exchange_currencies = [get_native_currency(t) for t in tickers]
    pos_currencies = [p.get("currency") or get_native_currency(p["ticker"]) for p in positions]
    fx_rates = get_fx_rates(list(set(exchange_currencies + pos_currencies)), base=base_currency)
    summary = build_portfolio(positions, quotes, fx_rates, base_currency, transactions)

    total = summary.total_value_base
    if total == 0:
        return {"target": target, "exposures": [], "total_effective_pct": 0.0}

    exposures = []
    for row in summary.rows:
        etf_weight = row.value_base / total
        cache_key = f"etf_holdings:{row.ticker}"
        holdings = cache.get(cache_key)
        if holdings is None:
            try:
                obj = yf.Ticker(yf_ticker(row.ticker))
                fd = obj.funds_data
                hdf = fd.top_holdings
                holdings = []
                if hdf is not None and hasattr(hdf, "iterrows"):
                    for sym, hrow in hdf.iterrows():
                        pct_raw = float(hrow.get("holdingPercent", 0) or 0)
                        pct = pct_raw * 100 if pct_raw < 1.5 else pct_raw
                        if pct > 0:
                            holdings.append({"symbol": str(sym), "pct": round(pct, 3)})
                cache.set(cache_key, holdings, ttl=3600)
            except Exception:
                holdings = []
                cache.set(cache_key, holdings, ttl=3600)

        match = next((h for h in holdings if h["symbol"].upper() == target), None)
        if match:
            effective_pct = round(etf_weight * match["pct"], 3)
            exposures.append({
                "etf": row.ticker,
                "etf_name": row.name or row.ticker,
                "etf_portfolio_weight_pct": round(etf_weight * 100, 2),
                "holding_pct_in_etf": match["pct"],
                "effective_portfolio_pct": effective_pct,
            })

    total_effective = round(sum(e["effective_portfolio_pct"] for e in exposures), 3)
    exposures.sort(key=lambda x: -x["effective_portfolio_pct"])

    return {
        "target": target,
        "exposures": exposures,
        "total_effective_pct": total_effective,
        "base_currency": base_currency,
    }
