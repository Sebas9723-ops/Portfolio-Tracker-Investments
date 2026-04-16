"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchPortfolio, saveSnapshot, fetchSnapshots, fetchPortfolioHistory } from "@/lib/api/portfolio";

export function usePortfolio() {
  return useQuery({
    queryKey: ["portfolio"],
    queryFn: fetchPortfolio,
    refetchInterval: 60_000,
    staleTime: 55_000,
    refetchOnWindowFocus: true,
  });
}

export function useSnapshots() {
  return useQuery({
    queryKey: ["snapshots"],
    queryFn: fetchSnapshots,
  });
}

export function useSaveSnapshot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (notes?: string) => saveSnapshot(notes),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["snapshots"] }),
  });
}

export function usePortfolioHistory(start = "2026-03-01") {
  return useQuery({
    queryKey: ["portfolioHistory", start],
    queryFn: () => fetchPortfolioHistory(start),
    staleTime: 5 * 60_000,  // 5 min
  });
}
