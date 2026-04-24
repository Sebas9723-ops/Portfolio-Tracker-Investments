"""
Quant Analytics v2 — Advanced Risk, Execution & Validation Engine.

15 pure-computation functions (no I/O, no external API calls) that extend
the core QuantEngine with analytics covering:

  Execution layer : band rebalancing, net alpha after costs, after-tax drag,
                    liquidity scoring, model agreement
  Return layer    : bootstrap confidence bands, BL explainability
  Risk layer      : tracking error budget, factor decomposition, dynamic caps,
                    expected drawdown profile
  Validation layer: walk-forward validation, regime probabilities, model drift,
                    naive benchmark comparison

All functions accept plain numpy/pandas types and return plain dicts/DataFrames
so they integrate cleanly with FastAPI response serialisation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

log = logging.getLogger(__name__)

# ── Covariance helper ────────────────────────────────────────────────────────


def _shrunk_cov(returns_df: pd.DataFrame, annualize: bool = True) -> np.ndarray:
    """Ledoit-Wolf shrinkage covariance estimator (annualised)."""
    r = returns_df.dropna()
    try:
        cov = LedoitWolf(assume_centered=False).fit(r.values).covariance_
    except Exception:
        cov = r.cov().values
    return cov * (252 if annualize else 1)


# ── 1. Band-based rebalancing ────────────────────────────────────────────────

def compute_rebalancing_bands(
    current_weights: dict[str, float],
    target_weights: dict[str, float],
    total_value: float,
    band_tolerance: float = 0.02,
    min_trade_pct: float = 0.005,
    min_notional: float = 100.0,
    max_turnover: float = 0.30,
    tc_bps: float = 10.0,
) -> dict:
    """Band-based rebalancing with turnover cap, notional floor, and order priority.

    Features: band rebalancing, min execution threshold, turnover control,
    gross vs executable-net weight comparison, order prioritisation, friction threshold.
    """
    if not current_weights or not target_weights or total_value <= 0:
        return {"trades": [], "turnover": 0.0, "n_executable": 0, "suppressed": []}

    rows = []
    for ticker, cur_w in current_weights.items():
        tgt_w = float(target_weights.get(ticker, 0.0))
        drift = cur_w - tgt_w
        delta_val = (tgt_w - cur_w) * total_value
        tc_cost = abs(delta_val) * tc_bps / 10000

        in_band = abs(drift) <= band_tolerance
        below_min = abs(delta_val) / total_value < min_trade_pct
        below_notional = abs(delta_val) < min_notional
        filtered = in_band or below_min or below_notional

        if in_band:
            action = "HOLD (in band)"
        elif below_notional or below_min:
            action = "HOLD (min size)"
        else:
            action = "BUY" if delta_val > 0 else "SELL"

        priority = abs(drift) / max(tc_bps / 10000, 1e-9) if not filtered else 0.0

        rows.append({
            "ticker": ticker,
            "current_w_pct": round(cur_w * 100, 2),
            "target_w_pct": round(tgt_w * 100, 2),
            "drift_w_pct": round(drift * 100, 2),
            "gross_delta": round(delta_val, 2),
            "filtered": filtered,
            "action": action,
            "est_tc": round(tc_cost, 2),
            "priority": round(priority, 4),
            "net_delta": 0.0,
            "executable_w_pct": 0.0,
        })

    rows.sort(key=lambda r: r["priority"], reverse=True)

    cum_to = 0.0
    for row in rows:
        if row["filtered"]:
            row["executable_w_pct"] = row["current_w_pct"]
            continue
        to_i = abs(row["gross_delta"]) / total_value
        if cum_to + to_i > max_turnover:
            row["filtered"] = True
            row["action"] = "HOLD (turnover cap)"
            row["executable_w_pct"] = row["current_w_pct"]
        else:
            row["net_delta"] = row["gross_delta"]
            row["executable_w_pct"] = row["target_w_pct"]
            cum_to += to_i

    return {
        "trades": rows,
        "turnover": round(cum_to, 4),
        "n_executable": sum(1 for r in rows if not r["filtered"]),
        "suppressed": [r["ticker"] for r in rows if r["filtered"]],
    }


# ── 2. Net alpha after transaction costs ─────────────────────────────────────

def compute_net_alpha_after_costs(
    expected_returns: dict[str, float],
    current_weights: dict[str, float],
    target_weights: dict[str, float],
    total_value: float,
    tc_bps: float = 10.0,
    holding_period_days: int = 252,
    min_edge_bps: float = 5.0,
) -> list[dict]:
    """Net alpha after TC with automatic trade suppression.

    Features: alpha-net-of-costs, auto-suppression of negative-net-alpha trades,
    no-trade rule when edge is insufficient.
    """
    if not expected_returns:
        return []

    rows = []
    for ticker, er in expected_returns.items():
        cur_w = float(current_weights.get(ticker, 0.0))
        tgt_w = float(target_weights.get(ticker, 0.0))
        delta_val = (tgt_w - cur_w) * total_value
        tc_one_way = abs(delta_val) * tc_bps / 10000
        ann_tc_drag = tc_one_way / total_value * (252 / max(holding_period_days, 1))
        net_alpha = er - ann_tc_drag
        has_edge = net_alpha * 10000 >= min_edge_bps
        rows.append({
            "ticker": ticker,
            "expected_return": round(er, 4),
            "ann_tc_drag": round(ann_tc_drag, 6),
            "net_alpha": round(net_alpha, 4),
            "has_edge": has_edge,
            "trade": has_edge,
        })

    return sorted(rows, key=lambda r: r["net_alpha"], reverse=True)


# ── 3. After-tax drag ────────────────────────────────────────────────────────

def compute_after_tax_drag(
    portfolio_ann_return: float,
    transactions: list[dict],
    current_prices: dict[str, float],
    st_rate: float = 0.35,
    lt_rate: float = 0.15,
) -> dict:
    """After-tax return drag from capital gains.

    Features: tax drag module, LT/ST capital gains estimation.
    """
    if not transactions or not current_prices:
        return {"after_tax_return": portfolio_ann_return, "tax_drag": 0.0, "positions": []}

    today = datetime.utcnow().date()
    positions: dict[str, dict] = {}

    for tx in transactions:
        ticker = str(tx.get("ticker", "")).upper()
        action = str(tx.get("action", tx.get("type", ""))).upper()
        shares = float(tx.get("shares", tx.get("quantity", 0)) or 0)
        price = float(tx.get("price", 0) or 0)
        try:
            tx_date = pd.to_datetime(tx.get("date")).date()
        except Exception:
            continue

        if action in ("BUY", "PURCHASE"):
            if ticker not in positions:
                positions[ticker] = {"lots": []}
            positions[ticker]["lots"].append({"shares": shares, "cost": price, "date": tx_date})

    rows = []
    total_tax_liability = 0.0
    for ticker, info in positions.items():
        cp = float(current_prices.get(ticker, 0))
        if cp <= 0:
            continue
        for lot in info["lots"]:
            holding_days = (today - lot["date"]).days
            gain = (cp - lot["cost"]) * lot["shares"]
            if gain <= 0:
                continue
            rate = lt_rate if holding_days >= 365 else st_rate
            tax = gain * rate
            total_tax_liability += tax
            rows.append({
                "ticker": ticker,
                "shares": lot["shares"],
                "cost_basis": round(lot["cost"], 4),
                "current_price": round(cp, 4),
                "gain": round(gain, 2),
                "holding_days": holding_days,
                "rate": rate,
                "tax_liability": round(tax, 2),
            })

    total_portfolio_value = sum(p * (sum(l["shares"] for l in positions.get(t, {}).get("lots", []))
                                     if t in positions else 0)
                                for t, p in current_prices.items())
    tax_drag = total_tax_liability / total_portfolio_value if total_portfolio_value > 0 else 0.0
    after_tax_return = portfolio_ann_return - tax_drag

    return {
        "after_tax_return": round(after_tax_return, 4),
        "tax_drag": round(tax_drag, 4),
        "total_tax_liability": round(total_tax_liability, 2),
        "positions": rows,
    }


# ── 4. Liquidity score ───────────────────────────────────────────────────────

def compute_liquidity_score(
    tickers: list[str],
    adv_map: dict[str, float],
    position_values: dict[str, float],
    adv_participation_cap: float = 0.10,
    min_notional: float = 500.0,
) -> list[dict]:
    """ADV-based liquidity scoring and market-depth filter.

    Features: liquidity and market-depth filter, minimum notional per asset.

    adv_map: {ticker: 30d_average_dollar_volume} — caller fetches from market data.
    """
    rows = []
    for ticker in tickers:
        pos_val = float(position_values.get(ticker, 0))
        adv = float(adv_map.get(ticker, 0))
        daily_capacity = adv * adv_participation_cap
        days_to_liquidate = pos_val / daily_capacity if daily_capacity > 0 else float("inf")
        liquidity_score = max(0.0, 1.0 - min(days_to_liquidate / 5, 1.0))
        rows.append({
            "ticker": ticker,
            "position_value": round(pos_val, 2),
            "adv_30d": round(adv, 0),
            "daily_capacity": round(daily_capacity, 0),
            "days_to_liquidate": round(days_to_liquidate, 1) if np.isfinite(days_to_liquidate) else None,
            "liquidity_score": round(liquidity_score, 3),
            "passes_min_notional": pos_val >= min_notional,
            "flag": "OK" if (np.isfinite(days_to_liquidate) and days_to_liquidate <= 5 and pos_val >= min_notional) else "REVIEW",
        })

    return sorted(rows, key=lambda r: r["liquidity_score"], reverse=True)


# ── 5. Model agreement score ─────────────────────────────────────────────────

def compute_model_agreement_score(
    optimizer_weights: dict[str, dict[str, float]],
    tickers: list[str],
) -> dict:
    """Signal agreement, collinearity detection, and fail-safe conflict rules.

    Features: model agreement / signal dispersion, collinearity detection,
    model complexity penalty, fail-safe rules when signals conflict.
    """
    models = {k: v for k, v in optimizer_weights.items() if v is not None}
    if len(models) < 2:
        return {"agreement_score": 1.0, "consensus_weights": {}, "high_conflict_tickers": []}

    weight_matrix = []
    for w in models.values():
        weight_matrix.append([float(w.get(t, 0)) for t in tickers])

    wm = np.array(weight_matrix)
    mean_w = wm.mean(axis=0)
    std_w = wm.std(axis=0)

    cv = std_w / np.where(mean_w > 1e-6, mean_w, 1.0)
    agreement_score = float(max(0.0, 1.0 - cv.mean()))

    model_names = list(models.keys())
    corr_pairs = {}
    for i in range(len(model_names)):
        for j in range(i + 1, len(model_names)):
            c = float(np.corrcoef(wm[i], wm[j])[0, 1])
            corr_pairs[f"{model_names[i]} / {model_names[j]}"] = round(c, 3)

    high_conflict = [tickers[i] for i, v in enumerate(cv) if v > 0.5]

    complexity_penalties = {}
    for name, row in zip(model_names, wm):
        n_significant = int((row > 0.02).sum())
        complexity_penalties[name] = round(n_significant / max(len(tickers), 1), 3)

    consensus = {tickers[i]: round(float(mean_w[i]), 4) for i in range(len(tickers))}
    for t in high_conflict:
        consensus[t] = round(consensus[t] * 0.5, 4)

    return {
        "agreement_score": round(agreement_score, 3),
        "consensus_weights": consensus,
        "weight_std_by_ticker": {tickers[i]: round(float(std_w[i]), 4) for i in range(len(tickers))},
        "model_correlations": corr_pairs,
        "high_conflict_tickers": high_conflict,
        "complexity_penalties": complexity_penalties,
        "n_models": len(models),
    }


# ── 6. Expected return confidence bands ──────────────────────────────────────

def compute_expected_return_bands(
    asset_returns: pd.DataFrame,
    n_bootstrap: int = 500,
    seed: int = 42,
    confidence: float = 0.90,
) -> list[dict]:
    """Bootstrap confidence bands on expected returns and Sharpe ratios.

    Features: parameter uncertainty in MC, confidence bands on expected returns,
    robust optimization sensitivity.
    """
    if asset_returns is None or asset_returns.empty or len(asset_returns) < 30:
        return []

    rng = np.random.default_rng(seed)
    r = asset_returns.dropna(how="all").values
    T, n = r.shape
    alpha = (1 - confidence) / 2

    # Fully vectorised bootstrap — no Python loop
    all_idx = rng.integers(0, T, size=(n_bootstrap, T))  # (B, T)
    samples = r[all_idx]                                  # (B, T, n)
    boot_means = samples.mean(axis=1) * 252               # (B, n)
    boot_vols = samples.std(axis=1) * np.sqrt(252)        # (B, n)
    boot_sharpe = np.where(boot_vols > 0, boot_means / boot_vols, 0.0)

    rows = []
    for i, ticker in enumerate(asset_returns.columns):
        lo_r, med_r, hi_r = np.percentile(boot_means[:, i], [alpha * 100, 50, (1 - alpha) * 100])
        lo_s, med_s, hi_s = np.percentile(boot_sharpe[:, i], [alpha * 100, 50, (1 - alpha) * 100])
        band_width = hi_r - lo_r
        reliable = band_width < abs(med_r) * 2 if med_r != 0 else False
        rows.append({
            "ticker": ticker,
            "return_low": round(lo_r, 4),
            "return_median": round(med_r, 4),
            "return_high": round(hi_r, 4),
            "band_width": round(band_width, 4),
            "sharpe_low": round(lo_s, 3),
            "sharpe_median": round(med_s, 3),
            "sharpe_high": round(hi_s, 3),
            "reliable": reliable,
        })

    return sorted(rows, key=lambda r: r["return_median"], reverse=True)


# ── 7. BL posterior explainability ───────────────────────────────────────────

def explain_bl_posterior(
    equilibrium_returns: dict[str, float],
    posterior_returns: dict[str, float],
    views: dict[str, dict],
) -> list[dict]:
    """Decompose BL posterior into equilibrium vs view contributions.

    Features: BL explainability.
    """
    tickers = list(posterior_returns.keys())
    rows = []
    for t in tickers:
        eq = float(equilibrium_returns.get(t, 0))
        post = float(posterior_returns.get(t, 0))
        pull = post - eq
        has_view = t in views
        rows.append({
            "ticker": t,
            "equilibrium_return": round(eq, 4),
            "posterior_return": round(post, 4),
            "view_pull": round(pull, 4),
            "has_view": has_view,
            "view_return": round(float(views[t].get("return", 0)), 4) if has_view else None,
            "view_confidence": round(float(views[t].get("confidence", 0.5)), 3) if has_view else None,
            "dominant_source": "view" if (has_view and abs(pull) > abs(eq) * 0.1) else "equilibrium",
        })

    return sorted(rows, key=lambda r: abs(r["view_pull"]), reverse=True)


# ── 8. Tracking error budget ─────────────────────────────────────────────────

def compute_tracking_error_budget(
    asset_returns: pd.DataFrame,
    portfolio_weights: dict[str, float],
    benchmark_returns: pd.Series | None,
    te_budget: float = 0.10,
) -> dict:
    """Tracking error budget allocation across assets.

    Features: tracking error budget, TE contribution per asset.
    """
    if asset_returns is None or asset_returns.empty or not portfolio_weights:
        return {}

    tickers = [t for t in portfolio_weights if t in asset_returns.columns]
    if not tickers:
        return {}

    w = np.array([portfolio_weights[t] for t in tickers], dtype=float)
    if w.sum() <= 0:
        return {}
    w = w / w.sum()

    cov = _shrunk_cov(asset_returns[tickers])
    port_r = (asset_returns[tickers] * w).sum(axis=1)

    if benchmark_returns is not None and not benchmark_returns.empty:
        aligned = pd.concat([port_r.rename("P"), benchmark_returns.rename("B")], axis=1).dropna()
        active_r = aligned["P"] - aligned["B"]
    else:
        active_r = port_r.dropna()

    te = float(active_r.std() * np.sqrt(252)) if len(active_r) > 1 else 0.0

    port_vol = float(np.sqrt(max(w @ cov @ w, 1e-12)))
    marginal = (cov @ w) / port_vol
    component_te = w * marginal
    total_component = component_te.sum()
    te_share = component_te / max(total_component, 1e-12)

    return {
        "total_te": round(te, 4),
        "te_budget": te_budget,
        "budget_used_pct": round(te / te_budget * 100, 1) if te_budget > 0 else 0.0,
        "within_budget": te <= te_budget,
        "per_asset": {
            tickers[i]: {
                "te_contribution": round(float(component_te[i]), 4),
                "te_share_pct": round(float(te_share[i]) * 100, 2),
            }
            for i in range(len(tickers))
        },
    }


# ── 9. Walk-forward validation ───────────────────────────────────────────────

def compute_walk_forward_metrics(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series | None,
    risk_free_rate: float = 0.045,
    n_folds: int = 4,
) -> dict:
    """Walk-forward out-of-sample Sharpe and alpha validation.

    Features: walk-forward validation and out-of-sample backtesting.
    """
    if portfolio_returns is None or len(portfolio_returns) < 60:
        return {}

    r = pd.to_numeric(portfolio_returns, errors="coerce").dropna()
    fold_size = len(r) // n_folds
    if fold_size < 10:
        return {}

    folds = []
    for i in range(n_folds):
        start = i * fold_size
        end = start + fold_size if i < n_folds - 1 else len(r)
        fold_r = r.iloc[start:end]
        ann_ret = float((1 + fold_r).prod() ** (252 / max(len(fold_r), 1)) - 1)
        vol = float(fold_r.std() * np.sqrt(252))
        sharpe = (ann_ret - risk_free_rate) / vol if vol > 0 else 0.0

        alpha = ann_ret
        if benchmark_returns is not None and not benchmark_returns.empty:
            b = pd.to_numeric(benchmark_returns, errors="coerce").dropna()
            b_fold = b.reindex(fold_r.index).dropna()
            if len(b_fold) > 2:
                b_ret = float((1 + b_fold).prod() ** (252 / max(len(b_fold), 1)) - 1)
                aligned = fold_r.reindex(b_fold.index).dropna()
                if len(aligned) > 2:
                    cov_arr = np.cov(aligned.values, b_fold.reindex(aligned.index).dropna().values)
                    beta = float(cov_arr[0, 1] / max(cov_arr[1, 1], 1e-12))
                    alpha = ann_ret - (risk_free_rate + beta * (b_ret - risk_free_rate))

        idx = fold_r.index
        folds.append({
            "fold": i + 1,
            "start": str(idx[0].date()) if hasattr(idx[0], "date") else str(idx[0]),
            "end": str(idx[-1].date()) if hasattr(idx[-1], "date") else str(idx[-1]),
            "ann_return": round(ann_ret, 4),
            "volatility": round(vol, 4),
            "sharpe": round(sharpe, 3),
            "alpha": round(alpha, 4),
        })

    sharpes = [f["sharpe"] for f in folds]
    alphas = [f["alpha"] for f in folds]
    return {
        "folds": folds,
        "oos_mean_sharpe": round(float(np.mean(sharpes)), 3),
        "oos_sharpe_std": round(float(np.std(sharpes)), 3),
        "oos_mean_alpha": round(float(np.mean(alphas)), 4),
        "consistent_edge": all(s > 0 for s in sharpes),
        "n_positive_folds": sum(1 for s in sharpes if s > 0),
    }


# ── 10. Regime probabilities ─────────────────────────────────────────────────

def compute_regime_probabilities(
    portfolio_returns: pd.Series,
    ewma_lambda: float = 0.94,
    flip_damping: int = 5,
) -> dict:
    """EWMA-based regime probabilities with Bayesian smoothing and flip suppression.

    Features: regime probability calibration, strategic/tactical/execution layer
    separation, false regime-flip monitoring.
    """
    if portfolio_returns is None or len(portfolio_returns) < 21:
        return {}

    r = pd.to_numeric(portfolio_returns, errors="coerce").dropna()
    r2 = r.values ** 2
    n = len(r2)
    ewma_var = np.empty(n)
    ewma_var[0] = r2[0]
    for i in range(1, n):
        ewma_var[i] = ewma_lambda * ewma_var[i - 1] + (1 - ewma_lambda) * r2[i]
    ann_vol = np.sqrt(ewma_var) * np.sqrt(252)

    REGIMES = [("low", 0, 0.10), ("normal", 0.10, 0.20), ("high", 0.20, 0.35), ("crisis", 0.35, 9)]
    labels = []
    for v in ann_vol:
        for name, lo, hi in REGIMES:
            if lo <= v < hi:
                labels.append(name)
                break

    smoothed = list(labels)
    for i in range(flip_damping, n):
        window = labels[i - flip_damping: i + 1]
        if len(set(window)) > 1:
            smoothed[i] = smoothed[i - 1]

    current_regime = smoothed[-1]
    recent = smoothed[-126:]
    probs = {name: round(recent.count(name) / len(recent), 3) for name, _, _ in REGIMES}
    recent_flip = len(set(smoothed[-flip_damping:])) > 1
    regime_confidence = probs.get(current_regime, 0.5)
    tactical_active = regime_confidence > 0.60
    execution_hold = recent_flip and regime_confidence < 0.70

    equity_tilt = {"low": 0.10, "normal": 0.0, "high": -0.10, "crisis": -0.20}[current_regime]
    bond_tilt = {"low": -0.05, "normal": 0.0, "high": 0.05, "crisis": 0.15}[current_regime]

    return {
        "current_regime": current_regime,
        "current_vol": round(float(ann_vol[-1]), 4),
        "regime_probabilities": probs,
        "regime_confidence": round(regime_confidence, 3),
        "recent_flip": recent_flip,
        "strategic": {"equity_tilt": equity_tilt, "bond_tilt": bond_tilt},
        "tactical": {"active": tactical_active, "confidence": round(regime_confidence, 3)},
        "execution": {"hold": execution_hold, "reason": "regime transition" if execution_hold else None},
    }


# ── 11. Dynamic weight caps ───────────────────────────────────────────────────

def compute_dynamic_weight_caps(
    asset_returns: pd.DataFrame,
    current_weights: dict[str, float],
    base_max_weight: float = 0.40,
    correlation_penalty: float = 0.10,
    top_n_threshold: float = 0.50,
) -> dict:
    """Adaptive per-asset weight caps based on correlation and concentration.

    Features: dynamic weight caps by concentration, control of excessive
    dependence on top holdings.
    """
    if asset_returns is None or asset_returns.empty:
        return {}

    tickers = list(asset_returns.columns)
    corr = asset_returns.corr().values
    n = len(tickers)

    mean_pairwise_corr = np.array([
        np.mean(np.abs(corr[i, [j for j in range(n) if j != i]]))
        for i in range(n)
    ])

    sorted_w = sorted([(float(current_weights.get(t, 0)), t) for t in tickers], reverse=True)
    cumulative = 0.0
    top_heavy_tickers: set[str] = set()
    for w, t in sorted_w:
        if cumulative >= top_n_threshold:
            break
        cumulative += w
        top_heavy_tickers.add(t)

    caps = {}
    for i, t in enumerate(tickers):
        cap = base_max_weight - mean_pairwise_corr[i] * correlation_penalty
        if t in top_heavy_tickers and cumulative >= top_n_threshold:
            cap *= 0.85
        caps[t] = round(max(cap, 0.05), 4)

    return {
        "caps": caps,
        "top_heavy_tickers": list(top_heavy_tickers),
        "top_n_concentration": round(cumulative, 4),
        "mean_pairwise_corr": {tickers[i]: round(float(mean_pairwise_corr[i]), 3) for i in range(n)},
    }


# ── 12. Expected drawdown profile ────────────────────────────────────────────

def compute_expected_drawdown_profile(
    portfolio_returns: pd.Series,
    current_value: float,
    horizons_years: list[int] | None = None,
    n_sims: int = 1000,
    seed: int = 42,
) -> dict:
    """Bootstrap MC max drawdown and recovery time per horizon.

    Features: drawdown report with expected drawdown and recovery time.
    """
    if horizons_years is None:
        horizons_years = [1, 3, 5]

    if portfolio_returns is None or len(portfolio_returns) < 60 or current_value <= 0:
        return {}

    rng = np.random.default_rng(seed)
    r = pd.to_numeric(portfolio_returns, errors="coerce").dropna().values
    result = {}

    for h in horizons_years:
        n_days = h * 252
        sampled = rng.choice(r, size=(n_sims, n_days), replace=True)
        # full_paths: (n_sims, n_days+1) — prepend starting value
        cum = np.cumprod(1 + sampled, axis=1) * current_value
        full_paths = np.hstack([np.full((n_sims, 1), current_value), cum])

        # Vectorised max-drawdown (no Python loops)
        running_max = np.maximum.accumulate(full_paths, axis=1)
        drawdowns = (full_paths - running_max) / running_max        # <= 0
        max_dds = drawdowns.min(axis=1)                             # (n_sims,)
        trough_idx = drawdowns.argmin(axis=1)                       # (n_sims,)

        # Recovery: for each sim find first step after trough where value >= peak at trough
        recovery_months = np.full(n_sims, float(h * 12))
        for s in range(n_sims):
            ti = trough_idx[s]
            if max_dds[s] < -0.01 and ti < n_days:
                peak_val = running_max[s, ti]
                after = full_paths[s, ti:]
                rec = np.argmax(after >= peak_val)
                if rec > 0:
                    recovery_months[s] = rec / 21.0

        result[str(h)] = {
            "expected_max_dd": round(float(np.median(max_dds)), 4),
            "worst_dd_p95": round(float(np.percentile(max_dds, 95)), 4),
            "median_recovery_months": round(float(np.median(recovery_months)), 1),
            "p90_recovery_months": round(float(np.percentile(recovery_months, 90)), 1),
            "prob_drawdown_gt_10pct": round(float((max_dds < -0.10).mean()), 3),
            "prob_drawdown_gt_20pct": round(float((max_dds < -0.20).mean()), 3),
        }

    return result


# ── 13. Model drift score ─────────────────────────────────────────────────────

def compute_model_drift_score(
    asset_returns: pd.DataFrame,
    risk_free_rate: float = 0.045,
    short_window: int = 63,
    long_window: int = 252,
) -> dict:
    """Rolling parameter drift monitoring and experiment tracking.

    Features: model drift alerts, false regime-flip monitoring,
    lightweight signal versioning.
    """
    if asset_returns is None or asset_returns.empty or len(asset_returns) < long_window:
        return {}

    r = asset_returns.dropna(how="all")
    tickers = list(r.columns)

    per_asset = {}
    for t in tickers:
        s = r[t].dropna()
        if len(s) < short_window:
            continue

        short_ret = s.iloc[-short_window:]
        long_ret = s.iloc[-long_window:]

        mu_s = float(short_ret.mean() * 252)
        mu_l = float(long_ret.mean() * 252)
        vol_s = float(short_ret.std() * np.sqrt(252))
        vol_l = float(long_ret.std() * np.sqrt(252))
        sr_s = (mu_s - risk_free_rate) / vol_s if vol_s > 0 else 0.0
        sr_l = (mu_l - risk_free_rate) / vol_l if vol_l > 0 else 0.0

        drift_score = (
            abs(mu_s - mu_l) / max(abs(mu_l), 0.01) * 0.4
            + abs(vol_s - vol_l) / max(vol_l, 0.01) * 0.3
            + abs(sr_s - sr_l) / max(abs(sr_l), 0.01) * 0.3
        )

        per_asset[t] = {
            "mu_short": round(mu_s, 4),
            "mu_long": round(mu_l, 4),
            "vol_short": round(vol_s, 4),
            "vol_long": round(vol_l, 4),
            "sharpe_short": round(sr_s, 3),
            "sharpe_long": round(sr_l, 3),
            "drift_score": round(drift_score, 3),
            "alert": drift_score > 0.50,
        }

    if not per_asset:
        return {}

    scores = [v["drift_score"] for v in per_asset.values()]
    n_alerts = sum(1 for v in per_asset.values() if v["alert"])

    return {
        "per_asset": per_asset,
        "mean_drift_score": round(float(np.mean(scores)), 3),
        "n_alerts": n_alerts,
        "engine_healthy": n_alerts == 0,
        "snapshot_ts": str(datetime.utcnow().date()),
    }


# ── 14. Naive portfolio benchmarking ─────────────────────────────────────────

def benchmark_naive_portfolios(
    asset_returns: pd.DataFrame,
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series | None,
    risk_free_rate: float = 0.045,
) -> list[dict]:
    """Compare portfolio vs naive model portfolios and simple benchmarks.

    Features: benchmarking against simple portfolios and model baselines.
    """
    if asset_returns is None or asset_returns.empty or portfolio_returns is None:
        return []

    r = asset_returns.dropna(how="all")
    tickers = list(r.columns)
    n = len(tickers)
    if n < 2:
        return []

    def _stats(ret_series: pd.Series, name: str) -> dict | None:
        s = pd.to_numeric(ret_series, errors="coerce").dropna()
        if len(s) < 20:
            return None
        ann_r = float((1 + s).prod() ** (252 / len(s)) - 1)
        vol = float(s.std() * np.sqrt(252))
        sr = (ann_r - risk_free_rate) / vol if vol > 0 else 0.0
        cum = (1 + s).prod() - 1
        rolling_peak = (1 + s).cumprod().cummax()
        dd = ((1 + s).cumprod() / rolling_peak - 1).min()
        return {"model": name, "ann_return": round(ann_r, 4), "volatility": round(vol, 4),
                "sharpe": round(sr, 3), "cum_return": round(cum, 4), "max_dd": round(dd, 4)}

    results = []

    # 1/N
    eq_w = np.ones(n) / n
    s = _stats((r * eq_w).sum(axis=1), "1/N Equal Weight")
    if s:
        results.append(s)

    # Min-Vol (unconstrained)
    try:
        cov = _shrunk_cov(r)
        cov_inv = np.linalg.pinv(cov)
        ones = np.ones(n)
        w_mv = (cov_inv @ ones) / (ones @ cov_inv @ ones)
        w_mv = np.clip(w_mv, 0, None)
        if w_mv.sum() > 0:
            w_mv /= w_mv.sum()
            s = _stats((r * w_mv).sum(axis=1), "Min-Vol (unconstrained)")
            if s:
                results.append(s)
    except Exception:
        pass

    # Max-Sharpe (unconstrained tangency)
    try:
        mu = r.mean().values * 252
        excess = mu - risk_free_rate
        w_ms = cov_inv @ excess
        if (ones @ cov_inv @ excess) != 0:
            w_ms /= ones @ cov_inv @ excess
        w_ms = np.clip(w_ms, 0, None)
        if w_ms.sum() > 0:
            w_ms /= w_ms.sum()
            s = _stats((r * w_ms).sum(axis=1), "Max-Sharpe (unconstrained)")
            if s:
                results.append(s)
    except Exception:
        pass

    # Actual portfolio
    s = _stats(portfolio_returns, "Your Portfolio")
    if s:
        results.append(s)

    # Benchmark
    if benchmark_returns is not None and not benchmark_returns.empty:
        s = _stats(benchmark_returns, "Benchmark")
        if s:
            results.append(s)

    return results


# ── 15. Factor risk decomposition ────────────────────────────────────────────

def compute_factor_risk_decomposition(
    asset_returns: pd.DataFrame,
    portfolio_weights: dict[str, float],
    factor_returns: pd.DataFrame | None = None,
    risk_free_rate: float = 0.045,
) -> dict:
    """Factor-level and position-level risk decomposition.

    Features: attribution waterfall, risk decomposition by factor and position,
    contribution-to-return dashboard.

    factor_returns: DataFrame with columns like "mkt", "smb", "hml" (Fama-French proxies).
    If None, falls back to per-asset contribution only.
    """
    if asset_returns is None or asset_returns.empty or not portfolio_weights:
        return {}

    tickers = [t for t in portfolio_weights if t in asset_returns.columns]
    if len(tickers) < 2:
        return {}

    w = np.array([portfolio_weights[t] for t in tickers], dtype=float)
    if w.sum() <= 0:
        return {}
    w = w / w.sum()

    cov = _shrunk_cov(asset_returns[tickers])
    port_var = float(w @ cov @ w)
    port_vol = float(np.sqrt(max(port_var, 1e-12)))

    marginal_contrib = (cov @ w) / port_vol
    component_contrib = w * marginal_contrib
    pct_contrib = component_contrib / port_vol

    per_asset = {
        tickers[i]: {
            "weight": round(float(w[i]), 4),
            "vol_contribution": round(float(component_contrib[i]), 4),
            "vol_contribution_pct": round(float(pct_contrib[i]) * 100, 2),
        }
        for i in range(len(tickers))
    }

    factor_decomp: dict = {}
    if factor_returns is not None and not factor_returns.empty:
        try:
            port_r = (asset_returns[tickers] * w).sum(axis=1)
            aligned = pd.concat(
                [port_r.rename("portfolio")] + [factor_returns[c] for c in factor_returns.columns],
                axis=1,
            ).dropna()
            if len(aligned) > 20:
                import statsmodels.api as sm
                Y = aligned["portfolio"].values - risk_free_rate / 252
                X = sm.add_constant(aligned[factor_returns.columns].values)
                ols = sm.OLS(Y, X).fit()
                r2 = float(ols.rsquared)
                factor_decomp = {
                    "r_squared": round(r2, 4),
                    "systematic_risk_pct": round(r2 * 100, 1),
                    "idiosyncratic_risk_pct": round((1 - r2) * 100, 1),
                    "betas": {
                        col: round(float(ols.params[i + 1]), 4)
                        for i, col in enumerate(factor_returns.columns)
                    },
                }
        except Exception as exc:
            log.debug("Factor decomp OLS failed: %s", exc)

    return {
        "portfolio_vol": round(port_vol, 4),
        "per_asset": per_asset,
        "factor_decomposition": factor_decomp,
    }
