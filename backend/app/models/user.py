from pydantic import BaseModel
from typing import Optional


class UserSettings(BaseModel):
    base_currency: str = "USD"
    rebalancing_threshold: float = 0.05
    max_single_asset: float = 0.30
    min_bonds: float = 0.10
    min_gold: float = 0.05
    preferred_benchmark: str = "VOO"
    risk_free_rate: float = 0.045
    rolling_window: int = 63
    tc_model: str = "broker"
    investor_profile: str = "balanced"
    target_return: float = 0.08
    ticker_weight_rules: dict = {}  # {profile: {ticker: {"floor": float, "cap": float}}}
    combination_ranges: dict = {}   # {profile: [{"id": str, "tickers": [str], "min": float, "max": float}]}
    optimization_periods: dict = {}  # {profile: period_string} e.g. {"base": "2y", "aggressive": "5y"}
    cost_basis_usd: Optional[float] = None  # actual USD deployed at purchase FX rates
    time_horizon: str = "long"  # short / medium / long — persisted per user
    bl_views: dict = {}  # {profile: [{ticker, ret}]} — Black-Litterman views per profile
    bl_risk_aversion: float = 2.5   # Black-Litterman risk aversion parameter (λ)
    bl_tau: float = 0.05            # Black-Litterman uncertainty scaling (τ)
    macro_overlay: dict = {}  # {ticker: float} — multiplier applied to mu, e.g. {"QQQ": 1.15, "GLD": 0.85}
    drift_alerts_enabled: bool = False  # Feature C: enable email drift alerts
    drift_alert_email: str = ""         # Feature C: email to receive alerts
    drift_alert_threshold: float = 0.08 # Feature C: drift threshold for alerts (above rebalancing_threshold)


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str


class WatchlistItemCreate(BaseModel):
    ticker: str
    name: Optional[str] = None
    category: str = "custom"


class AlertCreate(BaseModel):
    ticker: str
    alert_type: str
    threshold: float
