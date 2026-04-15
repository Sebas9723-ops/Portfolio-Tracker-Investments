from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import finnhub

from app.config import get_settings
from app.routers import (
    auth, portfolio, market, transactions, analytics,
    optimization, rebalancing, risk, settings as settings_router,
    fundamentals, technicals, news,
)
from app.routers import profile as profile_router
from app.routers.settings import wl_router, alerts_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify API keys on startup
    cfg = get_settings()
    try:
        fh = finnhub.Client(api_key=cfg.FINNHUB_API_KEY)
        fh.quote("VOO")
        print("✓ Finnhub connection OK")
    except Exception as e:
        print(f"⚠ Finnhub check failed: {e}")
    yield


app = FastAPI(
    title="Portfolio Tracker API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

cfg = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(portfolio.router)
app.include_router(market.router)
app.include_router(transactions.router)
app.include_router(analytics.router)
app.include_router(optimization.router)
app.include_router(rebalancing.router)
app.include_router(risk.router)
app.include_router(settings_router.router)
app.include_router(wl_router)
app.include_router(alerts_router)
app.include_router(fundamentals.router)
app.include_router(technicals.router)
app.include_router(news.router)
app.include_router(profile_router.router)


@app.get("/health")
def health():
    return {"status": "ok"}
