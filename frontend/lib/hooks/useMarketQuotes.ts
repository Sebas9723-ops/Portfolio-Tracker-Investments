"use client";
import { useQuery } from "@tanstack/react-query";
import { fetchQuotes } from "@/lib/api/market";
import type { QuoteResponse } from "@/lib/types";

export function useMarketQuotes(tickers: string[], enabled = true) {
  return useQuery<Record<string, QuoteResponse>>({
    queryKey: ["quotes", tickers.sort().join(",")],
    queryFn: () => fetchQuotes(tickers),
    enabled: enabled && tickers.length > 0,
    refetchInterval: 60_000,   // poll every 60 seconds
    staleTime: 55_000,
  });
}
