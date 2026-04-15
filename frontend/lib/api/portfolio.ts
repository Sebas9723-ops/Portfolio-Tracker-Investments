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

export const upsertPosition = (data: Partial<Position> & { ticker: string }) =>
  apiClient.post("/api/portfolio/positions", data).then((r) => r.data);

export const deletePosition = (ticker: string) =>
  apiClient.delete(`/api/portfolio/positions/${ticker}`);
