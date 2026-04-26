import { apiClient } from "./client";

export interface DCASchedule {
  id?: string;
  user_id?: string;
  amount: number;
  day_of_month: number;
  tc_model: string;
  profile: string;
  time_horizon: string;
  active: boolean;
  last_run_at?: string | null;
  created_at?: string;
}

export const fetchDCASchedule = () =>
  apiClient.get<DCASchedule>("/api/dca/schedule").then((r) => r.data);

export const upsertDCASchedule = (data: Omit<DCASchedule, "id" | "user_id" | "last_run_at" | "created_at">) =>
  apiClient.post<DCASchedule>("/api/dca/schedule", data).then((r) => r.data);

export const deleteDCASchedule = () =>
  apiClient.delete("/api/dca/schedule").then((r) => r.data);

export const runDCANow = () =>
  apiClient.post("/api/dca/run-now").then((r) => r.data);
