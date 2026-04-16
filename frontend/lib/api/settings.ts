import { apiClient } from "./client";
import type { UserSettings, TickerFloorCap, CombinationRange } from "@/lib/types";

export const fetchSettings = () =>
  apiClient.get<UserSettings>("/api/settings").then((r) => r.data);

export const updateSettings = (data: Partial<UserSettings>) =>
  apiClient.put<UserSettings>("/api/settings", data).then((r) => r.data);

// Motor 1 — save floor/cap rules for a specific profile
export const saveTickerWeightRules = (profile: string, rules: Record<string, TickerFloorCap>) =>
  apiClient
    .put("/api/optimization/ticker-weight-rules", { profile, rules })
    .then((r) => r.data);

// Motor 2 — save combination range rules for a specific profile
export const saveCombinationRanges = (profile: string, ranges: CombinationRange[]) =>
  apiClient
    .put("/api/optimization/combination-ranges", { profile, ranges })
    .then((r) => r.data);

export const fetchWatchlist = () =>
  apiClient.get("/api/watchlist").then((r) => r.data);

export const addToWatchlist = (ticker: string, name?: string) =>
  apiClient.post("/api/watchlist", { ticker, name }).then((r) => r.data);

export const removeFromWatchlist = (ticker: string) =>
  apiClient.delete(`/api/watchlist/${ticker}`);

export const fetchNews = (tickers: string[]) =>
  apiClient
    .get("/api/news", { params: { tickers: tickers.join(",") } })
    .then((r) => r.data);

export const fetchFundamentals = (ticker: string) =>
  apiClient.get(`/api/fundamentals/${ticker}`).then((r) => r.data);

export const fetchTechnicals = (ticker: string, period = "1y") =>
  apiClient.get(`/api/technicals/${ticker}`, { params: { period } }).then((r) => r.data);
