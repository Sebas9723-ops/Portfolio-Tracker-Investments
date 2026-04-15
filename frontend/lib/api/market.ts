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
