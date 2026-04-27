import { apiClient } from "./client";

export interface ImportResult {
  imported: number;
  skipped: number;
  errors: string[];
  tickers: string[];
}

export const importIBKRCsv = (file: File): Promise<ImportResult> => {
  const formData = new FormData();
  formData.append("file", file);
  return apiClient
    .post<ImportResult>("/api/import/ibkr-csv", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

export interface XTBImportResult extends ImportResult {
  deposits_usd: number;
}

export const importXTBXlsx = (file: File): Promise<XTBImportResult> => {
  const formData = new FormData();
  formData.append("file", file);
  return apiClient
    .post<XTBImportResult>("/api/import/xtb-xlsx", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

export interface BrokerReconcileResult {
  imported: number;
  skipped_duplicates: number;
  errors: string[];
  positions_updated: number;
  positions_created: number;
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
