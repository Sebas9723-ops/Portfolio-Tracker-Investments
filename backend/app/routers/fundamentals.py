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
