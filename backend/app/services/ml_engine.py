"""
ML Engine — feeds into Quant Engine contribution planner.

Modules (all optional, degrade gracefully):
  1. GJR-GARCH(1,1,1) + Student-t  → dynamic covariance  (arch)
  2. DCC(1,1)                       → time-varying correlations
  3. Fama-French 5                  → expected returns     (pandas_datareader + statsmodels)
  4. HMM 4-state                    → regime               (hmmlearn)
  5. XGBoost                        → ML-BL views          (xgboost)

All modules converge in run_ml_pipeline().
TTL cache (4h) for everything except user BL views.
"""
from __future__ import annotations

import logging
import threading
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, NamedTuple, Optional

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf
from sklearn.preprocessing import StandardScaler

log = logging.getLogger(__name__)

# ── Optional heavy deps ───────────────────────────────────────────────────────

try:
    from arch import arch_model
    _ARCH_OK = True
except ImportError:
    _ARCH_OK = False
    log.warning("ML: arch not installed — GARCH disabled, using LW variance")

try:
    import pandas_datareader as pdr
    _PDR_OK = True
except ImportError:
    _PDR_OK = False
    log.warning("ML: pandas_datareader not installed — FF5 disabled, using CAPM")

try:
    import statsmodels.api as sm
    _SM_OK = True
except ImportError:
    _SM_OK = False

try:
    from xgboost import XGBRegressor
    _XGB_OK = True
except ImportError:
    _XGB_OK = False
    log.warning("ML: xgboost not installed — ML-BL disabled, using user views only")

try:
    from hmmlearn import hmm as hmmlib
    _HMM_OK = True
except ImportError:
    _HMM_OK = False
    log.warning("ML: hmmlearn not installed — HMM disabled, using default regime")

try:
    from cachetools import TTLCache
    _CACHETOOLS_OK = True
except ImportError:
    _CACHETOOLS_OK = False
    log.warning("ML: cachetools not installed — pipeline cache disabled")

_REGIME_LABELS = ["bull_strong", "bull_weak", "bear_mild", "crisis"]

# XGBoost view weight by horizon: short trusts 1-month XGB more, long trusts FF5 more
_XGB_WEIGHT_BY_HORIZON = {"short": 0.80, "medium": 0.50, "long": 0.25}

# Profile-aware XGB blend weights: aggressive trusts shorter-horizon momentum signals more
_XGB_WEIGHT_BY_PROFILE_HORIZON: dict[tuple[str, str], float] = {
    ("aggressive",   "short"):  0.85,
    ("aggressive",   "medium"): 0.65,
    ("aggressive",   "long"):   0.45,
    ("base",         "short"):  0.80,
    ("base",         "medium"): 0.50,
    ("base",         "long"):   0.25,
    ("conservative", "short"):  0.50,
    ("conservative", "medium"): 0.30,
    ("conservative", "long"):   0.15,
}

# ── TTL Cache ─────────────────────────────────────────────────────────────────

_CACHE_TTL = 14400  # 4 hours
_pipeline_cache = TTLCache(maxsize=8, ttl=_CACHE_TTL) if _CACHETOOLS_OK else {}
_cache_lock = threading.Lock()


class _CacheEntry(NamedTuple):
    garch_cov: np.ndarray
    garch_vols: dict
    garch_std_resids: dict
    garch_available: bool
    ff5_returns: pd.Series
    ff5_loadings: dict
    ff5_available: bool
    regime: str
    regime_confidence: float
    regime_probs: dict
    regime_labels: pd.Series
    regime_available: bool
    xgb_ml_views: dict          # ML-only views (no user BL views merged yet)
    xgb_available: bool
    diagnostics_base: dict      # diag without user-merge info


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class MLResult:
    # GARCH + DCC
    garch_cov: np.ndarray
    garch_vols: dict[str, float]
    garch_available: bool

    # Fama-French 5
    ff5_returns: pd.Series
    ff5_loadings: dict[str, dict[str, float]]
    ff5_available: bool

    # HMM regime
    regime: str                          # "bull_strong"|"bull_weak"|"bear_mild"|"crisis"
    regime_confidence: float
    regime_probs: dict[str, float]
    regime_labels: pd.Series = field(default_factory=lambda: pd.Series(dtype=str))
    regime_available: bool = False

    # XGBoost ML-BL (merged with user views)
    bl_views: dict = field(default_factory=dict)
    xgb_available: bool = False

    diagnostics: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


# ── Engine ────────────────────────────────────────────────────────────────────

class MLEngine:
    """Full ML pipeline for portfolio optimization."""

    def __init__(self, risk_free_rate: float = 0.045):
        self.rfr = risk_free_rate

    # ── 1. GJR-GARCH(1,1,1) + Student-t Covariance ───────────────────────

    def fit_garch_covariance(
        self, returns: pd.DataFrame
    ) -> tuple[dict[str, float], dict[str, pd.Series], np.ndarray, bool]:
        """
        Per-ticker GJR-GARCH(1,1,1) + Student-t conditional variance.

        Algorithm:
          - Fit arch_model(r_i * 100, vol='GARCH', p=1, o=1, q=1, dist='studentst')
          - Extract conditional_volatility for DCC residuals
          - Build fallback_cov = outer(garch_vols) * LW_correlation for callers
            that don't use DCC
        Returns (garch_vols, garch_std_resids, fallback_cov, success).
        Falls back to sample variance per ticker on failure.
        """
        tickers = list(returns.columns)
        n = len(tickers)
        garch_vols: dict[str, float] = {}
        garch_std_resids: dict[str, pd.Series] = {}

        for t in tickers:
            series = returns[t].dropna()
            if len(series) < 100 or not _ARCH_OK:
                garch_vols[t] = float(series.std() * np.sqrt(252))
                garch_std_resids[t] = pd.Series(dtype=float)
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    mdl = arch_model(
                        series * 100,
                        vol="GARCH", p=1, o=1, q=1,
                        dist="studentst", rescale=False,
                    )
                    res = mdl.fit(disp="off", show_warning=False,
                                  options={"maxiter": 200, "ftol": 1e-6})

                    # 1-step-ahead conditional variance for annualized vol
                    fc = res.forecast(horizon=1, reindex=False)
                    daily_var = float(fc.variance.iloc[-1, 0]) / 1e4  # /100²
                    garch_vols[t] = np.sqrt(daily_var * 252)

                    # Standardized residuals for DCC
                    cond_vol_daily = res.conditional_volatility / 100.0  # undo *100 scaling
                    std_resid = series.reindex(cond_vol_daily.index) / (cond_vol_daily + 1e-10)
                    garch_std_resids[t] = std_resid.dropna()

            except Exception as exc:
                log.warning("GJR-GARCH failed for %s: %s", t, exc)
                garch_vols[t] = float(series.std() * np.sqrt(252))
                garch_std_resids[t] = pd.Series(dtype=float)

        # LW correlation matrix (structure only, diagonal replaced by GARCH)
        aligned = returns.ffill().dropna()
        if len(aligned) >= 20:
            lw = LedoitWolf().fit(aligned.values)
            lw_std = np.sqrt(np.diag(lw.covariance_))
            lw_std[lw_std < 1e-10] = 1e-10
            corr = lw.covariance_ / np.outer(lw_std, lw_std)
        else:
            corr = np.eye(n)

        vol_arr = np.array([garch_vols[t] for t in tickers])
        fallback_cov = np.outer(vol_arr, vol_arr) * corr
        fallback_cov = _psd(fallback_cov)

        success = _ARCH_OK and all(
            len(returns[t].dropna()) >= 100 for t in tickers
        )
        return garch_vols, garch_std_resids, fallback_cov, success

    # ── 2. DCC(1,1) Dynamic Conditional Correlations ─────────────────────

    def fit_dcc_covariance(
        self,
        tickers: list[str],
        garch_vols: dict[str, float],
        garch_std_resids: dict[str, pd.Series],
        a: float = 0.05,
        b: float = 0.90,
    ) -> np.ndarray:
        """
        DCC(1,1) dynamic conditional correlations (Engle 2002).

        Uses GARCH standardized residuals to estimate time-varying correlation.
        Fixed params a=0.05, b=0.90 (standard calibration).
        Returns PSD covariance matrix combining GARCH vols + DCC correlations.
        Falls back to GARCH+LW covariance if residuals are insufficient.
        """
        try:
            # Align residuals
            resid_df = pd.DataFrame(
                {t: garch_std_resids[t] for t in tickers if not garch_std_resids.get(t, pd.Series()).empty}
            ).dropna()

            if resid_df.shape[0] < 60 or resid_df.shape[1] < len(tickers):
                raise ValueError("Insufficient aligned residuals for DCC")

            # Use only the tickers with residuals (may be a subset)
            dcc_tickers = list(resid_df.columns)
            E = resid_df.values  # (T, N)
            T, N = E.shape

            # Unconditional correlation matrix
            Q_bar = _psd((E.T @ E) / T)

            # DCC recursion
            Q = Q_bar.copy()
            for i in range(1, T):
                e_prev = E[i - 1]
                Q = (1 - a - b) * Q_bar + a * np.outer(e_prev, e_prev) + b * Q

            # Normalize Q → R (correlation)
            diag_q = np.diag(Q)
            diag_q[diag_q < 1e-10] = 1e-10
            inv_sqrt = np.diag(1.0 / np.sqrt(diag_q))
            R = inv_sqrt @ Q @ inv_sqrt
            np.fill_diagonal(R, 1.0)

            # Build full correlation matrix (use LW for tickers missing residuals)
            n_full = len(tickers)
            R_full = np.eye(n_full)
            for i, ta in enumerate(tickers):
                for j, tb in enumerate(tickers):
                    if ta in dcc_tickers and tb in dcc_tickers:
                        di = dcc_tickers.index(ta)
                        dj = dcc_tickers.index(tb)
                        R_full[i, j] = R[di, dj]

            vol_arr = np.array([garch_vols[t] for t in tickers])
            cov = _psd(np.outer(vol_arr, vol_arr) * R_full)
            return cov

        except Exception as exc:
            log.warning("DCC failed, falling back to GARCH+LW: %s", exc)
            # Return a basic diagonal covariance as ultimate fallback
            vol_arr = np.array([garch_vols.get(t, 0.15) for t in tickers])
            return _psd(np.diag(vol_arr ** 2))

    # ── 3. Fama-French 5-Factor Expected Returns ──────────────────────────

    def fit_fama_french(
        self,
        returns: pd.DataFrame,
    ) -> tuple[pd.Series, dict[str, dict[str, float]], bool]:
        """
        OLS regression of each ticker's excess return on FF5 daily factors.
        E[r_i] = RF + alpha_i + sum(beta_ij * premium_j)
        Premium_j = trailing mean of factor j (annualized).
        Falls back to CAPM for tickers with < 60 aligned observations.
        """
        tickers = list(returns.columns)
        FACTORS = ["Mkt-RF", "SMB", "HML", "RMW", "CMA"]

        if not _PDR_OK:
            return self._capm_returns(returns), {}, False

        try:
            start = returns.index[0].strftime("%Y-%m-%d")
            end = returns.index[-1].strftime("%Y-%m-%d")
            ff5_raw = pdr.get_data_famafrench(
                "F-F_Research_Data_5_Factors_2x3_daily",
                start=start, end=end,
            )[0]
            ff5 = ff5_raw / 100.0
            ff5.index = pd.to_datetime(ff5.index)
        except Exception as exc:
            log.warning("FF5 fetch failed: %s — using CAPM", exc)
            return self._capm_returns(returns), {}, False

        # Factor premiums: blend full-history (structural) with recent 252d (cyclical).
        # 60/40 weighting gives better out-of-sample premium estimates.
        recent_days = min(252, len(ff5))
        factor_premia = (
            0.60 * ff5.tail(recent_days)[FACTORS].mean() * 252
            + 0.40 * ff5[FACTORS].mean() * 252
        )
        rf_annual = float(ff5["RF"].mean()) * 252

        expected: dict[str, float] = {}
        loadings: dict[str, dict[str, float]] = {}

        for t in tickers:
            series = returns[t].dropna()
            series.index = pd.to_datetime(series.index)
            joined = series.to_frame("ret").join(ff5, how="inner").dropna()

            if len(joined) < 60:
                expected[t] = float(series.mean() * 252)
                continue

            y = joined["ret"] - joined["RF"]
            X = joined[FACTORS]

            try:
                if _SM_OK:
                    ols = sm.OLS(y, sm.add_constant(X)).fit()
                    alpha = float(ols.params["const"]) * 252
                    betas = {f: float(ols.params[f]) for f in FACTORS}
                else:
                    from sklearn.linear_model import Ridge
                    mdl = Ridge(alpha=0.01).fit(X.values, y.values)
                    alpha = float((y - X.values @ mdl.coef_).mean()) * 252
                    betas = {FACTORS[i]: float(mdl.coef_[i]) for i in range(5)}

                # Blume (1975) beta adjustment: shrink market beta toward 1.0.
                # β_adj = 1/3 + 2/3 * β_OLS  — reduces over-fitting on short histories.
                betas["Mkt-RF"] = 1/3 + 2/3 * betas["Mkt-RF"]

                exp_ret = (
                    rf_annual + alpha
                    + sum(betas[f] * float(factor_premia[f]) for f in FACTORS)
                )
                expected[t] = exp_ret
                loadings[t] = {"alpha": round(alpha, 6), **{f: round(betas[f], 4) for f in FACTORS}}

            except Exception as exc:
                log.warning("FF5 OLS failed for %s: %s", t, exc)
                expected[t] = float(series.mean() * 252)

        return pd.Series(expected), loadings, True

    def _capm_returns(self, returns: pd.DataFrame) -> pd.Series:
        n = len(returns.columns)
        cov_ann = returns.cov() * 252
        w_mkt = np.ones(n) / n
        pi = 2.5 * cov_ann.values @ w_mkt
        return pd.Series(pi, index=returns.columns)

    # ── 4. HMM 4-State Regime ─────────────────────────────────────────────

    def fit_hmm_regime(
        self,
        returns: pd.DataFrame,
        market_ticker: Optional[str] = None,
    ) -> tuple[str, float, dict[str, float], pd.Series, bool]:
        """
        GaussianHMM(n_components=4) on [daily_ret, rolling_20d_vol, rolling_60d_mom].
        States labeled by sorting component mean_return descending:
          bull_strong → bull_weak → bear_mild → crisis
        Returns (regime_label, confidence, probs_dict, label_series, success).
        label_series is the full historical label sequence indexed by returns.index.
        """
        _default_labels = pd.Series(dtype=str)
        _default = (
            "bull_weak", 0.5,
            {"bull_strong": 0.15, "bull_weak": 0.55, "bear_mild": 0.20, "crisis": 0.10},
            _default_labels,
            False,
        )

        if not _HMM_OK:
            return _default

        if market_ticker is None or market_ticker not in returns.columns:
            market_ticker = returns.columns[0]

        mkt = returns[market_ticker].dropna()
        if len(mkt) < 120:
            return _default

        vol20 = mkt.rolling(20).std() * np.sqrt(252)
        mom60 = mkt.rolling(60).sum()
        features = pd.DataFrame({
            "ret": mkt,
            "vol": vol20,
            "mom": mom60,
        }).dropna()

        if len(features) < 60:
            return _default

        try:
            scaler = StandardScaler()
            X = scaler.fit_transform(features.values)

            # Multiple restarts — GaussianHMM is sensitive to initialisation.
            # Pick the run with highest log-likelihood to avoid local optima.
            best_model = None
            best_score = -np.inf
            for seed in [42, 7, 123, 0, 314]:
                try:
                    m = hmmlib.GaussianHMM(
                        n_components=4,
                        covariance_type="full",
                        n_iter=100,
                        random_state=seed,
                        tol=1e-4,
                    )
                    m.fit(X)
                    s = float(m.score(X))
                    if s > best_score:
                        best_score = s
                        best_model = m
                except Exception:
                    continue
            if best_model is None:
                return _default
            model = best_model

            hidden_states = model.predict(X)
            posteriors = model.predict_proba(X)

            # Map component indices → regime labels by mean return (descending)
            comp_mean_ret = [
                float(model.means_[k, 0] * scaler.scale_[0] + scaler.mean_[0])
                for k in range(4)
            ]
            sorted_comps = sorted(range(4), key=lambda k: comp_mean_ret[k], reverse=True)
            comp_to_label = {sorted_comps[i]: _REGIME_LABELS[i] for i in range(4)}

            # Full historical label sequence
            label_series = pd.Series(
                [comp_to_label[s] for s in hidden_states],
                index=features.index,
                dtype=str,
            )

            # Smooth over last 20 observations (robust to single-day spikes)
            recent_post = posteriors[-20:].mean(axis=0)  # (4,)
            current_comp = int(np.argmax(recent_post))
            regime = comp_to_label[current_comp]
            confidence = float(recent_post[current_comp])

            probs = {comp_to_label[k]: round(float(recent_post[k]), 4) for k in range(4)}

            return regime, round(confidence, 4), probs, label_series, True

        except Exception as exc:
            log.warning("HMM regime failed: %s", exc)
            return _default

    # ── 5. XGBoost ML-BL Views ────────────────────────────────────────────

    def generate_xgb_bl_views(
        self,
        returns: pd.DataFrame,
        ff5_returns: pd.Series,
        garch_vols: dict[str, float],
        user_bl_views: dict,
        regime_labels: pd.Series,
        current_regime: str,
        time_horizon: str = "long",
        profile: str = "base",
    ) -> tuple[dict[str, dict], bool]:
        """
        Per-ticker XGBoost predicts 1-month forward return.
        Regime one-hot + cross-sectional momentum rank features.
        Prediction → BL view with confidence from walk-forward MAE.
        User views always override ML views (merged last).
        Returns (ml_only_views, success) — caller merges user views.
        """
        if not _XGB_OK:
            return {}, False

        tickers = list(returns.columns)
        ml_views: dict[str, dict] = {}

        # ── Pre-compute cross-sectional momentum ranks ────────────────────────
        # These rank each ticker vs the universe — the strongest quant signal
        _mom_1m: dict[str, pd.Series] = {}
        _mom_3m: dict[str, pd.Series] = {}
        _sharpe_21: dict[str, pd.Series] = {}
        for _t in tickers:
            _s = returns[_t].dropna()
            if len(_s) >= 21:
                _vol20 = _s.rolling(20).std() * np.sqrt(252)
                _mom_1m[_t]   = _s.rolling(21).sum()
                _sharpe_21[_t] = (_s.rolling(21).mean() * 252) / (_vol20 + 1e-8)
            if len(_s) >= 63:
                _mom_3m[_t] = _s.rolling(63).sum()

        rank_mom_1m:   pd.DataFrame | None = None
        rank_mom_3m:   pd.DataFrame | None = None
        rank_sharpe_21: pd.DataFrame | None = None
        if len(_mom_1m) > 1:
            rank_mom_1m    = pd.DataFrame(_mom_1m).rank(axis=1, pct=True)
            rank_sharpe_21 = pd.DataFrame(_sharpe_21).rank(axis=1, pct=True)
        if len(_mom_3m) > 1:
            rank_mom_3m = pd.DataFrame(_mom_3m).rank(axis=1, pct=True)

        for t in tickers:
            if t in user_bl_views:
                continue  # user view takes precedence, skip ML for this ticker

            series = returns[t].dropna()
            if len(series) < 252:
                continue

            # Per-ticker cross-sectional rank series
            cs_ranks: dict[str, pd.Series] = {}
            if rank_mom_1m is not None and t in rank_mom_1m.columns:
                cs_ranks["cs_rank_mom_1m"] = rank_mom_1m[t]
            if rank_mom_3m is not None and t in rank_mom_3m.columns:
                cs_ranks["cs_rank_mom_3m"] = rank_mom_3m[t]
            if rank_sharpe_21 is not None and t in rank_sharpe_21.columns:
                cs_ranks["cs_rank_sharpe_21"] = rank_sharpe_21[t]

            try:
                feats = self._ticker_features(series, garch_vols.get(t, 0.15), regime_labels, current_regime, cs_ranks=cs_ranks)
                if feats is None or len(feats) < 80:
                    continue

                # ── Risk-adjusted target: forward Sharpe proxy ─────────────
                # Teaches XGB to predict alpha per unit of risk (more stationary
                # and regime-stable than raw 21d forward return).
                fwd_ret = series.shift(-21).rolling(21).sum() * (252 / 21)
                fwd_vol = series.rolling(21).std().shift(-21) * np.sqrt(252)
                fwd_sharpe = fwd_ret / (fwd_vol.clip(lower=0.05) + 1e-8)

                idx = feats.index.intersection(fwd_sharpe.dropna().index)
                if len(idx) < 80:
                    continue

                X = feats.loc[idx].values
                y = fwd_sharpe.loc[idx].values  # dimensionless Sharpe target

                # Walk-forward split: reserve last 63 days for out-of-sample validation
                split = max(60, len(X) - 63)
                X_tr, y_tr = X[:split], y[:split]
                X_val, y_val = X[split:], y[split:]
                X_cur = feats.iloc[[-1]].values

                # Inner early-stopping split (last 20% of training)
                es_split = max(30, int(len(X_tr) * 0.80))
                X_es_tr,  y_es_tr  = X_tr[:es_split],  y_tr[:es_split]
                X_es_val, y_es_val = X_tr[es_split:],  y_tr[es_split:]

                xgb = XGBRegressor(
                    n_estimators=300,
                    max_depth=3,
                    learning_rate=0.04,
                    subsample=0.8,
                    colsample_bytree=0.7,
                    min_child_weight=5,
                    reg_alpha=0.1,          # L1 — sparsity
                    reg_lambda=1.0,         # L2 — shrinkage
                    random_state=42,
                    verbosity=0,
                    early_stopping_rounds=25,
                )
                xgb.fit(
                    X_es_tr, y_es_tr,
                    eval_set=[(X_es_val, y_es_val)],
                    verbose=False,
                )
                predicted_sharpe = float(xgb.predict(X_cur)[0])

                # ── Scale back to annualized return view ──────────────────
                # predicted_return = predicted_Sharpe × current_GARCH_vol
                cur_vol = float(garch_vols.get(t, series.rolling(20).std().iloc[-1] * np.sqrt(252)))
                predicted = predicted_sharpe * max(cur_vol, 0.05)

                # ── Confidence from OOS Sharpe-MAE ────────────────────────
                # Aggressive allows higher confidence ceiling so XGB views have
                # stronger weight in the BL update (was 0.72, aggressive gets 0.88).
                _conf_ceil = 0.88 if profile == "aggressive" else 0.72
                if len(X_val) >= 5:
                    y_val_pred = xgb.predict(X_val)
                    mae = float(np.mean(np.abs(y_val_pred - y_val)))
                    # MAE in Sharpe units: 0.5 is good, 2.0 is noisy
                    confidence = float(np.clip(1.0 / (1.0 + mae * 1.5), 0.10, _conf_ceil))
                else:
                    confidence = 0.30

                # ── Blend with FF5 (horizon-dependent) ───────────────────
                xgb_weight = _XGB_WEIGHT_BY_PROFILE_HORIZON.get(
                    (profile, time_horizon),
                    _XGB_WEIGHT_BY_HORIZON.get(time_horizon, 0.50),
                )
                ff5_ret = float(ff5_returns.get(t, 0.0))
                blended = xgb_weight * predicted + (1.0 - xgb_weight) * ff5_ret

                if abs(blended - ff5_ret) > 0.005:
                    ml_views[t] = {
                        "return": round(blended, 6),
                        "confidence": round(confidence, 4),
                        "source": "xgboost",
                        "xgb_weight": xgb_weight,
                    }

            except Exception as exc:
                log.warning("XGB-BL failed for %s: %s", t, exc)

        return ml_views, True

    def _ticker_features(
        self,
        series: pd.Series,
        garch_vol: float,
        regime_labels: pd.Series,
        current_regime: str,
        cs_ranks: dict[str, pd.Series] | None = None,
    ) -> Optional[pd.DataFrame]:
        """
        Feature matrix for XGBoost BL prediction.

        Momentum: 1m/3m/6m/12m log-return sums
        Volatility: GARCH vol, 20d/60d/120d rolling vol, vol-ratio, vol-accel
        Risk-adjusted momentum: rolling Sharpe (21d, 63d)
        Mean-reversion: z-score vs 60d mean
        Oscillator: RSI(14)
        Tail: rolling skewness (60d), 63d max-drawdown proxy
        Regime: rolling 20-bar frequency per state (smoother than one-hot)
        Cross-sectional: momentum rank vs universe (cs_rank_mom_1m/3m, cs_rank_sharpe_21)
        """
        if len(series) < 130:
            return None
        f = pd.DataFrame(index=series.index)

        # ── Momentum ──────────────────────────────────────────────────────
        f["mom_1m"]  = series.rolling(21).sum()
        f["mom_3m"]  = series.rolling(63).sum()
        f["mom_6m"]  = series.rolling(126).sum()
        f["mom_12m"] = series.rolling(252).sum()

        # ── Volatility ────────────────────────────────────────────────────
        vol20  = series.rolling(20).std()  * np.sqrt(252)
        vol60  = series.rolling(60).std()  * np.sqrt(252)
        vol120 = series.rolling(120).std() * np.sqrt(252)
        f["vol_20"]    = vol20
        f["vol_60"]    = vol60
        f["vol_ratio"] = vol20 / (vol60  + 1e-8)   # short/mid vol term structure
        f["vol_accel"] = vol20 / (vol120 + 1e-8)   # short/long — picks up vol spikes
        f["garch_vol"] = garch_vol                  # GARCH 1-step forecast (cross-sectional signal)

        # ── Risk-adjusted momentum (rolling Sharpe) ───────────────────────
        f["sharpe_21"] = (series.rolling(21).mean() * 252) / (vol20 + 1e-8)
        f["sharpe_63"] = (series.rolling(63).mean() * 252) / (vol60 + 1e-8)

        # ── Mean-reversion z-score ─────────────────────────────────────────
        f["zscore"] = (
            (series.rolling(21).mean() - series.rolling(60).mean())
            / (series.rolling(60).std() + 1e-8)
        )

        # ── RSI(14) momentum oscillator ───────────────────────────────────
        delta = series.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        f["rsi_14"] = 100 - 100 / (1 + gain / (loss + 1e-8))

        # ── Tail risk signals ─────────────────────────────────────────────
        f["skew_60"] = series.rolling(60).skew()                  # negative = crash risk
        f["dd_63"]   = series.rolling(63).apply(                  # cummax drawdown proxy
            lambda x: float(np.nanmin(np.cumprod(1 + x) / np.maximum.accumulate(np.cumprod(1 + x))) - 1),
            raw=True,
        )

        # ── Regime features (rolling frequency = smoother than one-hot) ──
        if not regime_labels.empty:
            reg_aligned = regime_labels.reindex(series.index, method="ffill")
            for lbl in _REGIME_LABELS:
                f[f"reg_freq_{lbl}"] = (reg_aligned == lbl).rolling(20).mean()
        else:
            for lbl in _REGIME_LABELS:
                f[f"reg_freq_{lbl}"] = 1.0 if lbl == current_regime else 0.0

        # ── Cross-sectional momentum rank (Jegadeesh & Titman 1993) ──────
        # Rank among portfolio peers — strong predictor at 3-12 month horizon
        if cs_ranks:
            for name, rank_series in cs_ranks.items():
                aligned = rank_series.reindex(f.index, method="ffill")
                f[name] = aligned

        return f.dropna()

    # ── 6. Full ML Pipeline ───────────────────────────────────────────────

    def run_ml_pipeline(
        self,
        returns: pd.DataFrame,
        user_bl_views: dict,
        market_ticker: str = "VOO",
        time_horizon: str = "long",
        profile: str = "base",
    ) -> MLResult:
        """
        Orchestrate all ML modules. Each module is isolated — failures
        populate *_available=False and fall back to safe defaults.

        TTL cache (4h) stores everything except user BL views.
        Profile is included in cache key because XGB blend weights differ per profile.
        On cache hit: re-merges user views with cached XGB ML views.
        On cache miss: runs full pipeline, stores to cache.
        """
        tickers = list(returns.columns)
        cache_key = (tuple(sorted(tickers)), round(self.rfr, 3), time_horizon, profile)

        # ── Cache lookup ──────────────────────────────────────────────────
        with _cache_lock:
            cached: Optional[_CacheEntry] = _pipeline_cache.get(cache_key)

        if cached is not None:
            log.info("ML: cache hit for %d tickers — merging user BL views", len(tickers))
            merged_views = {**cached.xgb_ml_views, **user_bl_views}
            diag = dict(cached.diagnostics_base)
            diag["cache_hit"] = True
            return MLResult(
                garch_cov=cached.garch_cov,
                garch_vols=cached.garch_vols,
                garch_available=cached.garch_available,
                ff5_returns=cached.ff5_returns,
                ff5_loadings=cached.ff5_loadings,
                ff5_available=cached.ff5_available,
                regime=cached.regime,
                regime_confidence=cached.regime_confidence,
                regime_probs=cached.regime_probs,
                regime_labels=cached.regime_labels,
                regime_available=cached.regime_available,
                bl_views=merged_views,
                xgb_available=cached.xgb_available,
                diagnostics=diag,
            )

        # ── Cache miss: run full pipeline ─────────────────────────────────
        diag: dict[str, Any] = {"cache_hit": False}

        # 1. GJR-GARCH covariance + standardized residuals
        t0 = time.monotonic()
        log.info("ML: GJR-GARCH(1,1,1)+Student-t covariance (%d tickers)", len(tickers))
        garch_vols, garch_std_resids, fallback_cov, garch_ok = self.fit_garch_covariance(returns)
        diag["garch_ms"] = round((time.monotonic() - t0) * 1000)
        diag["garch_available"] = garch_ok
        diag["garch_vols"] = {t: round(v, 4) for t, v in garch_vols.items()}

        # 2. DCC(1,1) covariance + EWMA blend
        t1 = time.monotonic()
        log.info("ML: DCC(1,1) + EWMA(0.94) covariance blend")
        try:
            dcc_cov = self.fit_dcc_covariance(tickers, garch_vols, garch_std_resids)
            dcc_ok = True
        except Exception as exc:
            log.warning("DCC covariance failed: %s — using GARCH+LW fallback", exc)
            dcc_cov = fallback_cov
            dcc_ok = False

        # Blend DCC (or fallback) with EWMA for better responsiveness to recent vol.
        # 70% DCC (structural dynamics) + 30% EWMA (recent regime sensitivity).
        try:
            ewma = _ewma_cov(returns)
            garch_cov = _psd(0.70 * (dcc_cov if dcc_ok else fallback_cov) + 0.30 * ewma)
        except Exception:
            garch_cov = dcc_cov if dcc_ok else fallback_cov

        diag["dcc_ms"] = round((time.monotonic() - t1) * 1000)
        diag["dcc_available"] = dcc_ok

        # 3. FF5 expected returns
        t0 = time.monotonic()
        log.info("ML: Fama-French 5-factor returns")
        ff5_returns, ff5_loadings, ff5_ok = self.fit_fama_french(returns)
        if not ff5_ok or ff5_returns.empty:
            ff5_returns = self._capm_returns(returns)
        diag["ff5_ms"] = round((time.monotonic() - t0) * 1000)
        diag["ff5_available"] = ff5_ok
        diag["ff5_loadings"] = ff5_loadings

        # 4. HMM 4-state regime
        t0 = time.monotonic()
        log.info("ML: HMM 4-state regime")
        regime, regime_conf, regime_probs, regime_labels, regime_ok = self.fit_hmm_regime(
            returns, market_ticker
        )
        diag["regime_ms"] = round((time.monotonic() - t0) * 1000)
        diag["regime_available"] = regime_ok

        # 5. XGBoost ML-BL views (regime-aware, ML views only — no user merge yet)
        # Pass empty user_bl_views so XGB generates views for ALL tickers;
        # user views are merged AFTER caching so they always override fresh.
        t0 = time.monotonic()
        log.info("ML: XGBoost BL views (regime-aware)")
        xgb_ml_views, xgb_ok = self.generate_xgb_bl_views(
            returns, ff5_returns, garch_vols, {},
            regime_labels, regime,
            time_horizon=time_horizon,
            profile=profile,
        )
        diag["time_horizon"] = time_horizon
        diag["xgb_ms"] = round((time.monotonic() - t0) * 1000)
        diag["xgb_available"] = xgb_ok
        diag["xgb_views_generated"] = len(xgb_ml_views)

        log.info(
            "ML pipeline done — GARCH=%s DCC=%s FF5=%s regime=%s(%s) XGB=%s views=%d",
            garch_ok, dcc_ok, ff5_ok, regime, round(regime_conf, 2), xgb_ok,
            diag["xgb_views_generated"],
        )

        # ── Store to cache (without user BL views) ────────────────────────
        entry = _CacheEntry(
            garch_cov=garch_cov,
            garch_vols=garch_vols,
            garch_std_resids=garch_std_resids,
            garch_available=garch_ok,
            ff5_returns=ff5_returns,
            ff5_loadings=ff5_loadings,
            ff5_available=ff5_ok,
            regime=regime,
            regime_confidence=regime_conf,
            regime_probs=regime_probs,
            regime_labels=regime_labels,
            regime_available=regime_ok,
            xgb_ml_views=xgb_ml_views,
            xgb_available=xgb_ok,
            diagnostics_base=diag,
        )
        with _cache_lock:
            _pipeline_cache[cache_key] = entry

        # Merge user BL views last (user always overrides ML)
        merged_views = {**xgb_ml_views, **user_bl_views}

        return MLResult(
            garch_cov=garch_cov,
            garch_vols=garch_vols,
            garch_available=garch_ok,
            ff5_returns=ff5_returns,
            ff5_loadings=ff5_loadings,
            ff5_available=ff5_ok,
            regime=regime,
            regime_confidence=regime_conf,
            regime_probs=regime_probs,
            regime_labels=regime_labels,
            regime_available=regime_ok,
            bl_views=merged_views,
            xgb_available=xgb_ok,
            diagnostics=diag,
        )


# ── Private helpers ───────────────────────────────────────────────────────────

def _psd(matrix: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    """Project matrix onto positive semi-definite cone."""
    sym = (matrix + matrix.T) / 2
    eigvals, eigvecs = np.linalg.eigh(sym)
    eigvals = np.maximum(eigvals, eps)
    return eigvecs @ np.diag(eigvals) @ eigvecs.T


def _ewma_cov(returns: pd.DataFrame, lambda_: float = 0.94) -> np.ndarray:
    """
    RiskMetrics (1994) EWMA covariance estimator (annualised).

    More responsive to recent volatility than Ledoit-Wolf; useful as a
    complement to DCC in the covariance blend.
    """
    r = returns.dropna(how="all").fillna(0).values
    T, n = r.shape
    if T < 10:
        return np.eye(n) * 0.04
    # Initialise with sample covariance of first min(60, T) observations
    init = r[:min(60, T)]
    cov = np.cov(init.T) if init.shape[0] > 1 else np.eye(n) * 0.01
    if cov.ndim == 0:
        cov = np.array([[float(cov)]])
    for t in range(T):
        rt = r[t:t + 1].T           # (n, 1)
        cov = lambda_ * cov + (1 - lambda_) * (rt @ rt.T)
    return _psd(cov * 252)
