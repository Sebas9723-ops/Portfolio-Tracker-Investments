from pydantic import BaseModel
from typing import Optional


class PerformanceMetrics(BaseModel):
    twr: Optional[float]
    mwr: Optional[float]
    annualized_return: Optional[float]
    annualized_vol: Optional[float]
    sharpe: Optional[float]
    sortino: Optional[float]
    max_drawdown: Optional[float]
    calmar: Optional[float]
    alpha: Optional[float]
    beta: Optional[float]
    information_ratio: Optional[float]
    benchmark_ticker: str
    period: str


class RollingPoint(BaseModel):
    date: str
    sharpe: Optional[float]
    sortino: Optional[float]
    volatility: Optional[float]
    drawdown: Optional[float]


class MonthlyReturn(BaseModel):
    year: int
    month: int
    portfolio_return: Optional[float]
    benchmark_return: Optional[float]


class DrawdownEpisode(BaseModel):
    start: str
    trough: str
    end: Optional[str]
    depth: float
    duration_days: int
    recovery_days: Optional[int]


class AnalyticsResponse(BaseModel):
    metrics: PerformanceMetrics
    rolling: list[RollingPoint]
    monthly_returns: list[MonthlyReturn]
    drawdown_episodes: list[DrawdownEpisode]
    portfolio_series: list[dict]
    benchmark_series: list[dict]


class FrontierPoint(BaseModel):
    ret: float
    vol: float
    sharpe: float
    weights: dict[str, float]


class OptimizationResult(BaseModel):
    frontier: list[FrontierPoint]
    max_sharpe: FrontierPoint
    min_vol: FrontierPoint
    max_return: FrontierPoint
    risk_parity: dict[str, float]
    current_weights: dict[str, float]
    current_metrics: dict


class RebalancingRow(BaseModel):
    ticker: str
    name: str
    current_weight: float
    target_weight: float
    drift: float
    value_base: float
    trade_value: float
    trade_direction: str  # BUY / SELL / HOLD
    estimated_tc: float


class VaRResult(BaseModel):
    confidence: float
    var_historical: float
    var_parametric: float
    cvar_historical: float
    cvar_parametric: float
    period_days: int


class StressTestRow(BaseModel):
    scenario: str
    portfolio_impact_pct: float
    portfolio_impact_base: float
    details: dict[str, float]


class CorrelationMatrix(BaseModel):
    tickers: list[str]
    matrix: list[list[float]]


class RiskMetrics(BaseModel):
    var: VaRResult
    stress_tests: list[StressTestRow]
    correlation: CorrelationMatrix
    risk_budget: dict[str, float]
    fx_exposure: dict[str, float]
    mandate_violations: list[str]
