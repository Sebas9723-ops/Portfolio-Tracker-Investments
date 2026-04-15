"use client";
import { useState } from "react";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { fmtCurrency, fmtPct } from "@/lib/formatters";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";

function monteCarlo(
  initial: number, monthly: number, years: number,
  avgReturn: number, volatility: number, nPaths = 500,
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
  // Build percentile series by year
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
  const [monthly, setMonthly] = useState(500);
  const [years, setYears] = useState(10);
  const [ret, setRet] = useState(0.08);
  const [vol, setVol] = useState(0.15);
  const [goal, setGoal] = useState(100000);

  const data = monteCarlo(initial, monthly, years, ret, vol);
  const base = data[data.length - 1];
  const successRate = base.p50 >= goal ? 75 : base.p10 >= goal ? 25 : 10;

  const ccy = portfolio?.base_currency ?? "USD";

  return (
    <div className="space-y-4">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Investment Horizon</h1>

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
              <input type="number" value={value} onChange={(e) => setter(parseFloat(e.target.value) || 0)}
                step={step} min={min} max={max}
                className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs focus:outline-none focus:border-bloomberg-gold" />
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
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
      </div>

      <div className="bbg-card">
        <p className="bbg-header">Monte Carlo Projection ({years}y)</p>
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 20 }}>
            <defs>
              <linearGradient id="bull" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#4dff4d" stopOpacity={0.2} />
                <stop offset="95%" stopColor="#4dff4d" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="bear" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#ff4d4d" stopOpacity={0.15} />
                <stop offset="95%" stopColor="#ff4d4d" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
            <XAxis dataKey="year" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false}
              tickFormatter={(v) => `Y${v}`} />
            <YAxis tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false}
              tickFormatter={(v) => fmtCurrency(v, ccy, true)} width={65} />
            <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 10 }}
              formatter={(v: number) => fmtCurrency(v, ccy)} />
            <Area type="monotone" dataKey="p90" fill="url(#bull)" stroke="#4dff4d" strokeWidth={1} name="Bull (P90)" dot={false} />
            <Area type="monotone" dataKey="p50" fill="none" stroke="#f3a712" strokeWidth={2} name="Base (P50)" dot={false} />
            <Area type="monotone" dataKey="p10" fill="url(#bear)" stroke="#ff4d4d" strokeWidth={1} name="Bear (P10)" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
