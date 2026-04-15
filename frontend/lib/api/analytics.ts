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

export const fetchBlackLitterman = (body: {
  views: Record<string, number>;
  tau?: number;
  risk_aversion?: number;
  max_single_asset?: number;
  period?: string;
}) =>
  apiClient.post<{ weights: Record<string, number> }>("/api/optimization/black-litterman", body).then((r) => r.data);
