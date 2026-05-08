import { apiClient } from "./client";

export interface BrokerReconcileResult {
  imported: number;
  errors: string[];
  positions_updated: number;
  positions_created: number;
  positions_zeroed: number;
  reconciled_tickers: string[];
  deposits_usd: number;
  agent_summary: string | null;
}

export const brokerReconcile = (file: File): Promise<BrokerReconcileResult> => {
  const formData = new FormData();
  formData.append("file", file);
  return apiClient
    .post<BrokerReconcileResult>("/api/agents/broker-reconcile", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 120_000,
    })
    .then((r) => r.data);
};
