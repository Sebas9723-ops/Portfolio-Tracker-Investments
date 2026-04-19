import { apiClient } from "./client";

export interface AllocationRow {
  ticker: string;
  current_weight: number;
  target_weight: number;
  gap: number;
  gross_amount: number;
  slippage_cost: number;
  net_amount: number;
}

export interface ContributionPlan {
  allocations: AllocationRow[];
  total_cash: number;
  total_slippage: number;
  net_invested: number;
}

export interface QuantResultSummary {
  optimal_weights: Record<string, number>;
  expected_return: number;
  expected_volatility: number;
  expected_sharpe: number;
  cvar_95: number;
}

export interface CorrelationAlert {
  ticker_a: string;
  ticker_b: string;
  current_corr: number;
  historical_corr: number;
  deviation: number;
}

export interface SlippageEntry {
  spread_cost: number;
  volume_impact: number;
  total: number;
}

export interface ContributionPlanResponse {
  contribution_plan: ContributionPlan;
  quant_result: QuantResultSummary;
  regime: "bull" | "bear";
  regime_confidence: number;
  correlation_alerts: CorrelationAlert[];
  slippage_breakdown: Record<string, SlippageEntry>;
  optimization_timestamp: string;
  profile: string;
}

export const fetchContributionPlan = (params: {
  available_cash: number;
  profile: string;
}) =>
  apiClient
    .post<ContributionPlanResponse>("/api/contribution-plan", params)
    .then((r) => r.data);
