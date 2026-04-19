"use client";

import type { CorrelationAlert } from "@/lib/api/contribution";

interface CorrelationAlertsProps {
  alerts: CorrelationAlert[];
}

export function CorrelationAlerts({ alerts }: CorrelationAlertsProps) {
  if (alerts.length === 0) return null;

  return (
    <div className="bbg-card border-amber-500/20 bg-amber-500/5">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-amber-400 font-bold text-[11px] uppercase tracking-wider">
          Correlation Shift Alerts
        </span>
        <span className="px-1.5 py-0.5 text-[9px] font-bold rounded-full bg-amber-500/20 text-amber-400">
          {alerts.length}
        </span>
      </div>
      <p className="text-bloomberg-muted text-[10px] mb-3">
        Pairs where rolling 60-day correlation deviates significantly from historical baseline.
        Weight caps have been reduced 15% for affected tickers.
      </p>
      <div className="space-y-2">
        {alerts.map((a, i) => {
          const isPositiveShift = a.deviation > 0;
          const deviationColor = isPositiveShift ? "#ef4444" : "#22c55e";
          const directionLabel = isPositiveShift
            ? "Correlation spiked — diversification reduced"
            : "Correlation dropped — divergence risk";

          return (
            <div
              key={i}
              className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 border border-bloomberg-border text-[10px]"
            >
              <div className="flex items-center gap-2">
                <span className="text-bloomberg-gold font-semibold">{a.ticker_a}</span>
                <span className="text-bloomberg-muted">↔</span>
                <span className="text-bloomberg-gold font-semibold">{a.ticker_b}</span>
              </div>

              <div className="flex items-center gap-4">
                <div>
                  <span className="text-bloomberg-muted">Historical: </span>
                  <span className="text-bloomberg-text">{a.historical_corr.toFixed(2)}</span>
                </div>
                <div>
                  <span className="text-bloomberg-muted">Current: </span>
                  <span className="text-bloomberg-text">{a.current_corr.toFixed(2)}</span>
                </div>
                <div>
                  <span className="text-bloomberg-muted">Δ </span>
                  <span className="font-bold" style={{ color: deviationColor }}>
                    {a.deviation > 0 ? "+" : ""}{a.deviation.toFixed(2)}
                  </span>
                </div>
              </div>

              <span className="text-bloomberg-muted italic">{directionLabel}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
