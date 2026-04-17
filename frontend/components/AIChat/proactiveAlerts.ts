import { useMemo, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchRebalancing } from "@/lib/api/analytics";
import { useMarketQuotes } from "@/lib/hooks/useMarketQuotes";

export type AlertSeverity = "red" | "orange";

export interface ProactiveAlert {
  id: string;
  severity: AlertSeverity;
  message: string;
  chip?: { label: string; prompt: string };
}

const VOO_MONTHLY_KEY = () => {
  const now = new Date();
  return `voo-month-start-${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
};

export function useProactiveAlerts() {
  const { data: rebalancing } = useQuery({
    queryKey: ["rebalancing", 0, "broker"],
    queryFn: () => fetchRebalancing({}),
    staleTime: 5 * 60_000,
  });

  const { data: quotes } = useMarketQuotes(["VOO"]);

  // Store VOO price at start of month
  useEffect(() => {
    const vooPrice = quotes?.["VOO"]?.price;
    if (vooPrice == null) return;
    const key = VOO_MONTHLY_KEY();
    if (!localStorage.getItem(key)) {
      localStorage.setItem(key, String(vooPrice));
    }
  }, [quotes]);

  const alerts = useMemo<ProactiveAlert[]>(() => {
    const result: ProactiveAlert[] = [];

    // Alert 1 — Critical drift
    if (rebalancing) {
      const critical = rebalancing
        .filter((r) => Math.abs(r.drift) > 15)
        .sort((a, b) => Math.abs(b.drift) - Math.abs(a.drift));
      if (critical.length > 0) {
        const top = critical[0];
        result.push({
          id: "drift",
          severity: "red",
          message: `⚠️ ${top.ticker} requires attention: drift of ${top.drift > 0 ? "+" : ""}${top.drift.toFixed(1)}%`,
        });
      }
    }

    // Alert 2 — VOO monthly tactical opportunity
    const vooPrice = quotes?.["VOO"]?.price;
    if (vooPrice != null) {
      const stored = localStorage.getItem(VOO_MONTHLY_KEY());
      if (stored) {
        const startPrice = parseFloat(stored);
        const monthlyReturn = ((vooPrice - startPrice) / startPrice) * 100;
        if (monthlyReturn < -5) {
          result.push({
            id: "voo-dip",
            severity: "orange",
            message: `📉 VOO down ${monthlyReturn.toFixed(1)}% this month — tactical opportunity`,
            chip: {
              label: "📉 Dip detected — what do I do?",
              prompt: `VOO has dropped ${monthlyReturn.toFixed(1)}% this month. Per my dip rule (double VOO + QQQM when down >5%), how much should I deploy in each? Give me a concrete action plan in USD.`,
            },
          });
        }
      }
    }

    return result;
  }, [rebalancing, quotes]);

  const hasBadge = alerts.length > 0;
  const badgeSeverity: AlertSeverity | null = alerts.some((a) => a.severity === "red")
    ? "red"
    : alerts.some((a) => a.severity === "orange")
    ? "orange"
    : null;

  return { alerts, hasBadge, badgeSeverity };
}
