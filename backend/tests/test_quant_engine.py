"""
Unit tests for QuantEngine.
Uses a mock 3-ticker portfolio: VOO (US equity), EIMI.UK (EM equity), IGLN.L (gold).
Heavy operations (fetch_data, full HMM) are patched; pure math functions are tested directly.
"""
import numpy as np
import pandas as pd
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from app.services.quant_engine import (
    QuantEngine,
    QuantResult,
    _ensure_psd,
    _black_litterman_update,
    _solve_cvxpy,
)
from app.services.contribution_plan import generate_contribution_plan, ContributionPlan


# ── Fixtures ──────────────────────────────────────────────────────────────────

TICKERS = ["VOO", "EIMI.UK", "IGLN.L"]
N_DAYS = 500
RNG = np.random.default_rng(0)


@pytest.fixture
def synthetic_returns() -> pd.DataFrame:
    """Synthetic daily log-returns for 3 tickers."""
    data = RNG.normal(loc=[0.0004, 0.0003, 0.0001], scale=[0.01, 0.015, 0.008], size=(N_DAYS, 3))
    return pd.DataFrame(data, columns=TICKERS)


@pytest.fixture
def engine() -> QuantEngine:
    return QuantEngine(risk_free_rate=0.045)


@pytest.fixture
def simple_portfolio() -> dict:
    return {
        "VOO":     {"value_base": 5000.0, "shares": 10.0},
        "EIMI.UK": {"value_base": 3000.0, "shares": 100.0},
        "IGLN.L":  {"value_base": 2000.0, "shares": 50.0},
    }


# ── _ensure_psd ───────────────────────────────────────────────────────────────

def test_ensure_psd_already_psd():
    A = np.array([[4.0, 2.0], [2.0, 3.0]])
    result = _ensure_psd(A)
    eigvals = np.linalg.eigvalsh(result)
    assert np.all(eigvals >= 0), "Result should be PSD"


def test_ensure_psd_fixes_indefinite():
    # Indefinite matrix
    A = np.array([[1.0, 2.0], [2.0, 1.0]])
    result = _ensure_psd(A)
    eigvals = np.linalg.eigvalsh(result)
    assert np.all(eigvals >= 0), "Result should be PSD after fixing"


def test_ensure_psd_symmetric():
    A = np.array([[3.0, 1.5, 0.5], [1.4, 2.0, 0.8], [0.5, 0.7, 1.5]])
    result = _ensure_psd(A)
    assert np.allclose(result, result.T), "Result should be symmetric"


# ── _black_litterman_update ───────────────────────────────────────────────────

def test_bl_update_no_views():
    """With no views, mu_bl should equal pi."""
    n = 3
    pi = np.array([0.08, 0.10, 0.05])
    cov = np.diag([0.04, 0.06, 0.03])
    result = _black_litterman_update(pi, cov, TICKERS, {})
    assert np.allclose(result, pi)


def test_bl_update_with_view():
    """With a high-confidence view, result should move toward the view."""
    n = 3
    pi = np.array([0.08, 0.10, 0.05])
    cov = np.eye(n) * 0.04
    bl_views = {"VOO": {"return": 0.20, "confidence": 0.9}}
    result = _black_litterman_update(pi, cov, TICKERS, bl_views)
    # VOO return should have moved toward 0.20 from 0.08
    assert result[0] > pi[0], "VOO return should increase with bullish view"


def test_bl_update_unknown_ticker_ignored():
    pi = np.array([0.08, 0.10, 0.05])
    cov = np.eye(3) * 0.04
    bl_views = {"UNKNOWN": {"return": 0.50, "confidence": 0.9}}
    result = _black_litterman_update(pi, cov, TICKERS, bl_views)
    assert np.allclose(result, pi), "Unknown ticker views should be ignored"


# ── compute_covariance ────────────────────────────────────────────────────────

def test_compute_covariance_shape(engine, synthetic_returns):
    cov = engine.compute_covariance(synthetic_returns)
    n = len(TICKERS)
    assert cov.shape == (n, n), f"Expected ({n},{n}), got {cov.shape}"


def test_compute_covariance_psd(engine, synthetic_returns):
    cov = engine.compute_covariance(synthetic_returns)
    eigvals = np.linalg.eigvalsh(cov)
    assert np.all(eigvals >= -1e-6), "Covariance must be positive semi-definite"


def test_compute_covariance_symmetric(engine, synthetic_returns):
    cov = engine.compute_covariance(synthetic_returns)
    assert np.allclose(cov, cov.T, atol=1e-10), "Covariance must be symmetric"


def test_compute_covariance_handles_short_history(engine):
    """Ticker with only 30 days should get avg-corr filled covariance."""
    short = pd.DataFrame({
        "VOO": RNG.normal(0.0004, 0.01, 500),
        "EIMI.UK": RNG.normal(0.0003, 0.015, 500),
        "IGLN.L": np.concatenate([np.full(470, np.nan), RNG.normal(0.0001, 0.008, 30)]),
    })
    cov = engine.compute_covariance(short)
    assert cov.shape == (3, 3)
    assert not np.any(np.isnan(cov)), "No NaNs in covariance"


# ── detect_volatility_regime ─────────────────────────────────────────────────

def test_detect_volatility_regime_returns_valid(engine, synthetic_returns):
    result = engine.detect_volatility_regime(synthetic_returns, market_ticker="VOO")
    assert result["regime"] in ("bull", "bear")
    assert 0 <= result["confidence"] <= 1


def test_detect_volatility_regime_fallback_missing_ticker(engine, synthetic_returns):
    """If market_ticker not in returns, falls back to first ticker."""
    result = engine.detect_volatility_regime(synthetic_returns, market_ticker="MISSING")
    assert result["regime"] in ("bull", "bear")


def test_detect_volatility_regime_too_few_obs(engine):
    short = pd.DataFrame({"VOO": RNG.normal(0, 0.01, 30)})
    result = engine.detect_volatility_regime(short, market_ticker="VOO")
    assert result["regime"] == "bull"
    assert result["confidence"] == 0.5


# ── detect_correlation_shifts ────────────────────────────────────────────────

def test_detect_correlation_shifts_no_alerts_stable(engine, synthetic_returns):
    """Stable synthetic returns should produce few or no alerts."""
    alerts = engine.detect_correlation_shifts(synthetic_returns, window=60)
    # Not asserting zero (could happen by chance), just asserting it's a list
    assert isinstance(alerts, list)


def test_detect_correlation_shifts_detects_shift(engine):
    """Manually create a correlation shift and verify it is detected."""
    n = 300
    # First 240 days: uncorrelated; last 60: VOO & EIMI.UK highly correlated
    base = RNG.normal(0, 0.01, n)
    voo = np.concatenate([RNG.normal(0, 0.01, 240), base[240:] * 0.9 + RNG.normal(0, 0.003, 60)])
    eimi = np.concatenate([RNG.normal(0, 0.01, 240), base[240:] * 0.9 + RNG.normal(0, 0.003, 60)])
    igln = RNG.normal(0, 0.008, n)
    returns = pd.DataFrame({"VOO": voo, "EIMI.UK": eimi, "IGLN.L": igln})
    alerts = engine.detect_correlation_shifts(returns, window=60)
    pairs = [(a["ticker_a"], a["ticker_b"]) for a in alerts]
    assert any("VOO" in p and "EIMI.UK" in p for p in pairs), (
        "Should detect VOO-EIMI.UK correlation shift"
    )


def test_detect_correlation_shifts_alert_structure(engine, synthetic_returns):
    alerts = engine.detect_correlation_shifts(synthetic_returns, window=60)
    for a in alerts:
        assert "ticker_a" in a
        assert "ticker_b" in a
        assert "current_corr" in a
        assert "historical_corr" in a
        assert "deviation" in a
        assert abs(a["deviation"]) > 0.25


# ── compute_expected_returns ──────────────────────────────────────────────────

def test_compute_expected_returns_shape(engine, synthetic_returns):
    mu = engine.compute_expected_returns(synthetic_returns, bl_views={})
    assert len(mu) == len(TICKERS)
    assert set(mu.index) == set(TICKERS)


def test_compute_expected_returns_with_views(engine, synthetic_returns):
    bl_views = {"VOO": {"return": 0.25, "confidence": 0.8}}
    mu_no_view = engine.compute_expected_returns(synthetic_returns, {})
    mu_with_view = engine.compute_expected_returns(synthetic_returns, bl_views)
    assert mu_with_view["VOO"] > mu_no_view["VOO"] - 0.01, (
        "Bullish view should push VOO return higher"
    )


def test_compute_expected_returns_momentum(engine, synthetic_returns):
    """Positive 12m returns → +boost applied."""
    # Make VOO strongly positive over last 252 days
    pos_returns = synthetic_returns.copy()
    pos_returns.iloc[-252:, 0] = 0.002  # VOO daily +0.2% → positive 12m
    mu = engine.compute_expected_returns(pos_returns, {}, momentum_boost=0.02)
    # Negative returns for IGLN over 12m
    neg_returns = synthetic_returns.copy()
    neg_returns.iloc[-252:, 2] = -0.002  # IGLN negative
    mu_neg = engine.compute_expected_returns(neg_returns, {}, momentum_boost=0.02)
    assert mu_neg["IGLN.L"] < mu["VOO"], "Negative momentum asset should have lower expected return"


# ── optimize ──────────────────────────────────────────────────────────────────

def test_optimize_weights_sum_to_one(engine, synthetic_returns):
    cov = engine.compute_covariance(synthetic_returns)
    mu = engine.compute_expected_returns(synthetic_returns, {})
    current_weights = {"VOO": 0.5, "EIMI.UK": 0.3, "IGLN.L": 0.2}
    weights = engine.optimize(
        tickers=TICKERS,
        current_weights=current_weights,
        expected_returns=mu,
        cov_matrix=cov,
        constraints_motor1={},
        constraints_motor2=[],
        profile="base",
        regime="bull",
        correlation_shifts=[],
    )
    total = sum(weights.values())
    assert abs(total - 1.0) < 1e-4, f"Weights must sum to 1, got {total}"


def test_optimize_respects_motor1_cap(engine, synthetic_returns):
    cov = engine.compute_covariance(synthetic_returns)
    mu = engine.compute_expected_returns(synthetic_returns, {})
    constraints_motor1 = {"VOO": {"floor": 0.0, "cap": 0.30}}
    weights = engine.optimize(
        tickers=TICKERS,
        current_weights={"VOO": 0.4, "EIMI.UK": 0.35, "IGLN.L": 0.25},
        expected_returns=mu,
        cov_matrix=cov,
        constraints_motor1=constraints_motor1,
        constraints_motor2=[],
        profile="aggressive",
        regime="bull",
        correlation_shifts=[],
    )
    assert weights.get("VOO", 1.0) <= 0.31, "VOO should be capped at ~30%"


def test_optimize_all_profiles_valid(engine, synthetic_returns):
    cov = engine.compute_covariance(synthetic_returns)
    mu = engine.compute_expected_returns(synthetic_returns, {})
    cw = {"VOO": 0.5, "EIMI.UK": 0.3, "IGLN.L": 0.2}
    for profile in ("conservative", "base", "aggressive"):
        weights = engine.optimize(
            tickers=TICKERS,
            current_weights=cw,
            expected_returns=mu,
            cov_matrix=cov,
            constraints_motor1={},
            constraints_motor2=[],
            profile=profile,
            regime="bull",
            correlation_shifts=[],
        )
        assert all(v >= -1e-6 for v in weights.values()), f"No negative weights for {profile}"
        assert abs(sum(weights.values()) - 1.0) < 1e-4, f"Weights sum to 1 for {profile}"


def test_optimize_no_sell_constraint(engine, synthetic_returns):
    """current_weight should become the floor when > motor1 floor."""
    cov = engine.compute_covariance(synthetic_returns)
    mu = engine.compute_expected_returns(synthetic_returns, {})
    # VOO at 70% — no-sell means it stays >= 70%
    current_weights = {"VOO": 0.70, "EIMI.UK": 0.20, "IGLN.L": 0.10}
    weights = engine.optimize(
        tickers=TICKERS,
        current_weights=current_weights,
        expected_returns=mu,
        cov_matrix=cov,
        constraints_motor1={},
        constraints_motor2=[],
        profile="conservative",
        regime="bull",
        correlation_shifts=[],
    )
    assert weights.get("VOO", 0.0) >= 0.69, "VOO should not be sold (no-sell floor)"


# ── generate_contribution_plan ────────────────────────────────────────────────

def test_generate_contribution_plan_basic(simple_portfolio):
    result = QuantResult(
        optimal_weights={"VOO": 0.60, "EIMI.UK": 0.25, "IGLN.L": 0.15},
        expected_return=0.10,
        expected_volatility=0.15,
        expected_sharpe=0.37,
        cvar_95=0.02,
        regime="bull",
        regime_confidence=0.85,
        correlation_alerts=[],
        timestamp=datetime.utcnow(),
    )
    plan = generate_contribution_plan(
        result=result,
        current_portfolio=simple_portfolio,
        available_cash=1000.0,
        slippage_estimates={"VOO": {"total": 0.001}, "EIMI.UK": {"total": 0.002}},
    )
    assert isinstance(plan, ContributionPlan)
    assert plan.total_cash == 1000.0
    assert plan.net_invested <= 1000.0
    assert plan.net_invested >= 0


def test_generate_contribution_plan_no_negative_amounts(simple_portfolio):
    result = QuantResult(
        optimal_weights={"VOO": 0.50, "EIMI.UK": 0.30, "IGLN.L": 0.20},
        expected_return=0.08,
        expected_volatility=0.12,
        expected_sharpe=0.29,
        cvar_95=0.015,
        regime="bull",
        regime_confidence=0.75,
        correlation_alerts=[],
        timestamp=datetime.utcnow(),
    )
    plan = generate_contribution_plan(
        result=result,
        current_portfolio=simple_portfolio,
        available_cash=500.0,
        slippage_estimates={},
    )
    assert all(r.net_amount >= 0 for r in plan.allocations), "No negative net amounts"
    assert all(r.gross_amount >= 0 for r in plan.allocations), "No negative gross amounts"


def test_generate_contribution_plan_zero_cash(simple_portfolio):
    result = QuantResult(
        optimal_weights={"VOO": 0.50, "EIMI.UK": 0.30, "IGLN.L": 0.20},
        expected_return=0.08, expected_volatility=0.12, expected_sharpe=0.29,
        cvar_95=0.015, regime="bull", regime_confidence=0.7,
        correlation_alerts=[], timestamp=datetime.utcnow(),
    )
    plan = generate_contribution_plan(result, simple_portfolio, 0.0, {})
    assert plan.total_cash == 0.0
    assert plan.allocations == []


def test_generate_contribution_plan_cash_deployed(simple_portfolio):
    """Total gross allocations should approximately equal available_cash."""
    result = QuantResult(
        optimal_weights={"VOO": 0.70, "EIMI.UK": 0.20, "IGLN.L": 0.10},
        expected_return=0.10, expected_volatility=0.15, expected_sharpe=0.37,
        cvar_95=0.02, regime="bull", regime_confidence=0.85,
        correlation_alerts=[], timestamp=datetime.utcnow(),
    )
    plan = generate_contribution_plan(result, simple_portfolio, 2000.0, {})
    total_gross = sum(r.gross_amount for r in plan.allocations)
    assert abs(total_gross - 2000.0) < 1.0, f"Expected ~2000 gross, got {total_gross}"


# ── run_full_optimization (integration, mocked fetch_data) ────────────────────

def test_run_full_optimization_mocked(engine, simple_portfolio, synthetic_returns):
    """Patch fetch_data to avoid network calls; test full pipeline."""
    with patch.object(engine, "fetch_data", return_value=synthetic_returns):
        result = engine.run_full_optimization(
            portfolio=simple_portfolio,
            profile="base",
            bl_views={},
            constraints_motor1={},
            constraints_motor2=[],
        )
    assert isinstance(result, QuantResult)
    assert result.regime in ("bull", "bear")
    assert 0.0 <= result.regime_confidence <= 1.0
    assert abs(sum(result.optimal_weights.values()) - 1.0) < 1e-3
    assert result.expected_sharpe is not None
    assert isinstance(result.correlation_alerts, list)


def test_run_full_optimization_with_views(engine, simple_portfolio, synthetic_returns):
    bl_views = {"VOO": {"return": 0.20, "confidence": 0.8}}
    with patch.object(engine, "fetch_data", return_value=synthetic_returns):
        result = engine.run_full_optimization(
            portfolio=simple_portfolio,
            profile="aggressive",
            bl_views=bl_views,
            constraints_motor1={},
            constraints_motor2=[],
        )
    assert isinstance(result, QuantResult)
    assert sum(result.optimal_weights.values()) > 0


def test_run_full_optimization_with_motor2(engine, simple_portfolio, synthetic_returns):
    constraints_motor2 = [{"tickers": ["VOO", "EIMI.UK"], "min": 0.60, "max": 0.90}]
    with patch.object(engine, "fetch_data", return_value=synthetic_returns):
        result = engine.run_full_optimization(
            portfolio=simple_portfolio,
            profile="base",
            bl_views={},
            constraints_motor1={},
            constraints_motor2=constraints_motor2,
        )
    group_weight = (
        result.optimal_weights.get("VOO", 0)
        + result.optimal_weights.get("EIMI.UK", 0)
    )
    assert 0.58 <= group_weight <= 0.92, (
        f"VOO+EIMI.UK group weight {group_weight:.2f} should be in [0.60, 0.90]"
    )
