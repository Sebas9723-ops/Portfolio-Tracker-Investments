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

// ── Quant Analytics V2 types ──────────────────────────────────────────────────

export interface RebalancingBandTrade {
  ticker: string;
  current_w_pct: number;
  target_w_pct: number;
  drift_w_pct: number;
  gross_delta: number;
  filtered: boolean;
  action: string;
  est_tc: number;
  priority: number;
  net_delta: number;
  executable_w_pct: number;
}

export interface RebalancingBands {
  trades: RebalancingBandTrade[];
  turnover: number;
  n_executable: number;
  suppressed: string[];
}

export interface NetAlphaRow {
  ticker: string;
  expected_return: number;
  ann_tc_drag: number;
  net_alpha: number;
  has_edge: boolean;
  trade: boolean;
}

export interface AfterTaxDrag {
  after_tax_return: number;
  tax_drag: number;
  total_tax_liability: number;
  positions: {
    ticker: string;
    shares: number;
    cost_basis: number;
    current_price: number;
    gain: number;
    holding_days: number;
    rate: number;
    tax_liability: number;
  }[];
}

export interface LiquidityRow {
  ticker: string;
  position_value: number;
  adv_30d: number;
  daily_capacity: number;
  days_to_liquidate: number | null;
  liquidity_score: number;
  passes_min_notional: boolean;
  flag: "OK" | "REVIEW";
}

export interface ModelAgreement {
  agreement_score: number;
  consensus_weights: Record<string, number>;
  weight_std_by_ticker: Record<string, number>;
  model_correlations: Record<string, number>;
  high_conflict_tickers: string[];
  complexity_penalties: Record<string, number>;
  n_models: number;
}

export interface ReturnBandRow {
  ticker: string;
  return_low: number;
  return_median: number;
  return_high: number;
  band_width: number;
  sharpe_low: number;
  sharpe_median: number;
  sharpe_high: number;
  reliable: boolean;
}

export interface TrackingErrorBudget {
  total_te: number;
  te_budget: number;
  budget_used_pct: number;
  within_budget: boolean;
  per_asset: Record<string, { te_contribution: number; te_share_pct: number }>;
}

export interface WalkForwardFold {
  fold: number;
  start: string;
  end: string;
  ann_return: number;
  volatility: number;
  sharpe: number;
  alpha: number;
}

export interface WalkForward {
  folds: WalkForwardFold[];
  oos_mean_sharpe: number;
  oos_sharpe_std: number;
  oos_mean_alpha: number;
  consistent_edge: boolean;
  n_positive_folds: number;
}

export interface QuantRegime {
  current_regime: string;
  current_vol: number;
  regime_probabilities: Record<string, number>;
  regime_confidence: number;
  recent_flip: boolean;
  strategic: { equity_tilt: number; bond_tilt: number };
  tactical: { active: boolean; confidence: number };
  execution: { hold: boolean; reason: string | null };
}

export interface DynamicCaps {
  caps: Record<string, number>;
  top_heavy_tickers: string[];
  top_n_concentration: number;
  mean_pairwise_corr: Record<string, number>;
}

export interface DrawdownHorizon {
  expected_max_dd: number;
  worst_dd_p95: number;
  median_recovery_months: number;
  p90_recovery_months: number;
  prob_drawdown_gt_10pct: number;
  prob_drawdown_gt_20pct: number;
}

export interface ModelDriftAsset {
  mu_short: number;
  mu_long: number;
  vol_short: number;
  vol_long: number;
  sharpe_short: number;
  sharpe_long: number;
  drift_score: number;
  alert: boolean;
}

export interface ModelDrift {
  per_asset: Record<string, ModelDriftAsset>;
  mean_drift_score: number;
  n_alerts: number;
  engine_healthy: boolean;
  snapshot_ts: string;
}

export interface NaiveBenchmarkRow {
  model: string;
  ann_return: number;
  volatility: number;
  sharpe: number;
  cum_return: number;
  max_dd: number;
}

export interface FactorRiskAsset {
  weight: number;
  vol_contribution: number;
  vol_contribution_pct: number;
}

export interface FactorRisk {
  portfolio_vol: number;
  per_asset: Record<string, FactorRiskAsset>;
  factor_decomposition: Record<string, unknown>;
}

export interface BLExplanationRow {
  ticker: string;
  equilibrium_return: number;
  posterior_return: number;
  view_pull: number;
  has_view: boolean;
  view_return: number | null;
  view_confidence: number | null;
  dominant_source: string;
}

export interface QuantAnalyticsV2 {
  rebalancing_bands: RebalancingBands | null;
  net_alpha: NetAlphaRow[] | null;
  after_tax_drag: AfterTaxDrag | null;
  liquidity: LiquidityRow[] | null;
  model_agreement: ModelAgreement | null;
  return_bands: ReturnBandRow[] | null;
  bl_explanation: BLExplanationRow[] | null;
  tracking_error_budget: TrackingErrorBudget | null;
  walk_forward: WalkForward | null;
  regime: QuantRegime | null;
  dynamic_caps: DynamicCaps | null;
  drawdown_profile: Record<string, DrawdownHorizon> | null;
  model_drift: ModelDrift | null;
  naive_benchmarks: NaiveBenchmarkRow[] | null;
  factor_risk: FactorRisk | null;
}

// ── Main response ─────────────────────────────────────────────────────────────

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
  quant_analytics_v2?: QuantAnalyticsV2 | null;
}

export const fetchContributionPlan = (params: {
  available_cash: number;
  profile: string;
  time_horizon: string;
}) =>
  apiClient
    .post<ContributionPlanResponse>("/api/contribution-plan", params, { timeout: 300_000 })
    .then((r) => r.data);
