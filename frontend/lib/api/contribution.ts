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

export type RegimeLabel = "bull_strong" | "bull_weak" | "bear_mild" | "crisis";

export interface RegimeProbs {
  bull_strong: number;
  bull_weak: number;
  bear_mild: number;
  crisis: number;
}

export interface MLDiagnostics {
  garch_available: boolean;
  ff5_available: boolean;
  regime_available: boolean;
  xgb_available: boolean;
  garch_ms?: number;
  dcc_ms?: number;
  ff5_ms?: number;
  regime_ms?: number;
  xgb_ms?: number;
  xgb_views_generated?: number;
  garch_vols?: Record<string, number>;
}

export interface ContributionPlanResponse {
  contribution_plan: ContributionPlan;
  quant_result: QuantResultSummary;
  regime: RegimeLabel;
  regime_confidence: number;
  regime_probs: RegimeProbs;
  ml_diagnostics: MLDiagnostics;
  correlation_alerts: CorrelationAlert[];
  slippage_breakdown: Record<string, SlippageEntry>;
  optimization_timestamp: string;
  profile: string;
  time_horizon: string;
}

export const fetchContributionPlan = (params: {
  available_cash: number;
  profile: string;
  time_horizon: string;
}) =>
  apiClient
    .post<ContributionPlanResponse>("/api/contribution-plan", params, { timeout: 300_000 })
    .then((r) => r.data);
