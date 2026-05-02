import { apiClient } from "./client";
import type { QuoteResponse, HistoricalResponse, MarketStatus } from "@/lib/types";

export const fetchQuotes = (tickers: string[]) =>
  apiClient
    .get<Record<string, QuoteResponse>>("/api/market/quotes", {
      params: { tickers: tickers.join(",") },
    })
    .then((r) => r.data);

export const fetchQuote = (ticker: string) =>
  apiClient.get<QuoteResponse>(`/api/market/quote/${ticker}`).then((r) => r.data);

export const fetchHistorical = (ticker: string, period = "1y") =>
  apiClient
    .get<HistoricalResponse>(`/api/market/historical/${ticker}`, { params: { period } })
    .then((r) => r.data);

export const fetchMarketStatus = () =>
  apiClient.get<MarketStatus>("/api/market/status").then((r) => r.data);

export const fetchRiskFreeRate = () =>
  apiClient.get<{ rate: number }>("/api/market/risk-free-rate").then((r) => r.data.rate);

export const fetchMarketBreadth = () =>
  apiClient
    .get<{
      universe_size: number;
      advancing: number; declining: number; unchanged: number;
      advancing_pct: number; declining_pct: number;
      above_sma50: number; above_sma50_pct: number;
      above_sma200: number; above_sma200_pct: number;
      rel_vol_leaders: { ticker: string; price: number; change_pct: number; rel_vol: number }[];
      top_gainers: { ticker: string; price: number; change_pct: number }[];
      top_losers: { ticker: string; price: number; change_pct: number }[];
      as_of: string;
    }>("/api/market/breadth")
    .then((r) => r.data);

export interface ScreenerRow {
  ticker: string; name: string; sector: string; price: number; change_pct: number;
  market_cap_b: number | null; pe: number | null; forward_pe: number | null;
  pb: number | null; div_yield: number; roe: number; gross_margin: number | null;
  profit_margin: number | null; debt_equity: number; beta: number | null;
  rel_vol: number | null; dist_sma50: number | null; dist_sma200: number | null;
  short_float: number; recommendation: string; target_price: number | null; upside: number | null;
}

export const fetchScreener = (params?: {
  sector?: string; min_pe?: number; max_pe?: number; min_div_yield?: number;
  min_roe?: number; max_debt_eq?: number; min_market_cap_b?: number; max_market_cap_b?: number;
  min_rel_vol?: number; sort_by?: string; sort_desc?: boolean; limit?: number; tickers?: string;
}) =>
  apiClient
    .get<{ rows: ScreenerRow[]; total: number; universe_fetched: number }>("/api/market/screener", { params, timeout: 60_000 })
    .then((r) => r.data);

export const fetchEarningsCalendar = (days_ahead = 14) =>
  apiClient
    .get<{
      events: { ticker: string; name: string; earnings_date: string; eps_estimate: number | null; market_cap_b: number; sector: string }[];
      days_ahead: number; as_of: string;
    }>("/api/market/earnings-calendar", { params: { days_ahead } })
    .then((r) => r.data);
