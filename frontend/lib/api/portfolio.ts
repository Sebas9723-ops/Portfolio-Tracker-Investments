import { apiClient } from "./client";
import type { PortfolioSummary, Position, Snapshot } from "@/lib/types";

export const fetchPortfolio = () =>
  apiClient.get<PortfolioSummary>("/api/portfolio").then((r) => r.data);

export const fetchPositions = () =>
  apiClient.get<Position[]>("/api/portfolio/positions").then((r) => r.data);

export const fetchSnapshots = () =>
  apiClient.get<Snapshot[]>("/api/portfolio/snapshots").then((r) => r.data);

export const saveSnapshot = (notes?: string) =>
  apiClient.post("/api/portfolio/snapshots", { notes }).then((r) => r.data);

export const fetchPortfolioHistory = (start = "2026-03-01") =>
  apiClient
    .get<{ date: string; value: number; invested?: number }[]>("/api/portfolio/history", { params: { start } })
    .then((r) => r.data);

export const upsertPosition = (data: Partial<Position> & { ticker: string }) =>
  apiClient.post("/api/portfolio/positions", data).then((r) => r.data);

export const updatePosition = (ticker: string, data: { shares?: number; avg_cost_native?: number; name?: string }) =>
  apiClient.put(`/api/portfolio/positions/${ticker}`, data).then((r) => r.data);

export const deletePosition = (ticker: string) =>
  apiClient.delete(`/api/portfolio/positions/${ticker}`);

export const fetchRealizedPnl = () =>
  apiClient.get<{ ticker: string; realized_pnl: number; trades: number }[]>("/api/portfolio/realized-pnl").then((r) => r.data);

export const fetchDividendForecast = () =>
  apiClient
    .get<{
      positions: { ticker: string; name: string; value_base: number; dividend_yield: number; annual_income: number }[];
      total_annual: number;
      monthly: number;
      base_currency: string;
    }>("/api/portfolio/dividend-forecast")
    .then((r) => r.data);

export const exportPositionsCsv = () =>
  apiClient.get("/api/portfolio/export/positions.csv", { responseType: "blob" }).then((r) => r.data);

export const saveCapitalSnapshot = () =>
  apiClient.post<{ snapshot_date: string; invested_base: number }>("/api/portfolio/capital-snapshot").then((r) => r.data);

export const backfillCapitalSnapshots = () =>
  apiClient.post<{ created: number; dates: string[] }>("/api/portfolio/capital-snapshot/backfill").then((r) => r.data);
