import yfinance as yf
from fastapi import APIRouter, HTTPException
from app.services import cache
from app.services.exchange_classifier import yf_ticker

router = APIRouter(prefix="/api/fundamentals", tags=["fundamentals"])

_FIELDS = [
    "longName", "sector", "industry", "marketCap", "trailingPE", "forwardPE",
    "priceToBook", "dividendYield", "trailingAnnualDividendRate", "beta",
    "revenueGrowth", "earningsGrowth", "returnOnEquity", "returnOnAssets",
    "debtToEquity", "currentRatio", "grossMargins", "operatingMargins",
    "profitMargins", "totalRevenue", "netIncomeToCommon", "freeCashflow",
    "totalDebt", "totalCash", "bookValue", "enterpriseValue", "pegRatio",
    "shortDescription", "longBusinessSummary",
    # Analyst
    "recommendationKey", "recommendationMean", "targetMeanPrice",
    "targetHighPrice", "targetLowPrice", "targetMedianPrice",
    "numberOfAnalystOpinions",
    # Short interest
    "shortPercentOfFloat", "shortRatio", "sharesShort", "sharesShortPriorMonth",
    # Price range
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyDayAverage", "twoHundredDayAverage",
    # Volume
    "volume", "averageVolume", "averageVolume10days",
]


@router.get("/{ticker}")
def get_fundamentals(ticker: str):
    key = f"fundamentals:{ticker}"
    cached = cache.get(key)
    if cached:
        return cached

    try:
        yft = yf_ticker(ticker)
        t = yf.Ticker(yft)
        try:
            info = t.get_info()
        except Exception:
            info = t.info or {}

        result = {f: info.get(f) for f in _FIELDS}
        result["ticker"] = ticker

        # Relative volume
        vol = result.get("volume") or 0
        avg_vol = result.get("averageVolume") or 1
        result["relative_volume"] = round(vol / avg_vol, 2) if avg_vol > 0 else None

        # Financial statements
        try:
            inc = t.get_income_stmt()
            result["income_stmt"] = inc.to_dict() if inc is not None and not inc.empty else {}
        except Exception:
            result["income_stmt"] = {}
        try:
            bal = t.get_balance_sheet()
            result["balance_sheet"] = bal.to_dict() if bal is not None and not bal.empty else {}
        except Exception:
            result["balance_sheet"] = {}
        try:
            cf = t.get_cashflow()
            result["cashflow"] = cf.to_dict() if cf is not None and not cf.empty else {}
        except Exception:
            result["cashflow"] = {}

        cache.set(key, result, ttl=cache.TTL_FUNDAMENTALS)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch fundamentals: {e}")


@router.get("/{ticker}/insiders")
def get_insider_transactions(ticker: str):
    """Recent insider buy/sell transactions."""
    key = f"insiders:{ticker}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        yft = yf_ticker(ticker)
        t = yf.Ticker(yft)
        df = t.insider_transactions
        if df is None or (hasattr(df, "__len__") and len(df) == 0):
            result = {"transactions": [], "ticker": ticker}
            cache.set(key, result, ttl=cache.TTL_FUNDAMENTALS)
            return result

        rows = []
        for _, row in df.iterrows():
            date_val = row.get("Date") or row.get("startDate") or ""
            try:
                date_str = str(date_val)[:10]
            except Exception:
                date_str = ""
            rows.append({
                "date": date_str,
                "insider": str(row.get("Insider") or row.get("insiderName") or ""),
                "title": str(row.get("Title") or row.get("insiderTitle") or ""),
                "transaction": str(row.get("Transaction") or row.get("transactionText") or ""),
                "shares": int(row.get("Shares") or row.get("shares") or 0),
                "value": float(row.get("Value") or row.get("value") or 0),
                "is_buy": "buy" in str(row.get("Transaction") or row.get("transactionText") or "").lower(),
            })

        rows.sort(key=lambda x: x["date"], reverse=True)
        result = {"transactions": rows[:25], "ticker": ticker}
        cache.set(key, result, ttl=cache.TTL_FUNDAMENTALS)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch insiders: {e}")


@router.get("/{ticker}/analyst-ratings")
def get_analyst_ratings(ticker: str):
    """Analyst upgrades/downgrades and recommendation history."""
    key = f"analyst:{ticker}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        yft = yf_ticker(ticker)
        t = yf.Ticker(yft)

        upgrades = []
        try:
            df = t.upgrades_downgrades
            if df is not None and not df.empty:
                df = df.sort_index(ascending=False)
                for ts, row in df.head(20).iterrows():
                    try:
                        date_str = str(ts)[:10]
                    except Exception:
                        date_str = ""
                    action = str(row.get("Action") or "")
                    upgrades.append({
                        "date": date_str,
                        "firm": str(row.get("Firm") or ""),
                        "to_grade": str(row.get("ToGrade") or ""),
                        "from_grade": str(row.get("FromGrade") or ""),
                        "action": action,
                        "is_upgrade": action.lower() in ("up", "upgrade", "init", "initiated"),
                    })
        except Exception:
            pass

        rec_history = []
        try:
            rec_df = t.recommendations
            if rec_df is not None and not rec_df.empty:
                rec_df = rec_df.sort_index(ascending=False)
                for ts, row in rec_df.head(12).iterrows():
                    try:
                        date_str = str(ts)[:10]
                    except Exception:
                        date_str = ""
                    rec_history.append({
                        "date": date_str,
                        "period": str(row.get("period") or ""),
                        "strong_buy": int(row.get("strongBuy") or 0),
                        "buy": int(row.get("buy") or 0),
                        "hold": int(row.get("hold") or 0),
                        "sell": int(row.get("sell") or 0),
                        "strong_sell": int(row.get("strongSell") or 0),
                    })
        except Exception:
            pass

        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass

        result = {
            "ticker": ticker,
            "recommendation_key": info.get("recommendationKey"),
            "recommendation_mean": info.get("recommendationMean"),
            "target_mean": info.get("targetMeanPrice"),
            "target_high": info.get("targetHighPrice"),
            "target_low": info.get("targetLowPrice"),
            "n_analysts": info.get("numberOfAnalystOpinions"),
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "upgrades": upgrades,
            "rec_history": rec_history,
        }
        cache.set(key, result, ttl=cache.TTL_FUNDAMENTALS)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch analyst ratings: {e}")
