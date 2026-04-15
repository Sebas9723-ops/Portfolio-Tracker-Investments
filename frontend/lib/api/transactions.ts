import { apiClient } from "./client";
import type { Transaction, CashBalance } from "@/lib/types";

export const fetchTransactions = () =>
  apiClient.get<Transaction[]>("/api/transactions").then((r) => r.data);

export const createTransaction = (data: Omit<Transaction, "id" | "created_at">) =>
  apiClient.post<Transaction>("/api/transactions", data).then((r) => r.data);

export const deleteTransaction = (id: string) =>
  apiClient.delete(`/api/transactions/${id}`);

export const fetchCash = () =>
  apiClient.get<CashBalance[]>("/api/transactions/cash").then((r) => r.data);

export const upsertCash = (data: CashBalance) =>
  apiClient.put("/api/transactions/cash", data).then((r) => r.data);

export const fetchDividends = () =>
  apiClient.get("/api/transactions/dividends").then((r) => r.data);
