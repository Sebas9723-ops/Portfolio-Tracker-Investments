import { apiClient } from "./client";
import type { UserSettings } from "@/lib/types";

export const fetchSettings = () =>
  apiClient.get<UserSettings>("/api/settings").then((r) => r.data);

export const updateSettings = (data: Partial<UserSettings>) =>
  apiClient.put<UserSettings>("/api/settings", data).then((r) => r.data);

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
