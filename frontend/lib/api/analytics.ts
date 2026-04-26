import { apiClient } from "./client";
import type { AnalyticsResponse, OptimizationResult, RebalancingRow, VaRResult, StressTestRow } from "@/lib/types";

export const fetchAnalytics = (period = "2y", benchmark = "VOO") =>
  apiClient
    .get<AnalyticsResponse>("/api/analytics/performance", { params: { period, benchmark } })
    .then((r) => r.data);

export const fetchFrontier = (body = {}) =>
  apiClient.post<OptimizationResult>("/api/optimization/frontier", body).then((r) => r.data);

export const fetchMaxSharpe = (body = {}) =>
  apiClient.post<{ weights: Record<string, number> }>("/api/optimization/max-sharpe", body).then((r) => r.data);

export const fetchRebalancing = (params?: { contribution?: number; tc_model?: string }) =>
  apiClient.get<RebalancingRow[]>("/api/rebalancing/suggestions", { params }).then((r) => r.data);

export const fetchVaR = (confidence = 0.95, period = "2y") =>
  apiClient.get<VaRResult>("/api/risk/var", { params: { confidence, period } }).then((r) => r.data);

export const fetchStressTest = () =>
  apiClient.get<StressTestRow[]>("/api/risk/stress-test").then((r) => r.data);

export const fetchCorrelation = (period = "1y") =>
  apiClient.get("/api/risk/correlation", { params: { period } }).then((r) => r.data);

export const fetchRiskBudget = (period = "1y") =>
  apiClient.get("/api/risk/budget", { params: { period } }).then((r) => r.data);

export const fetchFxExposure = () =>
  apiClient.get<Record<string, number>>("/api/risk/fx-exposure").then((r) => r.data);

export const fetchRollingMetrics = (window = 63, period = "2y") =>
  apiClient.get("/api/risk/rolling", { params: { window, period } }).then((r) => r.data);

export const fetchExtendedAnalytics = (period = "2y") =>
  apiClient
    .get<{
      extended_ratios: Record<string, number | null>;
      fama_french: Record<string, number>;
      per_ticker_sharpe: Record<string, { ann_return: number; ann_vol: number; sharpe: number }>;
      benchmark_ticker: string;
    }>("/api/analytics/extended", { params: { period } })
    .then((r) => r.data);

export const fetchVolRegime = (period = "2y", window = 21) =>
  apiClient
    .get<{
      series: { date: string; vol: number; regime: "low" | "medium" | "high" }[];
      low_threshold: number;
      high_threshold: number;
    }>("/api/analytics/vol-regime", { params: { period, window } })
    .then((r) => r.data);

export const fetchRequiredForMaxSharpe = (params?: { period?: string; max_single_asset?: number }) =>
  apiClient
    .get<{
      required_contribution: number;
      max_sharpe_weights: Record<string, number>;
      buy_plan: Record<string, { buy_value: number; buy_pct: number; target_weight: number; current_weight: number }>;
      total_value: number;
      total_after: number;
      profile: string;
      profile_metrics?: { ann_return: number; ann_vol: number; sharpe: number; max_drawdown: number };
    }>("/api/rebalancing/required-for-max-sharpe", { params })
    .then((r) => r.data);

export const fetchPortfolioBreakdown = () =>
  apiClient
    .get<{ sectors: Record<string, number>; regions: Record<string, number> }>("/api/portfolio/breakdown")
    .then((r) => r.data);

export const backtestWeights = (weights: Record<string, number>, period = "1y") =>
  apiClient
    .post<{ optimal_series: { date: string; value: number }[]; current_series: { date: string; value: number }[] }>(
      "/api/analytics/backtest-weights",
      { weights, period }
    )
    .then((r) => r.data);

export const fetchQuantAdvanced = async (body: {
  period?: string;
  benchmark_ticker?: string;
  n_bootstrap?: number;
  n_dd_sims?: number;
  horizons_years?: number[];
  band_tolerance?: number;
  te_budget?: number;
  bl_views?: Record<string, { return: number; confidence: number }>;
} = {}): Promise<import("./contribution").QuantAnalyticsV2> => {
  // Start background job
  const { data: job } = await apiClient.post<{ job_id: string; status: string }>(
    "/api/analytics/quant-advanced",
    body,
  );

  // Poll every 3 s for up to 3 minutes
  const deadline = Date.now() + 3 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 3000));
    const { data: poll } = await apiClient.get<{
      status: string;
      result?: import("./contribution").QuantAnalyticsV2;
      detail?: string;
    }>(`/api/analytics/quant-advanced/result/${job.job_id}`);

    if (poll.status === "done") return poll.result!;
    if (poll.status === "error") throw new Error(poll.detail ?? "Quant engine error");
  }
  throw new Error("Quant engine timed out after 3 minutes");
};

export const fetchEquityCurve = (period = "1y") =>
  apiClient
    .get<{
      series: { date: string; value: number; invested: number | null; pnl: number | null; pnl_pct: number | null }[];
      base_currency: string;
    }>("/api/analytics/equity-curve", { params: { period } })
    .then((r) => r.data);

export const fetchBlackLitterman = (body: {
  views: Record<string, number>;
  tau?: number;
  risk_aversion?: number;
  max_single_asset?: number;
  period?: string;
  profile?: string;
}) =>
  apiClient.post<{ weights: Record<string, number> }>("/api/optimization/black-litterman", body).then((r) => r.data);
