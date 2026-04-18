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

    # Use today as exclusive end so the last bar is yesterday's confirmed close.
    # Today's live value is already shown in the portfolio header; including
    # today's incomplete intraday bar causes a misleading drop in the chart.
    end_str = str(date.today())

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
        # Only drop the last row when it corresponds to today's date (UTC).
        # Previously we always dropped it, which silently removed yesterday's
        # confirmed close when the server clock rolled past midnight UTC.
        if len(price_df) > 1:
            last_row_date = price_df.index[-1].date()
            if last_row_date >= date.today():
                price_df = price_df.iloc[:-1]
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
