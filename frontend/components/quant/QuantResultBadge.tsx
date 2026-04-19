"use client";

interface QuantResultBadgeProps {
  regime: "bull" | "bear";
  regimeConfidence: number;
  expectedReturn: number;
  expectedSharpe: number;
  cvar95: number;
  optimizationTimestamp: string;
}

export function QuantResultBadge({
  regime,
  regimeConfidence,
  expectedReturn,
  expectedSharpe,
  cvar95,
  optimizationTimestamp,
}: QuantResultBadgeProps) {
  const isBull = regime === "bull";
  const regimeColor = isBull ? "#22c55e" : "#ef4444";
  const regimeBg = isBull ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)";
  const regimeBorder = isBull ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.25)";

  const ts = new Date(optimizationTimestamp);
  const tsLabel = ts.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div
      className="flex flex-wrap items-center gap-3 px-3 py-2 border text-[10px]"
      style={{ borderColor: regimeBorder, background: regimeBg }}
    >
      {/* Regime dot + label */}
      <div className="flex items-center gap-1.5">
        <span
          className="inline-block w-2 h-2 rounded-full"
          style={{ background: regimeColor, boxShadow: `0 0 4px ${regimeColor}` }}
        />
        <span className="font-bold uppercase tracking-wider" style={{ color: regimeColor }}>
          {isBull ? "Bull" : "Bear"} Regime
        </span>
        <span className="text-bloomberg-muted ml-0.5">
          ({Math.round(regimeConfidence * 100)}% conf.)
        </span>
      </div>

      <div className="h-3 w-px bg-bloomberg-border" />

      {/* Metrics */}
      <div className="flex items-center gap-1">
        <span className="text-bloomberg-muted">Exp. Return</span>
        <span className="font-semibold text-green-400">
          {(expectedReturn * 100).toFixed(1)}%
        </span>
      </div>

      <div className="flex items-center gap-1">
        <span className="text-bloomberg-muted">Sharpe</span>
        <span className="font-semibold text-bloomberg-gold">
          {expectedSharpe.toFixed(2)}
        </span>
      </div>

      <div className="flex items-center gap-1">
        <span className="text-bloomberg-muted">CVaR 95%</span>
        <span className="font-semibold text-red-400">
          {(cvar95 * 100).toFixed(2)}%
        </span>
      </div>

      <div className="h-3 w-px bg-bloomberg-border" />

      <span className="text-bloomberg-muted">
        Powered by quant engine · {tsLabel}
      </span>
    </div>
  );
}
