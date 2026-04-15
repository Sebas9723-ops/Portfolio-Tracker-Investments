import finnhub
from fastapi import APIRouter, Query
from functools import lru_cache
from app.config import get_settings
from app.services import cache
from datetime import datetime, timedelta

router = APIRouter(prefix="/api/news", tags=["news"])


@lru_cache
def _fh():
    return finnhub.Client(api_key=get_settings().FINNHUB_API_KEY)


@router.get("")
def news(tickers: str = Query(..., description="Comma-separated tickers")):
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    key = f"news:{','.join(sorted(ticker_list))}"
    cached = cache.get(key)
    if cached:
        return cached

    to_dt = datetime.now().strftime("%Y-%m-%d")
    from_dt = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    articles = []
    seen_ids: set = set()
    for ticker in ticker_list[:5]:  # limit to 5 tickers to stay within rate limits
        try:
            items = _fh().company_news(ticker, _from=from_dt, to=to_dt)
            for item in (items or [])[:10]:
                nid = item.get("id") or item.get("url")
                if nid not in seen_ids:
                    seen_ids.add(nid)
                    articles.append({
                        "id": nid,
                        "ticker": ticker,
                        "headline": item.get("headline"),
                        "summary": item.get("summary"),
                        "source": item.get("source"),
                        "url": item.get("url"),
                        "datetime": item.get("datetime"),
                        "image": item.get("image"),
                        "sentiment": item.get("sentiment"),
                    })
        except Exception:
            pass

    articles.sort(key=lambda a: a.get("datetime") or 0, reverse=True)
    result = articles[:50]
    cache.set(key, result, ttl=300)
    return result
