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
