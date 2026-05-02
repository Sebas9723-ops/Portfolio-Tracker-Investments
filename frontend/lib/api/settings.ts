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

export const fetchInsiderTransactions = (ticker: string) =>
  apiClient
    .get<{
      ticker: string;
      transactions: { date: string; insider: string; title: string; transaction: string; shares: number; value: number; is_buy: boolean }[];
    }>(`/api/fundamentals/${ticker}/insiders`)
    .then((r) => r.data);

export const fetchAnalystRatings = (ticker: string) =>
  apiClient
    .get<{
      ticker: string;
      recommendation_key: string | null;
      recommendation_mean: number | null;
      target_mean: number | null;
      target_high: number | null;
      target_low: number | null;
      n_analysts: number | null;
      current_price: number | null;
      upgrades: { date: string; firm: string; to_grade: string; from_grade: string; action: string; is_upgrade: boolean }[];
      rec_history: { date: string; period: string; strong_buy: number; buy: number; hold: number; sell: number; strong_sell: number }[];
    }>(`/api/fundamentals/${ticker}/analyst-ratings`)
    .then((r) => r.data);

export const fetchTechnicals = (ticker: string, period = "1y") =>
  apiClient.get(`/api/technicals/${ticker}`, { params: { period } }).then((r) => r.data);

export type Alert = {
  id: string;
  ticker: string;
  alert_type: "above" | "below";
  threshold: number;
  current_price: number | null;
  triggered: boolean;
};

export const fetchAlerts = () =>
  apiClient.get<Alert[]>("/api/alerts").then((r) => r.data);

export const createAlert = (body: { ticker: string; alert_type: string; threshold: number }) =>
  apiClient.post<Alert>("/api/alerts", body).then((r) => r.data);

export const deleteAlert = (id: string) =>
  apiClient.delete(`/api/alerts/${id}`);
