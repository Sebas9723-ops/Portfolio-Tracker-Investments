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
          message: `⚠️ ${top.ticker} necesita atención: drift de ${top.drift > 0 ? "+" : ""}${top.drift.toFixed(1)}%`,
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
            message: `📉 VOO cayó ${monthlyReturn.toFixed(1)}% este mes — oportunidad táctica`,
            chip: {
              label: "📉 Caída detectada — ¿qué hago?",
              prompt: `VOO ha caído ${monthlyReturn.toFixed(1)}% este mes. Según mi regla de inversión (doblar en VOO y QQQM cuando cae >5%), ¿cuánto debo aportar exactamente en cada uno? Dame un plan de acción concreto en USD.`,
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
