import type { PortfolioSummary, PerformanceMetrics, UserSettings, RebalancingRow } from "@/lib/types";

export function buildSystemPrompt(params: {
  portfolio: PortfolioSummary | null;
  metrics: PerformanceMetrics | null;
  settings: UserSettings;
  rebalancing: RebalancingRow[] | null;
  costBasisUsd: number | null;
}): string {
  const { portfolio, metrics, settings, rebalancing, costBasisUsd } = params;
  const ccy = portfolio?.base_currency ?? "USD";

  const positionsBlock = portfolio?.rows
    .sort((a, b) => b.value_base - a.value_base)
    .map((r) => {
      const rb = rebalancing?.find((x) => x.ticker === r.ticker);
      const target = rb ? ` | target ${rb.target_weight.toFixed(1)}% | drift ${rb.drift > 0 ? "+" : ""}${rb.drift.toFixed(1)}%` : "";
      const pnl = r.unrealized_pnl_pct != null ? ` | P&L ${r.unrealized_pnl_pct > 0 ? "+" : ""}${r.unrealized_pnl_pct.toFixed(1)}%` : "";
      return `  - ${r.ticker} (${r.name}): ${r.weight.toFixed(1)}% weight${target}${pnl}`;
    })
    .join("\n") ?? "  (no positions)";

  const totalValue = portfolio?.total_value_base ?? 0;
  const basis = costBasisUsd ?? portfolio?.total_invested_base ?? 0;
  const totalPnl = basis > 0 ? ((totalValue - basis) / basis) * 100 : 0;

  const metricsBlock = metrics
    ? [
        metrics.annualized_return != null && `  - Annual return: ${metrics.annualized_return.toFixed(1)}%`,
        metrics.sharpe != null && `  - Sharpe: ${metrics.sharpe.toFixed(2)}`,
        metrics.sortino != null && `  - Sortino: ${metrics.sortino.toFixed(2)}`,
        metrics.max_drawdown != null && `  - Max drawdown: ${metrics.max_drawdown.toFixed(1)}%`,
        metrics.annualized_vol != null && `  - Volatility: ${metrics.annualized_vol.toFixed(1)}%`,
        metrics.alpha != null && `  - Alpha vs ${metrics.benchmark_ticker}: +${metrics.alpha.toFixed(1)}%`,
        metrics.beta != null && `  - Beta: ${metrics.beta.toFixed(2)}`,
      ]
        .filter(Boolean)
        .join("\n")
    : "  (no analytics data yet)";

  const constraintsBlock = Object.entries(settings.ticker_weight_rules?.aggressive ?? {})
    .map(([t, fc]) => `  - ${t}: floor ${(fc.floor * 100).toFixed(0)}% / cap ${(fc.cap * 100).toFixed(0)}%`)
    .join("\n") || "  (none configured)";

  return `You are a personal portfolio advisor AI. You know everything about the user's portfolio and investment strategy. Respond in the same language as the user's message (Spanish or English). Be concise, direct, and actionable — no generic disclaimers.

## USER PROFILE
- Name: Sebastian (Colombia, UTC-5, age 25)
- Goal: $1,000,000 by age 49 (24 years)
- Strategy: ultra-aggressive, 15+ year horizon, never sell — only buy
- Monthly contribution: $250/month + $500 every 6 months (approx $333/month avg)
- Rule on dips: when VOO drops >5% in a month, double contributions to VOO and QQQM
- Current cost basis (actual USD deployed): ${costBasisUsd != null ? `$${costBasisUsd.toFixed(0)}` : "not set"}

## PORTFOLIO (${ccy})
- Total value: $${totalValue.toFixed(0)} ${ccy}
- Total return: ${totalPnl > 0 ? "+" : ""}${totalPnl.toFixed(1)}% since inception
- Daily change: ${portfolio?.total_day_change_base != null ? `${portfolio.total_day_change_base > 0 ? "+" : ""}$${portfolio.total_day_change_base.toFixed(0)}` : "N/A"}

Positions (weight | target | drift | P&L):
${positionsBlock}

## ANALYTICS (2Y)
${metricsBlock}

## OPTIMIZATION CONSTRAINTS (Aggressive profile)
${constraintsBlock}
- Max single asset: ${(settings.max_single_asset * 100).toFixed(0)}%
- Min bonds: ${(settings.min_bonds * 100).toFixed(0)}%
- Min gold: ${(settings.min_gold * 100).toFixed(0)}%

## RESPONSE RULES
- Always use the real numbers above — never say "I don't have access to your data"
- For buy recommendations, give specific USD amounts
- For drift issues, explain why it matters for the $1M goal
- Use bullet points and bold for key numbers
- Max 250 words unless asked for detail`;
}
