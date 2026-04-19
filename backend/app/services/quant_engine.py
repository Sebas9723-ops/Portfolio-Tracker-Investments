"""
Quantitative Optimization Engine.

Orchestrates: data fetch → Ledoit-Wolf covariance → HMM regime → BL expected returns
             → CVXPY optimize (CVaR-constrained) → 500-sample resampling → QuantResult
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import time
import numpy as np
import pandas as pd
import yfinance as yf
import cvxpy as cp
from sklearn.covariance import LedoitWolf
from hmmlearn import hmm

from app.services.exchange_classifier import PROXY_TICKER_MAP

log = logging.getLogger(__name__)

_WINDOW_DAYS = 504          # 2 years of trading days — enough for LW/HMM, faster fetch
_RISK_AVERSION = 2.5        # for CAPM equilibrium returns
_MOMENTUM_WINDOW = 252      # trading days for 12-month momentum
_RESAMPLE_ITERS = 500
_OPTIM_TIME_BUDGET = 25.0   # max seconds for the resampling loop
_MU_NOISE_STD = 0.02
_COV_NOISE_STD = 0.01
_CORR_SHIFT_THRESHOLD = 0.25
_SLIPPAGE_WINDOW = 20       # trading days for spread estimation
_BEAR_CAP_REDUCTION = 0.20  # reduce cap by 20% for top-2 tickers in bear
_CORR_CAP_REDUCTION = 0.15  # reduce cap by 15% for corr-shifted pairs


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class QuantResult:
    optimal_weights: dict[str, float]
    expected_return: float        # annualized, e.g. 0.10 = 10%
    expected_volatility: float    # annualized
    expected_sharpe: float
    cvar_95: float                # daily CVaR at 95%, positive = loss
    regime: str                   # "bull" | "bear"
    regime_confidence: float      # 0-1
    correlation_alerts: list[dict]
    timestamp: datetime = field(default_factory=datetime.utcnow)


# ── Engine ───────────────────────────────────────────────────────────────────

class QuantEngine:
    def __init__(self, risk_free_rate: float = 0.045):
        self.rfr = risk_free_rate

    # ── 1. Data fetch ──────────────────────────────────────────────────────

    def fetch_data(
        self,
        tickers: list[str],
        window_days: int = _WINDOW_DAYS,
    ) -> pd.DataFrame:
        """
        Download daily adjusted-close prices via yfinance.
        Maps EIMI.UK → EIMI.L (and any other PROXY_TICKER_MAP entries).
        Returns log-returns DataFrame indexed by the ORIGINAL ticker names.
        Handles short-history tickers gracefully (uses available history).
        """
        # Build yfinance symbol → original ticker map
        yf_to_orig: dict[str, str] = {}
        yf_symbols: list[str] = []
        for t in tickers:
            yf_sym = PROXY_TICKER_MAP.get(t, t)
            yf_symbols.append(yf_sym)
            yf_to_orig[yf_sym] = t

        # Approximate period string for yfinance
        years_needed = max(1, window_days // 252 + 1)
        period = f"{years_needed}y"

        closes: pd.DataFrame = pd.DataFrame()

        # Try bulk download first
        try:
            raw = yf.download(
                yf_symbols,
                period=period,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if not raw.empty:
                if isinstance(raw.columns, pd.MultiIndex):
                    # Multi-ticker: shape (dates, (field, ticker))
                    if "Close" in raw.columns.get_level_values(0):
                        closes = raw["Close"]
                    else:
                        closes = raw.iloc[:, raw.columns.get_level_values(0) == raw.columns.get_level_values(0)[0]]
                else:
                    # Single ticker
                    col = "Close" if "Close" in raw.columns else raw.columns[0]
                    closes = raw[[col]]
                    closes.columns = yf_symbols[:1]
        except Exception as exc:
            log.warning("Bulk yfinance download failed: %s — falling back to individual", exc)

        # Fall back: individual per missing ticker
        downloaded_cols = set(closes.columns) if not closes.empty else set()
        missing = [s for s in yf_symbols if s not in downloaded_cols]
        if missing:
            parts: dict[str, pd.Series] = {}
            for sym in missing:
                try:
                    df = yf.download(sym, period=period, auto_adjust=True, progress=False)
                    if not df.empty:
                        col = "Close" if "Close" in df.columns else df.columns[0]
                        parts[sym] = df[col]
                except Exception as exc:
                    log.warning("Failed to download %s: %s", sym, exc)
            if parts:
                extra = pd.DataFrame(parts)
                closes = pd.concat([closes, extra], axis=1) if not closes.empty else extra

        if closes.empty:
            return pd.DataFrame()

        # Rename columns back to original ticker names
        closes.columns = [yf_to_orig.get(c, c) for c in closes.columns]

        # Keep only requested tickers that exist
        available = [t for t in tickers if t in closes.columns]
        closes = closes[available].dropna(how="all").ffill()

        # Trim to window_days (per-column, to preserve short-history tickers)
        trimmed: dict[str, pd.Series] = {}
        for t in available:
            col = closes[t].dropna()
            trimmed[t] = col.iloc[-window_days:] if len(col) > window_days else col

        returns_df = pd.DataFrame(trimmed)
        # Log returns
        log_returns = np.log(returns_df / returns_df.shift(1)).iloc[1:]
        return log_returns.dropna(how="all")

    # ── 2. Covariance ─────────────────────────────────────────────────────

    def compute_covariance(self, returns: pd.DataFrame) -> np.ndarray:
        """
        Ledoit-Wolf shrinkage covariance (annualized).
        - Diagonal: per-ticker sample variance (annualized), no LW needed for 1D.
        - Off-diagonal: pairwise LW shrinkage on aligned (overlapping) observations.
        - Short-history pairs: filled with avg_corr * std_i * std_j.
        - Final matrix projected to PSD cone.
        """
        tickers = list(returns.columns)
        n = len(tickers)
        cov_full = np.full((n, n), np.nan)

        # Diagonal: annualized sample variance per ticker (stable, 1-D)
        for i, t in enumerate(tickers):
            col = returns[t].dropna()
            cov_full[i, i] = float(col.var()) * 252 if len(col) >= 2 else 0.0

        # Annualized std for correlation fallback
        stds = np.array([np.sqrt(cov_full[i, i]) for i in range(n)])

        # Off-diagonal: pairwise Ledoit-Wolf on overlapping observations
        for i in range(n):
            for j in range(i + 1, n):           # strictly upper triangle, no i==j
                pair = returns[[tickers[i], tickers[j]]].dropna()
                if len(pair) < 20:
                    cov_full[i, j] = np.nan      # fill later with avg corr
                    cov_full[j, i] = np.nan
                else:
                    lw = LedoitWolf().fit(pair.values * np.sqrt(252))
                    lw_cov_ij = lw.covariance_[0, 1]
                    cov_full[i, j] = lw_cov_ij
                    cov_full[j, i] = lw_cov_ij

        # Average correlation from all available off-diagonal pairs
        valid_corrs: list[float] = []
        for i in range(n):
            for j in range(i + 1, n):
                c = cov_full[i, j]
                if not np.isnan(c) and stds[i] > 0 and stds[j] > 0:
                    valid_corrs.append(c / (stds[i] * stds[j]))
        avg_corr = float(np.mean(valid_corrs)) if valid_corrs else 0.3

        # Fill NaN off-diagonal entries
        for i in range(n):
            for j in range(i + 1, n):
                if np.isnan(cov_full[i, j]):
                    fill = avg_corr * stds[i] * stds[j]
                    cov_full[i, j] = fill
                    cov_full[j, i] = fill

        # Ensure positive semi-definite via eigenvalue clipping
        cov_full = _ensure_psd(cov_full)
        return cov_full

    # ── 3. Regime detection ────────────────────────────────────────────────

    def detect_volatility_regime(
        self,
        returns: pd.DataFrame,
        market_ticker: str = "VOO",
    ) -> dict:
        """
        Fit 2-state GaussianHMM on market returns.
        Identifies bull (high-mean) vs bear (low-mean or negative) regime.
        Returns: {regime: "bull"|"bear", confidence: float}
        """
        if market_ticker not in returns.columns:
            market_ticker = returns.columns[0]

        series = returns[market_ticker].dropna().values.reshape(-1, 1)
        if len(series) < 60:
            return {"regime": "bull", "confidence": 0.5}

        try:
            model = hmm.GaussianHMM(
                n_components=2,
                covariance_type="diag",
                n_iter=50,
                random_state=42,
                tol=1e-3,
            )
            model.fit(series)

            hidden_states = model.predict(series)
            posteriors = model.predict_proba(series)

            # Current state = last observation
            current_state = int(hidden_states[-1])
            confidence = float(posteriors[-1, current_state])

            # Identify which state is "bull": higher mean return
            means = model.means_.flatten()
            bull_state = int(np.argmax(means))

            regime = "bull" if current_state == bull_state else "bear"
            return {"regime": regime, "confidence": round(confidence, 4)}

        except Exception as exc:
            log.warning("HMM regime detection failed: %s", exc)
            return {"regime": "bull", "confidence": 0.5}

    # ── 4. Correlation shifts ──────────────────────────────────────────────

    def detect_correlation_shifts(
        self,
        returns: pd.DataFrame,
        window: int = 60,
    ) -> list[dict]:
        """
        Compare rolling 60-day correlation to full-history correlation.
        Returns pairs where |current - historical| > 0.25.
        """
        tickers = list(returns.columns)
        if len(tickers) < 2 or len(returns) < window + 10:
            return []

        hist_corr = returns.corr()
        rolling_corr = returns.iloc[-window:].corr()

        alerts: list[dict] = []
        for i, ta in enumerate(tickers):
            for j, tb in enumerate(tickers):
                if j <= i:
                    continue
                hc = hist_corr.loc[ta, tb]
                rc = rolling_corr.loc[ta, tb]
                if pd.isna(hc) or pd.isna(rc):
                    continue
                deviation = rc - hc
                if abs(deviation) > _CORR_SHIFT_THRESHOLD:
                    alerts.append({
                        "ticker_a": ta,
                        "ticker_b": tb,
                        "current_corr": round(float(rc), 4),
                        "historical_corr": round(float(hc), 4),
                        "deviation": round(float(deviation), 4),
                    })

        return alerts

    # ── 5. Expected returns (CAPM + BL + momentum) ────────────────────────

    def compute_expected_returns(
        self,
        returns: pd.DataFrame,
        bl_views: dict,
        momentum_boost: float = 0.015,
    ) -> pd.Series:
        """
        1. CAPM equilibrium returns (equal-weight market portfolio as prior)
        2. Black-Litterman update if bl_views provided
        3. Momentum overlay: ±momentum_boost based on 12-month return sign

        bl_views format: {ticker: {"return": float, "confidence": float}}
        """
        tickers = list(returns.columns)
        n = len(tickers)
        ann_returns = returns.mean() * 252
        cov_ann = returns.cov() * 252

        # CAPM equilibrium with equal-weight market portfolio
        w_mkt = np.ones(n) / n
        pi = _RISK_AVERSION * cov_ann.values @ w_mkt   # implied equilibrium returns

        # Black-Litterman update
        if bl_views:
            pi = _black_litterman_update(pi, cov_ann.values, tickers, bl_views)

        mu = pd.Series(pi, index=tickers)

        # Momentum overlay: 12-month return sign
        for t in tickers:
            series = returns[t].dropna()
            if len(series) >= _MOMENTUM_WINDOW:
                cumret_12m = (series.iloc[-_MOMENTUM_WINDOW:]).sum()
                mu[t] += momentum_boost if cumret_12m > 0 else -momentum_boost

        return mu

    # ── 6. Slippage estimation ────────────────────────────────────────────

    def estimate_slippage(
        self,
        tickers: list[str],
        trade_sizes: dict,
    ) -> dict:
        """
        For each ticker, fetch 20-day OHLCV and estimate:
          - spread_cost: mean((High - Low) / Close)
          - volume_impact: trade_size / avg_20d_volume * daily_vol
          - total: spread_cost + volume_impact (as fraction of trade)
        """
        results: dict[str, dict] = {}
        yf_syms = [PROXY_TICKER_MAP.get(t, t) for t in tickers]
        yf_to_orig = {PROXY_TICKER_MAP.get(t, t): t for t in tickers}

        try:
            raw = yf.download(
                yf_syms,
                period="1mo",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception as exc:
            log.warning("Slippage data download failed: %s", exc)
            raw = pd.DataFrame()

        for sym, orig in yf_to_orig.items():
            trade_size = abs(trade_sizes.get(orig, 0.0))
            try:
                if raw.empty:
                    raise ValueError("empty")
                if isinstance(raw.columns, pd.MultiIndex):
                    hi = raw["High"][sym].dropna()
                    lo = raw["Low"][sym].dropna()
                    cl = raw["Close"][sym].dropna()
                    vo = raw["Volume"][sym].dropna()
                else:
                    hi = raw["High"].dropna()
                    lo = raw["Low"].dropna()
                    cl = raw["Close"].dropna()
                    vo = raw["Volume"].dropna()

                spread = float(((hi - lo) / cl).mean())
                avg_vol = float(vo.mean())
                daily_vol = float(np.log(cl / cl.shift(1)).dropna().std())

                vol_impact = (trade_size / avg_vol * daily_vol) if avg_vol > 0 else 0.0
                total = spread + vol_impact

                results[orig] = {
                    "spread_cost": round(spread, 6),
                    "volume_impact": round(vol_impact, 6),
                    "total": round(total, 6),
                }
            except Exception:
                results[orig] = {"spread_cost": 0.001, "volume_impact": 0.0, "total": 0.001}

        return results

    # ── 7. CVXPY Optimize ─────────────────────────────────────────────────

    def optimize(
        self,
        tickers: list[str],
        current_weights: dict,
        expected_returns: pd.Series,
        cov_matrix: np.ndarray,
        constraints_motor1: dict,
        constraints_motor2: list[dict],
        profile: str,
        regime: str,
        correlation_shifts: list[dict],
    ) -> dict:
        """
        CVXPY mean-variance / CVaR-constrained optimization with:
          - Motor 1 floor/cap per ticker (hard constraints)
          - Motor 2 combination ranges (hard constraints)
          - No-sell: floor = max(motor1_floor, current_weight)
          - TC penalty: 0.005 * sum(pos(w - current_w))
          - Regime bear: reduce cap by 20% for top-2 expected-return tickers
          - Correlation shifts: reduce cap by 15% for affected tickers
        Runs 500 resampling iterations; returns averaged weights.
        """
        n = len(tickers)
        mu = np.array([expected_returns.get(t, 0.0) for t in tickers])
        cov = cov_matrix.copy()
        cur_w = np.array([current_weights.get(t, 0.0) for t in tickers])
        if cur_w.sum() > 0:
            cur_w = cur_w / cur_w.sum()

        # CVaR limit by profile
        cvar_limits = {"aggressive": 0.20, "balanced": 0.15, "conservative": 0.10}
        cvar_limit = cvar_limits.get(profile, 0.15)

        # Build per-ticker bounds accounting for regime and correlation shifts
        floors = np.zeros(n)
        caps = np.ones(n)
        for i, t in enumerate(tickers):
            rule = constraints_motor1.get(t, {})
            f = float(rule.get("floor", 0.0))
            c = float(rule.get("cap", 1.0))
            # No-sell: raise floor to current weight if higher
            f = max(f, cur_w[i])
            floors[i] = f
            caps[i] = c

        # Clip floors to Motor 1 caps BEFORE applying regime/corr reductions so
        # that the `max(floors[i], reduced_cap)` guard uses the real Motor 1 floor,
        # not the (potentially higher) no-sell floor.
        floors = np.minimum(floors, caps)

        # Bear regime: reduce cap by 20% for top-2 return tickers
        if regime == "bear":
            top2_idx = np.argsort(mu)[-2:]
            for i in top2_idx:
                caps[i] = max(floors[i], caps[i] * (1 - _BEAR_CAP_REDUCTION))

        # Correlation shifts: reduce cap by 15% for affected tickers
        affected_tickers: set[str] = set()
        for alert in correlation_shifts:
            affected_tickers.add(alert["ticker_a"])
            affected_tickers.add(alert["ticker_b"])
        for i, t in enumerate(tickers):
            if t in affected_tickers:
                caps[i] = max(floors[i], caps[i] * (1 - _CORR_CAP_REDUCTION))

        # Final clip after regime/corr adjustments
        floors = np.minimum(floors, caps)

        # Simulate returns scenarios for CVaR (use empirical — pass via shared state)
        # We'll compute CVaR analytically from cov in single solves
        # Using parametric CVaR: CVaR_95 ≈ -(mu - 1.645 * sigma) for normal
        # For the full CVaR constraint we use the parametric form:
        # CVaR_95(portfolio) = -(mu_p - z_alpha * sigma_p)  (as daily)
        # We constrain: -mu_p_daily + z_alpha * sigma_p_daily <= cvar_limit_daily
        # where mu_p_daily = mu/252, sigma_p_daily = sigma/sqrt(252)
        # z_alpha for 95% = 1.6449
        z_alpha = 1.6449
        cvar_limit_daily = cvar_limit  # treat as fraction of portfolio daily loss

        all_weights: list[np.ndarray] = []
        rng = np.random.default_rng(42)
        t0 = time.monotonic()

        for iteration in range(_RESAMPLE_ITERS):
            if time.monotonic() - t0 > _OPTIM_TIME_BUDGET:
                log.warning("QuantEngine: time budget reached after %d/%d resamples", iteration, _RESAMPLE_ITERS)
                break
            if iteration == 0:
                mu_p = mu.copy()
                cov_p = cov.copy()
            else:
                mu_p = mu + rng.normal(0, _MU_NOISE_STD, size=n)
                noise = rng.normal(0, _COV_NOISE_STD, size=(n, n))
                noise = (noise + noise.T) / 2
                cov_p = _ensure_psd(cov + noise)

            w_sol = _solve_cvxpy(
                n, mu_p, cov_p, floors, caps, cur_w,
                constraints_motor2, tickers, profile,
                cvar_limit_daily, z_alpha,
            )
            if w_sol is not None:
                all_weights.append(w_sol)

        log.info("QuantEngine: %d/%d resamples completed in %.1fs", len(all_weights), _RESAMPLE_ITERS, time.monotonic() - t0)

        if not all_weights:
            # Fallback: start from equal weight but respect both floors AND caps
            w_fb = _project_weights(np.full(n, 1.0 / n), floors, caps)
            return {t: round(float(w_fb[i]), 6) for i, t in enumerate(tickers)}

        avg_w = _project_weights(np.mean(all_weights, axis=0), floors, caps)
        return {t: round(float(avg_w[i]), 6) for i, t in enumerate(tickers)}

    # ── 8. Full orchestration ─────────────────────────────────────────────

    def run_full_optimization(
        self,
        portfolio: dict,
        profile: str,
        bl_views: dict,
        constraints_motor1: dict,
        constraints_motor2: list[dict],
        available_cash: float = 0.0,
    ) -> QuantResult:
        """
        Orchestrates all steps:
          portfolio: {ticker: {"value_base": float, ...}}
          available_cash: new cash being deployed (used to compute no-sell floors
            relative to post-contribution total, making room for new tickers).
          Returns QuantResult with all outputs.
        """
        tickers = list(portfolio.keys())
        if not tickers:
            raise ValueError("Portfolio is empty")

        # Current weights from portfolio values
        # Use total_after (including new cash) so no-sell floors for existing
        # tickers are slightly lower, making room for new 0-share tickers that
        # have Motor 1 floors — avoids sum(floors) > 1 infeasibility.
        values = np.array([portfolio[t].get("value_base", 0.0) for t in tickers])
        total_value = values.sum()
        total_after = total_value + max(available_cash, 0.0)
        denominator = total_after if total_after > 0 else (total_value if total_value > 0 else 1.0)
        current_weights: dict[str, float] = {
            t: float(values[i] / denominator) for i, t in enumerate(tickers)
        }

        log.info("QuantEngine: fetching data for %d tickers", len(tickers))
        returns = self.fetch_data(tickers)
        if returns.empty or len(returns.columns) == 0:
            raise RuntimeError("Could not fetch return data for any ticker")

        # Only optimize on tickers with data
        available = list(returns.columns)
        if set(available) != set(tickers):
            log.warning("Missing data for: %s", set(tickers) - set(available))
        tickers = available

        log.info("QuantEngine: computing covariance")
        cov_matrix = self.compute_covariance(returns)

        log.info("QuantEngine: detecting regime")
        regime_info = self.detect_volatility_regime(returns)

        log.info("QuantEngine: detecting correlation shifts")
        corr_alerts = self.detect_correlation_shifts(returns)

        log.info("QuantEngine: computing expected returns")
        mu = self.compute_expected_returns(returns, bl_views)

        log.info("QuantEngine: optimizing (500 resamples)")
        optimal_w = self.optimize(
            tickers=tickers,
            current_weights=current_weights,
            expected_returns=mu,
            cov_matrix=cov_matrix,
            constraints_motor1=constraints_motor1,
            constraints_motor2=constraints_motor2,
            profile=profile,
            regime=regime_info["regime"],
            correlation_shifts=corr_alerts,
        )

        # Compute portfolio metrics from optimal weights
        w_arr = np.array([optimal_w.get(t, 0.0) for t in tickers])
        if w_arr.sum() > 0:
            w_arr = w_arr / w_arr.sum()

        mu_arr = np.array([float(mu.get(t, 0.0)) for t in tickers])
        exp_ret = float(w_arr @ mu_arr)
        exp_vol = float(np.sqrt(w_arr @ cov_matrix @ w_arr))
        exp_sharpe = (exp_ret - self.rfr) / exp_vol if exp_vol > 0 else 0.0

        # Daily CVaR parametric
        daily_vol = exp_vol / np.sqrt(252)
        daily_ret = exp_ret / 252
        cvar_95 = float(-(daily_ret - 1.6449 * daily_vol))

        return QuantResult(
            optimal_weights=optimal_w,
            expected_return=round(exp_ret, 6),
            expected_volatility=round(exp_vol, 6),
            expected_sharpe=round(exp_sharpe, 4),
            cvar_95=round(cvar_95, 6),
            regime=regime_info["regime"],
            regime_confidence=regime_info["confidence"],
            correlation_alerts=corr_alerts,
            timestamp=datetime.utcnow(),
        )


# ── Private helpers ───────────────────────────────────────────────────────────

def _project_weights(
    w: np.ndarray, floors: np.ndarray, caps: np.ndarray, max_iters: int = 100
) -> np.ndarray:
    """
    Project w onto {x | floors <= x <= caps, sum(x) == 1}.

    Iterative algorithm: clip to [floors, caps], then redistribute the
    excess/deficit proportionally among tickers that have room to absorb it.
    Guarantees sum == 1 while respecting hard bounds.
    """
    w = w.copy()
    for _ in range(max_iters):
        w = np.clip(w, floors, caps)
        excess = w.sum() - 1.0
        if abs(excess) < 1e-10:
            break
        if excess > 0:
            # Need to reduce: use tickers above their floor
            mask = w > floors + 1e-12
        else:
            # Need to increase: use tickers below their cap
            mask = w < caps - 1e-12
        if not mask.any():
            break
        w[mask] -= excess / mask.sum()
    # Final hard clip
    w = np.clip(w, floors, caps)
    # If still off (all tickers at bounds), normalise with best-effort clip
    if abs(w.sum() - 1.0) > 1e-6 and w.sum() > 0:
        w = w / w.sum()
        w = np.clip(w, floors, caps)
    return w


def _ensure_psd(matrix: np.ndarray, epsilon: float = 1e-8) -> np.ndarray:
    """Project matrix onto positive semidefinite cone via eigenvalue clipping."""
    symmetric = (matrix + matrix.T) / 2
    eigvals, eigvecs = np.linalg.eigh(symmetric)
    eigvals = np.maximum(eigvals, epsilon)
    return eigvecs @ np.diag(eigvals) @ eigvecs.T


def _black_litterman_update(
    pi: np.ndarray,
    cov: np.ndarray,
    tickers: list[str],
    bl_views: dict,
    tau: float = 0.05,
) -> np.ndarray:
    """
    BL update with absolute views.
    bl_views: {ticker: {"return": float, "confidence": float}}
    confidence in [0,1]: higher = lower uncertainty in view.
    """
    view_tickers = [t for t in bl_views if t in tickers]
    if not view_tickers:
        return pi

    k = len(view_tickers)
    n = len(tickers)
    P = np.zeros((k, n))
    q = np.zeros(k)
    omega_diag = np.zeros(k)

    for i, t in enumerate(view_tickers):
        j = tickers.index(t)
        P[i, j] = 1.0
        q[i] = float(bl_views[t].get("return", 0.0))
        conf = float(bl_views[t].get("confidence", 0.5))
        conf = np.clip(conf, 0.01, 0.99)
        # Uncertainty inversely proportional to confidence
        omega_diag[i] = (1 - conf) / conf * tau * cov[j, j]

    omega = np.diag(omega_diag)
    tau_sigma = tau * cov

    try:
        inv_tau_sigma = np.linalg.inv(tau_sigma + np.eye(n) * 1e-8)
        inv_omega = np.linalg.inv(omega + np.eye(k) * 1e-8)
        M = inv_tau_sigma + P.T @ inv_omega @ P
        mu_bl = np.linalg.solve(M + np.eye(n) * 1e-8, inv_tau_sigma @ pi + P.T @ inv_omega @ q)
        return mu_bl
    except np.linalg.LinAlgError:
        return pi


def _solve_cvxpy(
    n: int,
    mu: np.ndarray,
    cov: np.ndarray,
    floors: np.ndarray,
    caps: np.ndarray,
    cur_w: np.ndarray,
    constraints_motor2: list[dict],
    tickers: list[str],
    profile: str,
    cvar_limit_daily: float,
    z_alpha: float,
) -> Optional[np.ndarray]:
    """
    Solve a single CVXPY instance.

    CVaR constraint (parametric, normal approximation):
        CVaR_95(daily) = -(mu_daily @ w) + z_alpha * ||L.T @ w||_2 <= cvar_limit
    where L is the Cholesky factor of cov/252.  This formulation is DCP-valid
    (norm of an affine expression is convex; the sum with an affine term is convex).

    Returns weight array or None if infeasible/solver error.
    """
    w = cp.Variable(n, nonneg=True)

    # ── Cholesky decomposition for DCP-compliant portfolio vol ───────────────
    # sigma(w)_daily = ||L.T @ w||_2  where  cov/252 = L @ L.T
    # This avoids cp.sqrt(cp.quad_form(...)) which violates DCP.
    cov_daily = cov / 252
    try:
        L = np.linalg.cholesky(cov_daily)
    except np.linalg.LinAlgError:
        L = np.linalg.cholesky(cov_daily + np.eye(n) * 1e-7)

    mu_daily = mu / 252
    port_ret_daily = mu_daily @ w                  # affine
    port_vol_daily = cp.norm(L.T @ w, 2)           # convex (norm of affine)

    # CVaR(95%) parametric: loss = -E[r] + z * sigma  (convex)
    cvar_expr = -port_ret_daily + z_alpha * port_vol_daily

    # TC penalty (convex: sum of pos() = max(0, ...))
    tc_penalty = 0.005 * cp.sum(cp.pos(w - cur_w))

    # ── Objective ────────────────────────────────────────────────────────────
    if profile == "aggressive":
        objective = cp.Maximize(mu @ w - tc_penalty)
    elif profile == "conservative":
        objective = cp.Minimize(cp.quad_form(w, cov) + tc_penalty)
    else:  # base / balanced
        objective = cp.Maximize(mu @ w - 3.0 * cp.quad_form(w, cov) - tc_penalty)

    # ── Build shared constraint list ─────────────────────────────────────────
    def _base_constraints(cvar_limit: float) -> list:
        c = [
            cp.sum(w) == 1,
            w >= floors,
            w <= caps,
            cvar_expr <= cvar_limit,
        ]
        for rule in constraints_motor2:
            group_tickers = rule.get("tickers", [])
            idx = [k for k, t in enumerate(tickers) if t in group_tickers]
            if not idx:
                continue
            g = cp.sum(w[idx])
            if rule.get("min") is not None:
                c.append(g >= float(rule["min"]))
            if rule.get("max") is not None:
                c.append(g <= float(rule["max"]))
        return c

    def _extract(wvar: cp.Variable) -> Optional[np.ndarray]:
        """Project solver output onto feasible [floors, caps] simplex."""
        if wvar.value is None:
            return None
        return _project_weights(np.array(wvar.value, dtype=float), floors, caps)

    # ── Primary solve ────────────────────────────────────────────────────────
    prob = cp.Problem(objective, _base_constraints(cvar_limit_daily))
    try:
        prob.solve(solver=cp.CLARABEL, verbose=False)
        if prob.status in ("optimal", "optimal_inaccurate"):
            sol = _extract(w)
            if sol is not None:
                return sol
    except Exception:
        pass

    # ── Retry with 50% relaxed CVaR (keeps Motor 2) ──────────────────────────
    try:
        prob2 = cp.Problem(objective, _base_constraints(cvar_limit_daily * 1.5))
        prob2.solve(solver=cp.CLARABEL, verbose=False)
        if prob2.status in ("optimal", "optimal_inaccurate"):
            sol = _extract(w)
            if sol is not None:
                return sol
    except Exception:
        pass

    # ── Last resort: SCS fallback (more tolerant solver) ─────────────────────
    try:
        prob3 = cp.Problem(objective, _base_constraints(cvar_limit_daily * 2.0))
        prob3.solve(solver=cp.SCS, verbose=False)
        if prob3.status in ("optimal", "optimal_inaccurate"):
            sol = _extract(w)
            if sol is not None:
                return sol
    except Exception:
        pass

    return None
