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

export const downloadReport = (period = "1y") =>
  apiClient.get("/api/portfolio/report.pdf", { params: { period }, responseType: "blob" }).then((r) => r.data);

export const importPositionsCsv = (file: File, mode: "upsert" | "skip" = "upsert") => {
  const fd = new FormData();
  fd.append("file", file);
  return apiClient
    .post<{ imported: number; skipped: number; errors: { row: number; ticker?: string; error: string }[]; total_rows: number }>(
      `/api/portfolio/import/positions?mode=${mode}`,
      fd,
      { headers: { "Content-Type": "multipart/form-data" } }
    )
    .then((r) => r.data);
};

export const saveCapitalSnapshot = () =>
  apiClient.post<{ snapshot_date: string; invested_base: number }>("/api/portfolio/capital-snapshot").then((r) => r.data);

export const backfillCapitalSnapshots = () =>
  apiClient.post<{ created: number; dates: string[] }>("/api/portfolio/capital-snapshot/backfill").then((r) => r.data);

export const fetchGeographicExposure = () =>
  apiClient
    .get<{
      regions: Record<string, number>;
      by_ticker: {
        ticker: string; name: string; weight_pct: number;
        regions: Record<string, number>;
      }[];
      base_currency: string;
    }>("/api/portfolio/geographic-exposure")
    .then((r) => r.data);

export const fetchEtfOverlap = () =>
  apiClient
    .get<{
      top_holdings: {
        symbol: string; name: string; total_weight_pct: number;
        sources: { etf: string; etf_weight_pct: number; holding_pct: number }[];
        n_etfs: number;
      }[];
      by_etf: {
        ticker: string; name: string; portfolio_weight_pct: number;
        top_holdings: { symbol: string; name: string; pct: number }[];
        has_data: boolean;
      }[];
      overlap_pct: number;
      n_etfs_with_data: number;
      base_currency: string;
    }>("/api/portfolio/etf-overlap")
    .then((r) => r.data);

export const fetchPerformanceTimeframes = () =>
  apiClient
    .get<{
      rows: { ticker: string; current_price?: number; "1W"?: number | null; "1M"?: number | null; "3M"?: number | null; "6M"?: number | null; "YTD"?: number | null; "1Y"?: number | null }[];
      as_of: string;
      periods: string[];
    }>("/api/portfolio/performance-timeframes")
    .then((r) => r.data);

export const fetchEtfExposureForTicker = (ticker: string) =>
  apiClient
    .get<{
      target: string;
      exposures: { etf: string; etf_name: string; etf_portfolio_weight_pct: number; holding_pct_in_etf: number; effective_portfolio_pct: number }[];
      total_effective_pct: number;
      base_currency: string;
    }>(`/api/portfolio/etf-exposure/${ticker}`)
    .then((r) => r.data);
