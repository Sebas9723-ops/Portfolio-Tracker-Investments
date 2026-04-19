"use client";

import { fmtPct } from "@/lib/formatters";
import type { RegimeLabel, RegimeProbs, MLDiagnostics } from "@/lib/api/contribution";

const REGIME_META: Record<RegimeLabel, { label: string; color: string; bg: string; border: string }> = {
  bull_strong: {
    label: "Bull (Strong)",
    color: "#22c55e",
    bg: "rgba(34,197,94,0.08)",
    border: "rgba(34,197,94,0.25)",
  },
  bull_weak: {
    label: "Bull (Weak)",
    color: "#86efac",
    bg: "rgba(134,239,172,0.06)",
    border: "rgba(134,239,172,0.20)",
  },
  bear_mild: {
    label: "Bear (Mild)",
    color: "#f97316",
    bg: "rgba(249,115,22,0.08)",
    border: "rgba(249,115,22,0.25)",
  },
  crisis: {
    label: "Crisis",
    color: "#ef4444",
    bg: "rgba(239,68,68,0.08)",
    border: "rgba(239,68,68,0.25)",
  },
};

const REGIME_ORDER: RegimeLabel[] = ["bull_strong", "bull_weak", "bear_mild", "crisis"];

interface QuantResultBadgeProps {
  regime: RegimeLabel;
  regimeConfidence: number;
  regimeProbs?: RegimeProbs;
  expectedReturn: number;
  expectedSharpe: number;
  cvar95: number;
  optimizationTimestamp: string;
  mlDiagnostics?: MLDiagnostics;
}

export function QuantResultBadge({
  regime,
  regimeConfidence,
  regimeProbs,
  expectedReturn,
  expectedSharpe,
  cvar95,
  optimizationTimestamp,
  mlDiagnostics,
}: QuantResultBadgeProps) {
  const meta = REGIME_META[regime] ?? REGIME_META.bull_weak;
  const ts = new Date(optimizationTimestamp);
  const tsLabel = ts.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  const mlModules = mlDiagnostics
    ? [
        { key: "GARCH", ok: mlDiagnostics.garch_available, ms: mlDiagnostics.garch_ms },
        { key: "FF5", ok: mlDiagnostics.ff5_available, ms: mlDiagnostics.ff5_ms },
        { key: "GMM", ok: mlDiagnostics.regime_available, ms: mlDiagnostics.regime_ms },
        { key: "XGB", ok: mlDiagnostics.xgb_available, ms: mlDiagnostics.xgb_ms },
      ]
    : [];

  return (
    <div
      className="border text-[10px] space-y-2 px-3 py-2"
      style={{ borderColor: meta.border, background: meta.bg }}
    >
      {/* Row 1 — regime + metrics */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Regime dot + label */}
        <div className="flex items-center gap-1.5">
          <span
            className="inline-block w-2 h-2 rounded-full"
            style={{ background: meta.color, boxShadow: `0 0 4px ${meta.color}` }}
          />
          <span className="font-bold uppercase tracking-wider" style={{ color: meta.color }}>
            {meta.label}
          </span>
          <span className="text-bloomberg-muted ml-0.5">
            ({Math.round(regimeConfidence * 100)}% conf.)
          </span>
        </div>

        <div className="h-3 w-px bg-bloomberg-border" />

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
        <span className="text-bloomberg-muted">ML quant engine · {tsLabel}</span>
      </div>

      {/* Row 2 — 4-state regime probability bar */}
      {regimeProbs && (
        <div className="space-y-0.5">
          <div className="flex h-1.5 w-full rounded-sm overflow-hidden gap-px">
            {REGIME_ORDER.map((r) => (
              <div
                key={r}
                style={{
                  width: `${(regimeProbs[r] ?? 0) * 100}%`,
                  background: REGIME_META[r].color,
                  opacity: r === regime ? 1 : 0.35,
                }}
              />
            ))}
          </div>
          <div className="flex justify-between text-bloomberg-muted" style={{ fontSize: 9 }}>
            {REGIME_ORDER.map((r) => (
              <span key={r} style={{ color: r === regime ? REGIME_META[r].color : undefined }}>
                {REGIME_META[r].label.split(" ")[1]?.replace(/[()]/g, "") ?? REGIME_META[r].label}{" "}
                {Math.round((regimeProbs[r] ?? 0) * 100)}%
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Row 3 — ML module status */}
      {mlModules.length > 0 && (
        <div className="flex flex-wrap gap-2 pt-0.5 border-t border-bloomberg-border/50">
          {mlModules.map(({ key, ok, ms }) => (
            <span key={key} className="flex items-center gap-1">
              <span
                className="inline-block w-1.5 h-1.5 rounded-full"
                style={{ background: ok ? "#22c55e" : "#ef4444" }}
              />
              <span className={ok ? "text-bloomberg-muted" : "text-red-400"}>{key}</span>
              {ms != null && <span className="text-bloomberg-muted">{ms}ms</span>}
            </span>
          ))}
          {mlDiagnostics?.xgb_views_generated != null && mlDiagnostics.xgb_views_generated > 0 && (
            <span className="text-bloomberg-muted">
              · {mlDiagnostics.xgb_views_generated} XGB views
            </span>
          )}
        </div>
      )}
    </div>
  );
}
