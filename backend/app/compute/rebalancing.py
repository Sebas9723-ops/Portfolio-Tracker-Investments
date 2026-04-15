"""
Rebalancing trade suggestions + transaction cost estimates.
Port of build_rebalancing_table from app_core.py.
"""
from app.models.analytics import RebalancingRow

TC_MODELS = {
    "broker": {"fixed": 1.0, "pct": 0.001},
    "etoro": {"fixed": 0.0, "pct": 0.002},
    "degiro": {"fixed": 0.5, "pct": 0.0005},
    "ib": {"fixed": 0.5, "pct": 0.0005},
}


def build_rebalancing_table(
    portfolio_rows: list[dict],
    target_weights: dict[str, float],
    total_value: float,
    contribution: float = 0.0,
    tc_model: str = "broker",
    threshold: float = 0.05,
) -> list[RebalancingRow]:
    """
    portfolio_rows: list of PortfolioRow dicts
    target_weights: {ticker: weight_fraction}
    contribution: cash to deploy (positive) or withdraw (negative)
    """
    total_with_contrib = total_value + contribution
    rows = []

    for row in portfolio_rows:
        ticker = row["ticker"]
        current_value = row.get("value_base", 0.0)
        current_w = current_value / total_value if total_value > 0 else 0
        target_w = target_weights.get(ticker, current_w)
        drift = current_w - target_w

        target_value = target_w * total_with_contrib
        trade_value = target_value - current_value
        direction = "BUY" if trade_value > 0 else ("SELL" if trade_value < 0 else "HOLD")

        if abs(drift) < threshold / 10:  # skip trivial trades
            direction = "HOLD"
            trade_value = 0.0

        tc = estimate_tc(abs(trade_value), tc_model)

        rows.append(RebalancingRow(
            ticker=ticker,
            name=row.get("name", ticker),
            current_weight=round(current_w * 100, 2),
            target_weight=round(target_w * 100, 2),
            drift=round(drift * 100, 2),
            value_base=round(current_value, 2),
            trade_value=round(trade_value, 2),
            trade_direction=direction,
            estimated_tc=round(tc, 2),
        ))

    return sorted(rows, key=lambda r: abs(r.drift), reverse=True)


def estimate_tc(trade_value: float, tc_model: str = "broker") -> float:
    model = TC_MODELS.get(tc_model, TC_MODELS["broker"])
    return model["fixed"] + trade_value * model["pct"]


def compute_target_weights_from_drift(
    portfolio_rows: list[dict],
    threshold: float = 0.05,
) -> dict[str, float]:
    """
    Returns the equal-weight target. In practice, the user can set custom targets
    via user_settings. This is the default drift-based fallback.
    """
    n = len(portfolio_rows)
    return {r["ticker"]: round(1 / n, 4) for r in portfolio_rows}
