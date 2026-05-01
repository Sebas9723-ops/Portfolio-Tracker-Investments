"""
Contribution plan generator.
Takes a QuantResult + available cash → per-ticker buy allocation net of slippage.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.quant_engine import QuantResult


@dataclass
class AllocationRow:
    ticker: str
    current_weight: float   # 0-1
    target_weight: float    # 0-1
    gap: float              # target - current (0-1); always > 0 in output
    gross_amount: float     # cash allocated before slippage
    slippage_cost: float    # estimated slippage in base currency
    net_amount: float       # gross_amount - slippage_cost


@dataclass
class ContributionPlan:
    allocations: list[AllocationRow] = field(default_factory=list)
    total_cash: float = 0.0
    total_slippage: float = 0.0
    net_invested: float = 0.0


def generate_contribution_plan(
    result: QuantResult,
    current_portfolio: dict,
    available_cash: float,
    slippage_estimates: dict,
    profile: str = "base",
) -> ContributionPlan:
    """
    Build a buy-only contribution plan from QuantResult optimal weights.

    Parameters
    ----------
    result : QuantResult
        Output of QuantEngine.run_full_optimization().
    current_portfolio : dict
        {ticker: {"value_base": float, ...}}  — current holdings in base currency.
    available_cash : float
        Cash to deploy (in base currency).
    slippage_estimates : dict
        {ticker: {"total": float, ...}}  — from QuantEngine.estimate_slippage().
        The "total" entry is a fraction of trade value (e.g., 0.002 = 0.2%).

    Returns
    -------
    ContributionPlan
    """
    if available_cash <= 0:
        return ContributionPlan(total_cash=0.0)

    tickers = list(result.optimal_weights.keys())
    target_weights = result.optimal_weights  # {ticker: float 0-1}

    # Current portfolio values and weights
    total_current = sum(
        d.get("value_base", 0.0) for d in current_portfolio.values()
    )
    total_after = total_current + available_cash

    current_weights: dict[str, float] = {}
    for t in tickers:
        v = current_portfolio.get(t, {}).get("value_base", 0.0)
        current_weights[t] = v / total_current if total_current > 0 else 0.0

    # Compute gap for each ticker (in new weight space after contribution)
    # gap = target_weight_new - current_value/total_after
    gaps: dict[str, float] = {}
    for t in tickers:
        current_val = current_portfolio.get(t, {}).get("value_base", 0.0)
        # Effective current weight in the post-contribution portfolio
        effective_current_w = current_val / total_after if total_after > 0 else 0.0
        target_w = float(target_weights.get(t, 0.0))
        gap = target_w - effective_current_w
        if gap > 0:
            gaps[t] = gap

    if not gaps:
        return ContributionPlan(total_cash=available_cash)

    # ── Profile-aware allocation priority ────────────────────────────────────
    # aggressive: weight cash toward highest expected-return tickers that also
    #             have a gap — maximises return per dollar deployed.
    # conservative/base: pure gap-proportional (risk already embedded in CVXPY
    #                    target weights, so largest gap = most underweight asset).
    mu_vec: dict[str, float] = result.mu_vector  # annualised, per-ticker

    if profile == "aggressive" and mu_vec:
        # Score = gap × max(0, mu)  — only reward positive-return tickers;
        # if all mu ≤ 0 fall back to pure gap.
        scores: dict[str, float] = {
            t: gaps[t] * max(0.0, mu_vec.get(t, 0.0)) for t in gaps
        }
        total_score = sum(scores.values())
        if total_score > 1e-8:
            # Sort by return-weighted gap descending
            sorted_tickers = sorted(gaps.keys(), key=lambda t: scores[t], reverse=True)
            raw_allocations: dict[str, float] = {
                t: (scores[t] / total_score) * available_cash for t in sorted_tickers
            }
        else:
            # All expected returns ≤ 0 — fall back to gap-proportional
            sorted_tickers = sorted(gaps.keys(), key=lambda t: gaps[t], reverse=True)
            total_gap = sum(gaps.values())
            raw_allocations = {
                t: (gaps[t] / total_gap) * available_cash for t in sorted_tickers
            }
    else:
        # Base / conservative: gap-proportional
        sorted_tickers = sorted(gaps.keys(), key=lambda t: gaps[t], reverse=True)
        total_gap = sum(gaps.values())
        raw_allocations = {
            t: (gaps[t] / total_gap if total_gap > 0 else 1.0 / len(gaps)) * available_cash
            for t in sorted_tickers
        }

    # Subtract slippage per ticker
    rows: list[AllocationRow] = []
    total_slippage = 0.0
    remainder = available_cash

    for t in sorted_tickers:
        gross = round(raw_allocations[t], 2)
        slip_rate = slippage_estimates.get(t, {}).get("total", 0.001)
        slip_cost = round(gross * slip_rate, 2)
        net = round(max(0.0, gross - slip_cost), 2)

        total_slippage += slip_cost
        remainder -= gross

        rows.append(AllocationRow(
            ticker=t,
            current_weight=round(current_weights.get(t, 0.0), 6),
            target_weight=round(float(target_weights.get(t, 0.0)), 6),
            gap=round(gaps[t], 6),
            gross_amount=gross,
            slippage_cost=slip_cost,
            net_amount=net,
        ))

    # Assign remainder (rounding drift) to the highest-priority ticker
    if rows and abs(remainder) > 0.01:
        rows[0] = AllocationRow(
            ticker=rows[0].ticker,
            current_weight=rows[0].current_weight,
            target_weight=rows[0].target_weight,
            gap=rows[0].gap,
            gross_amount=round(rows[0].gross_amount + remainder, 2),
            slippage_cost=rows[0].slippage_cost,
            net_amount=round(max(0.0, rows[0].net_amount + remainder), 2),
        )

    # Ensure no negative amounts
    rows = [r for r in rows if r.net_amount > 0]

    net_invested = round(sum(r.net_amount for r in rows), 2)
    total_slippage = round(total_slippage, 2)

    return ContributionPlan(
        allocations=rows,
        total_cash=round(available_cash, 2),
        total_slippage=total_slippage,
        net_invested=net_invested,
    )
