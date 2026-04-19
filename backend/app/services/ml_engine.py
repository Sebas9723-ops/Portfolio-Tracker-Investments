"""
ML Engine — feeds into Quant Engine contribution planner.

Modules (all optional, degrade gracefully):
  1. GARCH(1,1)         → dynamic covariance  (arch)
  2. Fama-French 5      → expected returns     (pandas_datareader + statsmodels)
  3. GMM 4-state        → regime               (sklearn)
  4. XGBoost            → ML-BL views          (xgboost)

All 4 converge in run_ml_pipeline().
"""
from __future__ import annotations

import logging
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf
from sklearn.mixture import GaussianMixture
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

_REGIME_LABELS = ["bull_strong", "bull_weak", "bear_mild", "crisis"]


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class MLResult:
    # GARCH
    garch_cov: np.ndarray
    garch_vols: dict[str, float]
    garch_available: bool

    # Fama-French 5
    ff5_returns: pd.Series
    ff5_loadings: dict[str, dict[str, float]]
    ff5_available: bool

    # GMM regime
    regime: str                          # "bull_strong"|"bull_weak"|"bear_mild"|"crisis"
    regime_confidence: float
    regime_probs: dict[str, float]
    regime_available: bool

    # XGBoost ML-BL (merged with user views)
    bl_views: dict[str, dict]
    xgb_available: bool

    diagnostics: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


# ── Engine ────────────────────────────────────────────────────────────────────

class MLEngine:
    """Full ML pipeline for portfolio optimization."""

    def __init__(self, risk_free_rate: float = 0.045):
        self.rfr = risk_free_rate

    # ── 1. GARCH(1,1) Covariance ──────────────────────────────────────────

    def fit_garch_covariance(
        self, returns: pd.DataFrame
    ) -> tuple[dict[str, float], np.ndarray, bool]:
        """
        Per-ticker GARCH(1,1) conditional variance → GARCH-adjusted covariance.

        Algorithm:
          - Fit arch_model(r_i * 100, vol='Garch', p=1, q=1) per ticker
          - Extract 1-step-ahead conditional variance h_T, convert to annualized vol
          - Build cov = outer(garch_vols) * LW_correlation
        Falls back to sample variance per ticker on failure.
        """
        tickers = list(returns.columns)
        n = len(tickers)
        garch_vols: dict[str, float] = {}

        for t in tickers:
            series = returns[t].dropna()
            if len(series) < 100 or not _ARCH_OK:
                garch_vols[t] = float(series.std() * np.sqrt(252))
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    mdl = arch_model(
                        series * 100,
                        vol="Garch", p=1, q=1,
                        dist="normal", rescale=False,
                    )
                    res = mdl.fit(disp="off", show_warning=False,
                                  options={"maxiter": 200, "ftol": 1e-6})
                    fc = res.forecast(horizon=1, reindex=False)
                    daily_var = float(fc.variance.iloc[-1, 0]) / 1e4  # /100²
                    garch_vols[t] = np.sqrt(daily_var * 252)
            except Exception as exc:
                log.warning("GARCH failed for %s: %s", t, exc)
                garch_vols[t] = float(series.std() * np.sqrt(252))

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
        cov = np.outer(vol_arr, vol_arr) * corr
        cov = _psd(cov)

        success = _ARCH_OK and all(
            len(returns[t].dropna()) >= 100 for t in tickers
        )
        return garch_vols, cov, success

    # ── 2. Fama-French 5-Factor Expected Returns ──────────────────────────

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

    # ── 3. GMM 4-State Regime ─────────────────────────────────────────────

    def fit_gmm_regime(
        self,
        returns: pd.DataFrame,
        market_ticker: Optional[str] = None,
    ) -> tuple[str, float, dict[str, float], bool]:
        """
        GaussianMixture(n=4) on [daily_return, rolling_20d_vol] features.
        States labeled by sorting component mean_return descending:
          bull_strong → bull_weak → bear_mild → crisis
        Returns (regime_label, confidence, probs_dict, success).
        """
        _default = (
            "bull_weak", 0.5,
            {"bull_strong": 0.15, "bull_weak": 0.55, "bear_mild": 0.20, "crisis": 0.10},
            False,
        )

        if market_ticker is None or market_ticker not in returns.columns:
            market_ticker = returns.columns[0]

        mkt = returns[market_ticker].dropna()
        if len(mkt) < 120:
            return _default

        vol20 = mkt.rolling(20).std() * np.sqrt(252)
        features = pd.DataFrame({"ret": mkt, "vol": vol20}).dropna()

        if len(features) < 60:
            return _default

        try:
            scaler = StandardScaler()
            X = scaler.fit_transform(features.values)

            gmm = GaussianMixture(
                n_components=4,
                covariance_type="full",
                n_init=5,
                max_iter=300,
                random_state=42,
            )
            gmm.fit(X)

            labels = gmm.predict(X)
            posteriors = gmm.predict_proba(X)

            # Map component indices → regime labels by mean return (descending)
            comp_mean_ret = [
                float(scaler.mean_[0] + scaler.scale_[0] * gmm.means_[k, 0])
                for k in range(4)
            ]
            sorted_comps = sorted(range(4), key=lambda k: comp_mean_ret[k], reverse=True)
            comp_to_label = {sorted_comps[i]: _REGIME_LABELS[i] for i in range(4)}

            # Smooth over last 20 observations (robust to single-day spikes)
            recent_post = posteriors[-20:].mean(axis=0)  # (4,)
            current_comp = int(np.argmax(recent_post))
            regime = comp_to_label[current_comp]
            confidence = float(recent_post[current_comp])

            probs = {comp_to_label[k]: round(float(recent_post[k]), 4) for k in range(4)}

            return regime, round(confidence, 4), probs, True

        except Exception as exc:
            log.warning("GMM regime failed: %s", exc)
            return _default

    # ── 4. XGBoost ML-BL Views ────────────────────────────────────────────

    def generate_xgb_bl_views(
        self,
        returns: pd.DataFrame,
        ff5_returns: pd.Series,
        garch_vols: dict[str, float],
        user_bl_views: dict,
    ) -> tuple[dict[str, dict], bool]:
        """
        Per-ticker XGBoost predicts 1-month forward return.
        Prediction → BL view with confidence from walk-forward MAE.
        User views always override ML views (merged last).
        """
        if not _XGB_OK:
            return dict(user_bl_views), False

        tickers = list(returns.columns)
        ml_views: dict[str, dict] = {}

        for t in tickers:
            if t in user_bl_views:
                continue  # user view takes precedence, skip ML for this ticker

            series = returns[t].dropna()
            if len(series) < 252:
                continue

            try:
                feats = self._ticker_features(series, garch_vols.get(t, 0.15))
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
                    n_estimators=100,
                    max_depth=3,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
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

                # Only include if prediction meaningfully differs from FF5
                ff5_ret = float(ff5_returns.get(t, 0.0))
                if abs(predicted - ff5_ret) > 0.005:
                    ml_views[t] = {
                        "return": round(predicted, 6),
                        "confidence": round(confidence, 4),
                        "source": "xgboost",
                    }

            except Exception as exc:
                log.warning("XGB-BL failed for %s: %s", t, exc)

        # User views override ML — merge last
        merged = {**ml_views, **user_bl_views}
        return merged, True

    def _ticker_features(
        self, series: pd.Series, garch_vol: float
    ) -> Optional[pd.DataFrame]:
        """Feature matrix for XGBoost BL prediction."""
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
        return f.dropna()

    # ── 5. Full ML Pipeline ───────────────────────────────────────────────

    def run_ml_pipeline(
        self,
        returns: pd.DataFrame,
        user_bl_views: dict,
        market_ticker: str = "VOO",
    ) -> MLResult:
        """
        Orchestrate all 4 ML modules. Each module is isolated — failures
        populate *_available=False and fall back to safe defaults.
        """
        diag: dict[str, Any] = {}
        tickers = list(returns.columns)

        # 1. GARCH covariance
        t0 = time.monotonic()
        log.info("ML: GARCH covariance (%d tickers)", len(tickers))
        garch_vols, garch_cov, garch_ok = self.fit_garch_covariance(returns)
        diag["garch_ms"] = round((time.monotonic() - t0) * 1000)
        diag["garch_available"] = garch_ok
        diag["garch_vols"] = {t: round(v, 4) for t, v in garch_vols.items()}

        # 2. FF5 expected returns
        t0 = time.monotonic()
        log.info("ML: Fama-French 5-factor returns")
        ff5_returns, ff5_loadings, ff5_ok = self.fit_fama_french(returns)
        if not ff5_ok or ff5_returns.empty:
            ff5_returns = self._capm_returns(returns)
        diag["ff5_ms"] = round((time.monotonic() - t0) * 1000)
        diag["ff5_available"] = ff5_ok
        diag["ff5_loadings"] = ff5_loadings

        # 3. GMM 4-state regime
        t0 = time.monotonic()
        log.info("ML: GMM 4-state regime")
        regime, regime_conf, regime_probs, regime_ok = self.fit_gmm_regime(
            returns, market_ticker
        )
        diag["regime_ms"] = round((time.monotonic() - t0) * 1000)
        diag["regime_available"] = regime_ok

        # 4. XGBoost ML-BL views
        t0 = time.monotonic()
        log.info("ML: XGBoost BL views")
        bl_views, xgb_ok = self.generate_xgb_bl_views(
            returns, ff5_returns, garch_vols, user_bl_views
        )
        diag["xgb_ms"] = round((time.monotonic() - t0) * 1000)
        diag["xgb_available"] = xgb_ok
        diag["xgb_views_generated"] = sum(
            1 for v in bl_views.values()
            if isinstance(v, dict) and v.get("source") == "xgboost"
        )

        log.info(
            "ML pipeline done — GARCH=%s FF5=%s regime=%s(%s) XGB=%s views=%d",
            garch_ok, ff5_ok, regime, round(regime_conf, 2), xgb_ok,
            diag["xgb_views_generated"],
        )

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
            regime_available=regime_ok,
            bl_views=bl_views,
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
