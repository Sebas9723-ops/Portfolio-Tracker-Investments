import { apiClient } from "./client";
import type { InvestorProfile } from "@/lib/store/profileStore";

export interface ProfileMetrics {
  ann_return: number;
  ann_vol: number;
  sharpe: number;
  max_drawdown: number;
}

export interface ProfileData {
  weights: Record<string, number>;
  metrics: ProfileMetrics;
}

export interface ProfileOptimalResponse {
  profiles: Record<"conservative" | "base" | "aggressive", ProfileData>;
  current: ProfileData;
  active_profile: string;
  target_return: number;
  tickers: string[];
  period: string;
}

export const fetchProfileOptimal = (period = "2y") =>
  apiClient
    .get<ProfileOptimalResponse>("/api/profile/optimal", { params: { period } })
    .then((r) => r.data);

export const updateProfile = (profile: InvestorProfile, target_return?: number) =>
  apiClient
    .put("/api/profile", { investor_profile: profile, target_return })
    .then((r) => r.data);
