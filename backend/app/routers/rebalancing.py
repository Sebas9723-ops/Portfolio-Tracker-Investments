from fastapi import APIRouter, Depends, Query
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from app.auth.dependencies import get_user_id
from app.services.market_data import get_risk_free_rate, get_historical_multi
from app.compute.rebalancing import build_rebalancing_table, compute_target_weights_from_drift, TC_MODELS
from app.compute.optimization import simulate_efficient_frontier, optimize_max_sharpe, optimize_max_return
from app.compute.profile import compute_profile_weights, compute_profile_metrics, _CVAR_LIMIT_DEFAULT, _cvar_constraint
from app.models.analytics import RebalancingRow
from app.services.portfolio_service import load_portfolio_data
from app.db.quant_results import load_latest_quant_result, load_user_bl_views

router = APIRouter(prefix="/api/rebalancing", tags=["rebalancing"])

# ── Regime → threshold multiplier per profile ─────────────────────────────────
# Conservative in crisis → raise threshold (trade less, protect capital)
# Aggressive in bull    → lower threshold (rebalance more, capture upside)
_REGIME_THRESHOLD_MULT: dict[str, dict[str, float]] = {
    "bull_strong": {"conservative": 1.0, "base": 1.0, "aggressive": 0.8},
    "bull_weak":   {"conservative": 1.1, "base": 1.0, "aggressive": 0.9},
    "bear_mild":   {"conservative": 1.3, "base": 1.1, "aggressive": 1.0},
    "crisis":      {"conservative": 1.6, "base": 1.2, "aggressive": 1.0},
}

# ── Regime → CVaR limit scaling per profile ───────────────────────────────────
# In crisis: tighten CVaR for conservative/base; aggressive stays same
_REGIME_CVAR_MULT: dict[str, dict[str, float]] = {
    "bull_strong": {"conservative": 1.1, "base": 1.1, "aggressive": 1.2},
    "bull_weak":   {"conservative": 1.0, "base": 1.0, "aggressive": 1.1},
    "bear_mild":   {"conservative": 0.85, "base": 0.90, "aggressive": 1.0},
    "crisis":      {"conservative": 0.70, "base": 0.80, "aggressive": 0.95},
}


def _compute_bl_mu(
    returns_df: pd.DataFrame,
    bl_views: dict,
    risk_aversion: float = 2.5,
    tau: float = 0.05,
) -> np.ndarray:
    """
    Black-Litterman posterior expected returns (annualized).
    Uses equal-weight market portfolio as prior.
    bl_views: {ticker: {"return": float, "confidence": float}}
    """
    tickers = list(returns_df.columns)
    n = len(tickers)
    cov = returns_df.cov().values * 252
    w_eq = np.ones(n) / n
    pi = risk_aversion * cov @ w_eq  # equilibrium returns

    view_tickers = [t for t in bl_views if t in tickers]
    if not view_tickers:
        return pi

    k = len(view_tickers)
    P = np.zeros((k, n))
    q = np.zeros(k)
    omega_diag = np.zeros(k)
    for i, t in enumerate(view_tickers):
        j = tickers.index(t)
        P[i, j] = 1.0
        q[i] = float(bl_views[t]["return"])
        conf = float(bl_views[t].get("confidence", 0.5))
        # Higher confidence → smaller uncertainty (omega)
        omega_diag[i] = tau * cov[j, j] * max(1.0 - conf, 0.05)

    tau_sigma = tau * cov
    omega = np.diag(omega_diag)
    try:
        inv_tau_sigma = np.linalg.inv(tau_sigma + np.eye(n) * 1e-8)
        inv_omega = np.linalg.inv(omega + np.eye(k) * 1e-8)
        M = inv_tau_sigma + P.T @ inv_omega @ P
        mu_bl = np.linalg.solve(M + np.eye(n) * 1e-8, inv_tau_sigma @ pi + P.T @ inv_omega @ q)
        return mu_bl
    except np.linalg.LinAlgError:
        return pi


@router.get("/suggestions", response_model=list[RebalancingRow])
def suggestions(
    contribution: float = Query(default=0.0),
    tc_model: str = Query(default="broker"),
    user_id: str = Depends(get_user_id),
):
    summary, tickers, settings = load_portfolio_data(user_id)
    if not tickers:
        return []

    threshold = float(settings.get("rebalancing_threshold", 0.05))
    investor_profile = settings.get("investor_profile", "balanced")
    target_return = float(settings.get("target_return", 0.08))
    rfr = float(settings.get("risk_free_rate", 0.045))
    max_single = float(settings.get("max_single_asset", 0.40))
    bl_risk_aversion_s = float(settings.get("bl_risk_aversion") or 2.5)
    bl_tau_s = float(settings.get("bl_tau") or 0.05)

    rows_dicts = [r.model_dump() for r in summary.rows]

    # ── Motor 1 & 2 constraints ───────────────────────────────────────────────
    ticker_weight_rules = settings.get("ticker_weight_rules") or {}
    combination_ranges = settings.get("combination_ranges") or {}
    profile_key = investor_profile if investor_profile in ("conservative", "base", "aggressive") else None

    per_ticker_bounds = None
    combination_constraints = None
    if profile_key:
        profile_rules = ticker_weight_rules.get(profile_key, {})
        per_ticker_bounds = {
            ticker: (float(rule.get("floor", 0.0)), float(rule.get("cap", 1.0)))
            for ticker, rule in profile_rules.items()
            if isinstance(rule, dict)
        } or None
        combination_constraints = combination_ranges.get(profile_key, []) or None

    # ── Load quant cache (regime + CVaR + optimal weights) ───────────────────
    regime = None
    cvar_95_daily = None
    target_weights = None

    try:
        cached_qr = load_latest_quant_result(user_id)
        if cached_qr:
            regime = cached_qr.get("regime")  # e.g. "bull_strong", "crisis"
            cvar_raw = cached_qr.get("cvar_95")
            if cvar_raw is not None:
                cvar_95_daily = float(cvar_raw)

            # Priority 1: use cached optimal weights if they cover the portfolio
            raw_w = cached_qr.get("optimal_weights") or {}
            if isinstance(raw_w, dict):
                filtered = {t: float(w) for t, w in raw_w.items() if t in tickers}
                wsum = sum(filtered.values())
                if wsum > 0.5:
                    target_weights = {t: w / wsum for t, w in filtered.items()}
    except Exception:
        pass

    # ── Regime → adjust threshold per profile ────────────────────────────────
    if regime and profile_key and regime in _REGIME_THRESHOLD_MULT:
        mult = _REGIME_THRESHOLD_MULT[regime].get(profile_key, 1.0)
        threshold = threshold * mult

    # ── CVaR limit: scale regime multiplier per profile ───────────────────────
    cvar_limit = None
    if cvar_95_daily is not None and profile_key and regime in (_REGIME_CVAR_MULT or {}):
        cvar_mult = _REGIME_CVAR_MULT.get(regime, {}).get(profile_key, 1.0)
        cvar_limit = cvar_95_daily * cvar_mult
    elif profile_key:
        # Fallback: use profile default (defined inside profile.py)
        cvar_limit = None  # profile.py will apply _CVAR_LIMIT_DEFAULT

    # ── Priority 2: profile-driven weights with BL + CVaR ────────────────────
    if target_weights is None and profile_key:
        try:
            hist = get_historical_multi(tickers, period="2y")
            closes: dict[str, pd.Series] = {}
            for t, df in hist.items():
                if not df.empty:
                    col = "Close" if "Close" in df.columns else df.columns[0]
                    closes[t] = df[col].dropna()
            returns_df = pd.DataFrame(closes).dropna(how="all").ffill().pct_change().dropna()

            if not returns_df.empty:
                # Load BL views and compute BL-adjusted mu if views exist
                mu_bl = None
                try:
                    bl_views = load_user_bl_views(user_id)
                    if bl_views:
                        mu_bl = _compute_bl_mu(returns_df, bl_views, risk_aversion=bl_risk_aversion_s, tau=bl_tau_s)
                except Exception:
                    pass

                target_weights = compute_profile_weights(
                    returns_df,
                    profile_key,
                    rfr,
                    target_return,
                    max_single,
                    per_ticker_bounds,
                    combination_constraints,
                    mu_override=mu_bl,
                    cvar_limit=cvar_limit,
                )
        except Exception:
            pass

    # ── Priority 3: drift-based equal-weight fallback ─────────────────────────
    if target_weights is None:
        target_weights = compute_target_weights_from_drift(rows_dicts, threshold)

    return build_rebalancing_table(
        portfolio_rows=rows_dicts,
        target_weights=target_weights,
        total_value=summary.total_value_base,
        contribution=contribution,
        tc_model=tc_model,
        threshold=threshold,
    )


@router.get("/required-for-max-sharpe")
def required_for_max_sharpe(
    period: str = Query(default="2y"),
    max_single_asset: float = Query(default=0.40),
    user_id: str = Depends(get_user_id),
):
    """
    Computes the minimum cash contribution needed to reach Max Sharpe weights
    without selling any existing positions.
    """
    summary, tickers, settings = load_portfolio_data(user_id)
    if not tickers:
        return {"required_contribution": 0, "max_sharpe_weights": {}, "buy_plan": {}}

    hist = get_historical_multi(tickers, period=period)
    closes: dict[str, pd.Series] = {}
    for t, df in hist.items():
        if not df.empty:
            col = "Close" if "Close" in df.columns else df.columns[0]
            closes[t] = df[col].dropna()

    returns_df = pd.DataFrame(closes).dropna(how="all").ffill().pct_change().dropna()
    rfr = get_risk_free_rate()

    investor_profile = settings.get("investor_profile", "base")
    profile_key = investor_profile if investor_profile in ("conservative", "base", "aggressive") else "base"
    ticker_weight_rules = settings.get("ticker_weight_rules") or {}
    combination_ranges_data = settings.get("combination_ranges") or {}

    profile_rules = ticker_weight_rules.get(profile_key, {})
    per_ticker_bounds = {
        ticker: (float(rule.get("floor", 0.0)), float(rule.get("cap", 1.0)))
        for ticker, rule in profile_rules.items()
        if isinstance(rule, dict)
    } or None
    combination_constraints = combination_ranges_data.get(profile_key, []) or None

    target_return_val = float(settings.get("target_return", 0.08))

    # Load BL views and CVaR from quant cache
    mu_bl = None
    cvar_limit = None
    try:
        bl_views = load_user_bl_views(user_id)
        if bl_views and not returns_df.empty:
            mu_bl = _compute_bl_mu(returns_df, bl_views)
    except Exception:
        pass
    try:
        cached_qr = load_latest_quant_result(user_id)
        if cached_qr and cached_qr.get("cvar_95") is not None:
            regime = cached_qr.get("regime", "bull_weak")
            cvar_mult = _REGIME_CVAR_MULT.get(regime, {}).get(profile_key, 1.0)
            cvar_limit = float(cached_qr["cvar_95"]) * cvar_mult
    except Exception:
        pass

    ms_weights = compute_profile_weights(
        returns_df, profile_key, rfr, target_return_val, max_single_asset,
        per_ticker_bounds, combination_constraints,
        mu_override=mu_bl, cvar_limit=cvar_limit,
    )

    if not ms_weights:
        return {"required_contribution": 0, "max_sharpe_weights": {}, "buy_plan": {}}

    current_values = {r.ticker: r.value_base for r in summary.rows}
    total_value = summary.total_value_base

    required = 0.0
    for ticker, w in ms_weights.items():
        if w > 0:
            v = current_values.get(ticker, 0.0)
            implied_total = v / w
            required = max(required, implied_total - total_value)

    required = max(0.0, round(required, 2))
    total_new = total_value + required

    buy_plan = {}
    for ticker, w in ms_weights.items():
        target_value = w * total_new
        current_v = current_values.get(ticker, 0.0)
        buy_value = max(0.0, target_value - current_v)
        buy_plan[ticker] = {
            "buy_value": round(buy_value, 2),
            "buy_pct": round(buy_value / required * 100, 2) if required > 0 else 0.0,
            "target_weight": round(w * 100, 2),
            "current_weight": round(current_v / total_value * 100, 2) if total_value > 0 else 0.0,
        }

    profile_metrics = compute_profile_metrics(returns_df, ms_weights, rfr)

    return {
        "required_contribution": required,
        "max_sharpe_weights": {t: round(w * 100, 2) for t, w in ms_weights.items()},
        "buy_plan": buy_plan,
        "total_value": total_value,
        "total_after": round(total_new, 2),
        "profile": profile_key,
        "profile_metrics": profile_metrics,
    }


# ── Regime → per-ticker mu scaling ────────────────────────────────────────────
# In bull: boost mu by 10% for all tickers
# In crisis: cut mu by 30% — penalize equity-like returns heavily
_REGIME_MU_SCALE: dict[str, float] = {
    "bull_strong": 1.10,
    "bull_weak":   1.02,
    "bear_mild":   0.85,
    "crisis":      0.70,
}


@router.get("/deploy-capital")
def deploy_capital(
    amount: float = Query(..., description="Cash to deploy (base currency)"),
    tc_model: str = Query(default="broker"),
    user_id: str = Depends(get_user_id),
):
    """
    Quant-enhanced buy-only capital deployment.

    Uses cached QuantEngine signals (regime_probs, correlation_alerts,
    expected_return) + BL views + net_alpha + liquidity to decide
    exactly where to put new capital — maximising risk-adjusted return
    without selling any existing position.

    Returns per-ticker: amount, pct_of_capital, signals (why).
    """
    if amount <= 0:
        return {"allocations": [], "signals": {}, "regime": None, "mu_source": "none"}

    summary, tickers, settings = load_portfolio_data(user_id)
    if not tickers:
        return {"allocations": [], "signals": {}, "regime": None, "mu_source": "equal"}

    profile_raw = settings.get("investor_profile", "base")
    profile_key = profile_raw if profile_raw in ("conservative", "base", "aggressive") else "base"
    rfr = float(settings.get("risk_free_rate", 0.045))
    max_single = float(settings.get("max_single_asset", 0.40))
    ticker_weight_rules = settings.get("ticker_weight_rules") or {}
    combination_ranges = settings.get("combination_ranges") or {}

    profile_rules = ticker_weight_rules.get(profile_key, {})
    per_ticker_bounds: dict[str, tuple[float, float]] = {
        t: (float(r.get("floor", 0.0)), float(r.get("cap", 1.0)))
        for t, r in profile_rules.items() if isinstance(r, dict)
    } or {}
    combination_constraints = combination_ranges.get(profile_key, []) or []

    # BL params from user settings (persisted)
    bl_risk_aversion = float(settings.get("bl_risk_aversion") or 2.5)
    bl_tau = float(settings.get("bl_tau") or 0.05)

    total_value = float(summary.total_value_base)
    current_values = {r.ticker: float(r.value_base) for r in summary.rows}
    current_weights = {r.ticker: float(r.weight) / 100 for r in summary.rows}

    # ── Load historical returns (1y, cached) ──────────────────────────────────
    try:
        hist = get_historical_multi(tickers, period="1y")
        closes = {}
        for t, df in hist.items():
            if not df.empty:
                col = "Close" if "Close" in df.columns else df.columns[0]
                closes[t] = df[col].dropna()
        returns_df = pd.DataFrame(closes).dropna(how="all").ffill().pct_change().dropna()
    except Exception:
        returns_df = pd.DataFrame()

    if returns_df.empty:
        return {"allocations": [], "signals": {}, "regime": None, "mu_source": "none"}

    tickers_avail = [t for t in tickers if t in returns_df.columns]
    if not tickers_avail:
        return {"allocations": [], "signals": {}, "regime": None, "mu_source": "none"}

    returns_df = returns_df[tickers_avail]
    n = len(tickers_avail)
    mu_hist = returns_df.mean().values * 252
    cov = returns_df.cov().values * 252

    # ── Load quant cache ──────────────────────────────────────────────────────
    regime = None
    regime_probs: dict[str, float] = {}
    corr_alerts: list[dict] = []
    cached_mu: dict[str, float] = {}
    cvar_95_daily: float | None = None
    mu_source = "historical"

    try:
        qr = load_latest_quant_result(user_id)
        if qr:
            regime = qr.get("regime")
            regime_probs = qr.get("regime_probs") or {}
            corr_alerts = qr.get("correlation_alerts") or []
            if isinstance(qr.get("optimal_weights"), dict):
                # Use quant's implied mu via CAPM from optimal weights
                pass
            if qr.get("cvar_95") is not None:
                cvar_95_daily = float(qr["cvar_95"])
    except Exception:
        pass

    # ── BL views → adjust mu ─────────────────────────────────────────────────
    try:
        bl_views = load_user_bl_views(user_id)
        if bl_views:
            mu_bl = _compute_bl_mu(returns_df, bl_views, risk_aversion=bl_risk_aversion, tau=bl_tau)
            mu_hist = mu_bl
            mu_source = "black_litterman"
    except Exception:
        pass

    # ── Regime-probability weighted mu scaling ────────────────────────────────
    # Blend regime-specific mu scalars weighted by regime_probs
    if regime_probs:
        total_p = sum(regime_probs.values())
        if total_p > 0:
            blended_scale = sum(
                (p / total_p) * _REGIME_MU_SCALE.get(r, 1.0)
                for r, p in regime_probs.items()
            )
        else:
            blended_scale = _REGIME_MU_SCALE.get(regime or "bull_weak", 1.0)
    else:
        blended_scale = _REGIME_MU_SCALE.get(regime or "bull_weak", 1.0)

    mu = mu_hist * blended_scale

    # ── Correlation penalty: reduce mu for flagged pairs ──────────────────────
    corr_penalised: set[str] = set()
    for alert in corr_alerts:
        ta = alert.get("ticker_a", "")
        tb = alert.get("ticker_b", "")
        # Penalise the ticker that is already more overweight
        ow_a = current_weights.get(ta, 0)
        ow_b = current_weights.get(tb, 0)
        penalise = ta if ow_a >= ow_b else tb
        if penalise in tickers_avail:
            idx = tickers_avail.index(penalise)
            mu[idx] *= 0.80
            corr_penalised.add(penalise)

    # ── Net alpha filter: zero-out tickers that won't earn after TC ───────────
    tc_params = TC_MODELS.get(tc_model, TC_MODELS["broker"])
    ann_tc_drag = (tc_params["fixed"] / max(amount / n, 1) + tc_params["pct"]) * 2  # round-trip
    no_edge: set[str] = set()
    for i, t in enumerate(tickers_avail):
        net_alpha = mu[i] - ann_tc_drag
        if net_alpha < 0:
            mu[i] = max(mu[i], 0.0)  # floor at 0 but don't invert (still buy underweight)
            no_edge.add(t)

    # ── Liquidity caps: limit single trade to 5% of 30d ADV ──────────────────
    liquidity_caps: dict[str, float] = {}  # ticker → max fraction of capital
    for t, df in hist.items():
        if t not in tickers_avail:
            continue
        try:
            if not df.empty and "Volume" in df.columns and "Close" in df.columns:
                adv = float((df["Close"].iloc[-30:] * df["Volume"].iloc[-30:]).mean())
                max_trade = adv * 0.05  # 5% of ADV
                liquidity_caps[t] = min(max_trade / amount, 1.0) if amount > 0 else 1.0
        except Exception:
            pass

    # ── Current weights adjusted for buy-only constraint ─────────────────────
    # We only want to buy underweight tickers (or all if aggressive).
    # For conservative/base: floor at 0 for already-overweight tickers.
    total_new = total_value + amount

    # Build per-ticker upper bounds for the capital allocation:
    # w_alloc[i] = fraction of *capital* going to ticker i
    # constraint: current_value[i] + w_alloc[i]*amount <= cap_i * total_new
    bounds_alloc: list[tuple[float, float]] = []
    for t in tickers_avail:
        lo_w, hi_w = per_ticker_bounds.get(t, (0.0, max_single))
        # max additional allocation respecting weight cap on total portfolio
        cur_v = current_values.get(t, 0.0)
        max_target_v = hi_w * total_new
        max_buy = max(0.0, max_target_v - cur_v)
        # Cap 1: portfolio-weight constraint (how much room left before hitting hi_w)
        frac_from_portfolio = min(max_buy / amount, 1.0) if amount > 0 else 0.0
        # Cap 2: Motor 1 cap applied directly to capital allocation fraction.
        # Prevents any single ticker from receiving more than hi_w of new capital
        # (e.g. max_single=0.40 → no ticker gets >40% of the deployment).
        max_frac = min(frac_from_portfolio, hi_w)
        # Apply liquidity cap
        if t in liquidity_caps:
            max_frac = min(max_frac, liquidity_caps[t])
        # Floor: 0 (buy-only — never negative)
        bounds_alloc.append((0.0, max(0.0, max_frac)))

    # ── CVaR limit ────────────────────────────────────────────────────────────
    cvar_limit = cvar_95_daily
    if cvar_limit is not None and regime and regime in _REGIME_CVAR_MULT:
        cvar_limit *= _REGIME_CVAR_MULT[regime].get(profile_key, 1.0)
    if cvar_limit is None:
        cvar_limit = _CVAR_LIMIT_DEFAULT[profile_key]

    # ── Objective: maximise mu @ w_alloc (fraction of capital) ───────────────
    def neg_ret(w):
        return -float(mu @ w)

    constraints_list = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    # Combination constraints adapted to capital-allocation fractions
    for rule in combination_constraints:
        rule_tickers = rule.get("tickers", [])
        raw_min = rule.get("min")
        raw_max = rule.get("max")
        indices = [i for i, t in enumerate(tickers_avail) if t in rule_tickers]
        if not indices:
            continue
        # Scale Motor2 constraints: target weight in total portfolio
        # w_port[i] ≈ (cur_v[i] + w_alloc[i]*amount) / total_new
        if raw_min is not None:
            m = float(raw_min)
            constraints_list.append({
                "type": "ineq",
                "fun": lambda w, idx=indices, mn=m: sum(
                    (current_values.get(tickers_avail[i], 0) + w[i] * amount) / total_new
                    for i in idx
                ) - mn,
            })
        if raw_max is not None:
            m = float(raw_max)
            constraints_list.append({
                "type": "ineq",
                "fun": lambda w, idx=indices, mx=m: mx - sum(
                    (current_values.get(tickers_avail[i], 0) + w[i] * amount) / total_new
                    for i in idx
                ),
            })

    # CVaR on the *resulting portfolio* weights (post-deployment)
    def _cvar_total(w):
        # portfolio weights after deployment
        port_w = np.array([
            (current_values.get(t, 0) + w[i] * amount) / total_new
            for i, t in enumerate(tickers_avail)
        ])
        port_w = np.clip(port_w, 0, None)
        s = port_w.sum()
        if s > 0:
            port_w /= s
        mu_daily = mu / 252
        cov_daily = cov / 252
        port_ret = mu_daily @ port_w
        port_vol = float(np.sqrt(max(port_w @ cov_daily @ port_w, 1e-12)))
        cvar = -port_ret + 1.645 * port_vol
        return float(cvar_limit - cvar)

    constraints_list.append({"type": "ineq", "fun": _cvar_total})

    # Initial guess: proportional to mu (only positive mu)
    mu_pos = np.maximum(mu, 0.0)
    w0 = mu_pos / mu_pos.sum() if mu_pos.sum() > 0 else np.ones(n) / n
    w0 = np.clip(w0, [b[0] for b in bounds_alloc], [b[1] for b in bounds_alloc])
    w0 /= w0.sum() if w0.sum() > 0 else 1.0

    try:
        res = minimize(neg_ret, w0, method="SLSQP",
                       bounds=bounds_alloc, constraints=constraints_list,
                       options={"ftol": 1e-10, "maxiter": 1000})
        w_opt = np.clip(res.x, 0, None)
        if w_opt.sum() > 0:
            w_opt /= w_opt.sum()
        else:
            w_opt = w0
    except Exception:
        w_opt = w0

    # ── Build output ──────────────────────────────────────────────────────────
    tc_fixed = tc_params["fixed"]
    tc_pct = tc_params["pct"]
    corr_flagged_pairs = [
        (a.get("ticker_a", ""), a.get("ticker_b", ""))
        for a in corr_alerts
    ]

    allocations = []
    for i, t in enumerate(tickers_avail):
        frac = float(w_opt[i])
        amt = round(frac * amount, 2)
        if amt < 0.01:
            continue
        tc_cost = round(tc_fixed + amt * tc_pct, 2)
        net_amt = round(amt - tc_cost, 2)

        # Signals for this ticker
        signals: list[str] = []
        if t not in no_edge:
            signals.append("net_alpha_positive")
        cw = current_weights.get(t, 0.0)
        # target weight in total portfolio
        target_w = (current_values.get(t, 0.0) + amt) / total_new
        if cw < target_w:
            signals.append("underweight")
        if t in corr_penalised:
            signals.append("corr_penalty_applied")
        if t in liquidity_caps and liquidity_caps[t] < 1.0:
            signals.append("liquidity_capped")
        if mu[i] > mu_hist.mean() * blended_scale * 1.1:
            signals.append("high_expected_return")

        allocations.append({
            "ticker": t,
            "amount": amt,
            "pct_of_capital": round(frac * 100, 2),
            "tc_cost": tc_cost,
            "net_amount": net_amt,
            "current_weight_pct": round(cw * 100, 2),
            "target_weight_pct": round(target_w * 100, 2),
            "expected_return_pct": round(float(mu[i]) * 100, 2),
            "signals": signals,
        })

    allocations.sort(key=lambda x: x["amount"], reverse=True)

    return {
        "allocations": allocations,
        "regime": regime,
        "regime_probs": regime_probs,
        "mu_source": mu_source,
        "regime_mu_scale": round(blended_scale, 3),
        "cvar_limit_daily": round(cvar_limit, 6),
        "n_corr_alerts": len(corr_alerts),
        "n_no_edge": len(no_edge),
        "total_tc": round(sum(a["tc_cost"] for a in allocations), 2),
        "net_deployed": round(sum(a["net_amount"] for a in allocations), 2),
    }
