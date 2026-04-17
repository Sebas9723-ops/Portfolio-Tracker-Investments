"use client";
import { useState, useEffect } from "react";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { useProfileStore } from "@/lib/store/profileStore";
import { useSettingsStore } from "@/lib/store/settingsStore";
import { fmtCurrency, fmtPct } from "@/lib/formatters";
import { HorizonLWChart } from "@/components/charts/HorizonLWChart";

// Profile → which frontier point to use
const PROFILE_FRONTIER_KEY = {
  conservative: "min_vol",
  base:         "max_sharpe",
  aggressive:   "max_return",
} as const;

const PROFILE_FRONTIER_LABEL = {
  conservative: "Min Volatility",
  base:         "Max Sharpe",
  aggressive:   "Max Return",
} as const;

function monteCarlo(
  initial: number, monthly: number, years: number,
  avgReturn: number, volatility: number, nPaths = 1000,
) {
  const months = years * 12;
  const mu = avgReturn / 12;
  const sigma = volatility / Math.sqrt(12);
  const paths: number[][] = Array.from({ length: nPaths }, () => {
    const path = [initial];
    for (let m = 0; m < months; m++) {
      const r = mu + sigma * (Math.random() + Math.random() + Math.random() - 1.5) * Math.sqrt(2 / 3);
      path.push(path[path.length - 1] * (1 + r) + monthly);
    }
    return path;
  });
  const data = [];
  for (let y = 0; y <= years; y++) {
    const idx = y * 12;
    const vals = paths.map((p) => p[idx]).sort((a, b) => a - b);
    data.push({
      year: y,
      p10: vals[Math.floor(0.10 * nPaths)],
      p50: vals[Math.floor(0.50 * nPaths)],
      p90: vals[Math.floor(0.90 * nPaths)],
    });
  }
  return data;
}

export default function InvestmentHorizonPage() {
  const { data: portfolio } = usePortfolio();
  const initial = portfolio?.total_value_base ?? 10000;
  const { profile, targetReturn } = useProfileStore();
  const { horizon_params, frontier_result, setSettings } = useSettingsStore();

  // Pick the right frontier point for the active profile
  const frontierKey = PROFILE_FRONTIER_KEY[profile as keyof typeof PROFILE_FRONTIER_KEY] ?? "max_sharpe";
  const frontierPoint = frontier_result?.[frontierKey];
  const frontierLabel = PROFILE_FRONTIER_LABEL[profile as keyof typeof PROFILE_FRONTIER_LABEL] ?? "Max Sharpe";

  // Default ret/vol: frontier (profile-specific point) > profileStore.targetReturn
  const defaultRet = frontierPoint ? frontierPoint.ret / 100 : targetReturn;
  const defaultVol = frontierPoint ? frontierPoint.vol / 100 : (horizon_params?.vol ?? 0.15);

  const [monthly, setMonthly] = useState(horizon_params?.monthly ?? 500);
  const [years, setYears]     = useState(horizon_params?.years ?? 10);
  const [ret, setRet]         = useState(defaultRet);
  const [vol, setVol]         = useState(defaultVol);
  const [goal, setGoal]       = useState(horizon_params?.goal ?? 100000);

  // Sync when frontier result updates (user ran optimization)
  useEffect(() => {
    if (!frontierPoint) return;
    setRet(frontierPoint.ret / 100);
    setVol(frontierPoint.vol / 100);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frontier_result, profile]);

  // Fallback: sync targetReturn only when no frontier result
  useEffect(() => {
    if (frontierPoint) return;
    setRet(targetReturn);
  }, [targetReturn, frontierPoint]);

  // Persist non-rate params
  useEffect(() => {
    setSettings({ horizon_params: { monthly, years, vol, goal } });
  }, [monthly, years, vol, goal, setSettings]);

  const data = monteCarlo(initial, monthly, years, ret, vol);
  const base = data[data.length - 1];

  const successRate = (() => {
    if (base.p10 >= goal) return 90;
    if (base.p50 >= goal) return 50 + Math.round(50 * (base.p50 - goal) / (base.p50 - base.p10) * -1 + 50);
    if (base.p90 >= goal) return Math.round(50 * (base.p90 - goal) / (base.p90 - base.p50));
    return 5;
  })();

  const requiredMonthly = (() => {
    const months = years * 12;
    const mu = ret / 12;
    const growth = Math.pow(1 + mu, months);
    const pvComponent = initial * growth;
    const annuityFactor = mu > 0 ? (growth - 1) / mu : months;
    return Math.max(0, (goal - pvComponent) / annuityFactor);
  })();

  const ccy = portfolio?.base_currency ?? "USD";

  return (
    <div className="space-y-4">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Investment Horizon</h1>

      {/* Source banner */}
      <div className="flex items-center gap-3 px-3 py-2 border border-bloomberg-border text-[10px]">
        <span className="text-bloomberg-muted uppercase tracking-widest">Guided by:</span>
        {frontierPoint ? (
          <>
            <span className="text-bloomberg-gold font-semibold">
              Efficient Frontier — {frontierLabel}
            </span>
            <span className="text-bloomberg-muted">
              Ret {fmtPct(frontierPoint.ret)} · Vol {fmtPct(frontierPoint.vol)} · Sharpe {frontierPoint.sharpe.toFixed(3)}
            </span>
            <button
              onClick={() => {
                setSettings({ frontier_result: undefined });
                setRet(targetReturn);
                setVol(horizon_params?.vol ?? 0.15);
              }}
              className="ml-auto text-bloomberg-muted hover:text-bloomberg-red"
            >
              ✕ Clear
            </button>
          </>
        ) : (
          <span className="text-bloomberg-muted">
            No frontier result — using investor profile target ({fmtPct(targetReturn * 100)}).
            Run Optimization to connect.
          </span>
        )}
      </div>

      <div className="bbg-card">
        <p className="bbg-header">Parameters</p>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[
            { label: "Monthly Contribution", value: monthly, setter: setMonthly, step: 100 },
            { label: "Horizon (years)", value: years, setter: setYears, step: 1, min: 1, max: 30 },
            { label: "Avg Annual Return", value: ret, setter: setRet, step: 0.01, isRate: true },
            { label: "Annual Volatility", value: vol, setter: setVol, step: 0.01, isRate: true },
            { label: "Target Goal", value: goal, setter: setGoal, step: 1000 },
          ].map(({ label, value, setter, step, min, max, isRate }) => (
            <div key={label}>
              <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">
                {label}{isRate ? `: ${fmtPct(value * 100)}` : ""}
              </label>
              <input
                type="number" value={value}
                onChange={(e) => setter(parseFloat(e.target.value) || 0)}
                step={step} min={min} max={max}
                className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
              />
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="bbg-card">
          <p className="text-bloomberg-muted text-[10px] uppercase">Bear (P10)</p>
          <p className={`text-lg font-semibold ${(base?.p10 ?? 0) >= goal ? "positive" : "text-bloomberg-text"}`}>
            {fmtCurrency(base?.p10 ?? 0, ccy)}
          </p>
        </div>
        <div className="bbg-card">
          <p className="text-bloomberg-muted text-[10px] uppercase">Base (P50)</p>
          <p className={`text-lg font-semibold ${(base?.p50 ?? 0) >= goal ? "positive" : "text-bloomberg-text"}`}>
            {fmtCurrency(base?.p50 ?? 0, ccy)}
          </p>
        </div>
        <div className="bbg-card">
          <p className="text-bloomberg-muted text-[10px] uppercase">Bull (P90)</p>
          <p className={`text-lg font-semibold ${(base?.p90 ?? 0) >= goal ? "positive" : "text-bloomberg-text"}`}>
            {fmtCurrency(base?.p90 ?? 0, ccy)}
          </p>
        </div>
        <div className="bbg-card">
          <p className="text-bloomberg-muted text-[10px] uppercase">Success Rate</p>
          <p
            className={`text-lg font-semibold ${successRate >= 50 ? "positive" : "negative"}`}
            style={successRate >= 25 && successRate < 50 ? { color: "#f3a712" } : {}}
          >
            ~{successRate}%
          </p>
          <p className="text-bloomberg-muted text-[10px]">of hitting goal</p>
        </div>
        <div className="bbg-card">
          <p className="text-bloomberg-muted text-[10px] uppercase">Required/mo</p>
          <p className="text-lg font-semibold text-bloomberg-gold">
            {fmtCurrency(requiredMonthly, ccy)}
          </p>
          <p className="text-bloomberg-muted text-[10px]">to reach P50 goal</p>
        </div>
      </div>

      <div className="bbg-card">
        <p className="bbg-header">Monte Carlo Projection ({years}y)</p>
        <HorizonLWChart data={data} ccy={ccy} />
      </div>
    </div>
  );
}
