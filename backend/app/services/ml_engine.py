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

        # Trailing annualized factor premiums (use full available history)
        factor_premia = ff5[FACTORS].mean() * 252
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

            model = hmmlib.GaussianHMM(
                n_components=4,
                covariance_type="full",
                n_iter=100,
                random_state=42,
                tol=1e-4,
            )
            model.fit(X)

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
    ) -> tuple[dict[str, dict], bool]:
        """
        Per-ticker XGBoost predicts 1-month forward return.
        Regime one-hot features added from historical HMM label sequence.
        Prediction → BL view with confidence from walk-forward MAE.
        User views always override ML views (merged last).
        Returns (ml_only_views, success) — caller merges user views.
        """
        if not _XGB_OK:
            return {}, False

        tickers = list(returns.columns)
        ml_views: dict[str, dict] = {}

        for t in tickers:
            if t in user_bl_views:
                continue  # user view takes precedence, skip ML for this ticker

            series = returns[t].dropna()
            if len(series) < 252:
                continue

            try:
                feats = self._ticker_features(series, garch_vols.get(t, 0.15), regime_labels, current_regime)
                if feats is None or len(feats) < 80:
                    continue

                # Target: annualized 21-day forward return
                fwd = series.shift(-21).rolling(21).sum() * (252 / 21)
                idx = feats.index.intersection(fwd.dropna().index)
                if len(idx) < 80:
                    continue

                X = feats.loc[idx].values
                y = fwd.loc[idx].values

                # Walk-forward split: train on all but last 63 days
                split = max(60, len(X) - 63)
                X_tr, y_tr = X[:split], y[:split]
                X_cur = feats.iloc[[-1]].values

                xgb = XGBRegressor(
                    n_estimators=150,
                    max_depth=3,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    min_child_weight=5,
                    random_state=42,
                    verbosity=0,
                )
                xgb.fit(X_tr, y_tr)
                predicted = float(xgb.predict(X_cur)[0])

                # Confidence from validation MAE
                if len(X) > split + 5:
                    y_val_pred = xgb.predict(X[split:])
                    mae = float(np.mean(np.abs(y_val_pred - y[split:])))
                    confidence = float(np.clip(1.0 / (1.0 + mae * 4), 0.10, 0.70))
                else:
                    confidence = 0.30

                # Blend XGB (short-term) with FF5 (long-term fundamental)
                # Short horizon → trust XGBoost more; long → trust FF5 more
                xgb_weight = _XGB_WEIGHT_BY_HORIZON.get(time_horizon, 0.50)
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
    ) -> Optional[pd.DataFrame]:
        """Feature matrix for XGBoost BL prediction, including regime one-hot columns."""
        if len(series) < 130:
            return None
        f = pd.DataFrame(index=series.index)
        f["mom_1m"] = series.rolling(21).sum()
        f["mom_3m"] = series.rolling(63).sum()
        f["mom_6m"] = series.rolling(126).sum()
        f["mom_12m"] = series.rolling(252).sum()
        f["vol_20"] = series.rolling(20).std() * np.sqrt(252)
        f["vol_60"] = series.rolling(60).std() * np.sqrt(252)
        f["vol_ratio"] = f["vol_20"] / (f["vol_60"] + 1e-8)
        f["zscore"] = (
            (series.rolling(21).mean() - series.rolling(60).mean())
            / (series.rolling(60).std() + 1e-8)
        )
        f["garch_vol"] = garch_vol  # constant per ticker, encodes cross-sectional vol signal

        # Regime one-hot features
        for lbl in ["bull_strong", "bull_weak", "bear_mild", "crisis"]:
            if not regime_labels.empty:
                reg_aligned = regime_labels.reindex(series.index, method="ffill")
                f[f"regime_{lbl}"] = (reg_aligned == lbl).astype(float)
            else:
                f[f"regime_{lbl}"] = 1.0 if lbl == current_regime else 0.0

        return f.dropna()

    # ── 6. Full ML Pipeline ───────────────────────────────────────────────

    def run_ml_pipeline(
        self,
        returns: pd.DataFrame,
        user_bl_views: dict,
        market_ticker: str = "VOO",
        time_horizon: str = "long",
    ) -> MLResult:
        """
        Orchestrate all ML modules. Each module is isolated — failures
        populate *_available=False and fall back to safe defaults.

        TTL cache (4h) stores everything except user BL views.
        On cache hit: re-merges user views with cached XGB ML views.
        On cache miss: runs full pipeline, stores to cache.
        """
        tickers = list(returns.columns)
        cache_key = (tuple(sorted(tickers)), round(self.rfr, 3), time_horizon)

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

        # 2. DCC(1,1) covariance
        t1 = time.monotonic()
        log.info("ML: DCC(1,1) dynamic correlations")
        try:
            dcc_cov = self.fit_dcc_covariance(tickers, garch_vols, garch_std_resids)
            dcc_ok = True
        except Exception as exc:
            log.warning("DCC covariance failed: %s — using GARCH+LW fallback", exc)
            dcc_cov = fallback_cov
            dcc_ok = False
        diag["dcc_ms"] = round((time.monotonic() - t1) * 1000)
        diag["dcc_available"] = dcc_ok

        # Use DCC cov if available, else fallback to GARCH+LW
        garch_cov = dcc_cov if dcc_ok else fallback_cov

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
