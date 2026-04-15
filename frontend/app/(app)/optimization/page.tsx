"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { fetchFrontier } from "@/lib/api/analytics";
import { fmtPct } from "@/lib/formatters";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceDot,
} from "recharts";
import type { OptimizationResult, FrontierPoint } from "@/lib/types";

export default function OptimizationPage() {
  const [maxSingle, setMaxSingle] = useState(0.40);
  const [nSim, setNSim] = useState(3000);
  const [period, setPeriod] = useState("2y");
  const [result, setResult] = useState<OptimizationResult | null>(null);

  const { mutate, isPending } = useMutation({
    mutationFn: () => fetchFrontier({ max_single_asset: maxSingle, n_simulations: nSim, period }),
    onSuccess: setResult,
  });

  const CustomDot = (props: { payload?: FrontierPoint; cx?: number; cy?: number }) => {
    const { cx, cy, payload } = props;
    if (!payload || !cx || !cy) return null;
    return <circle cx={cx} cy={cy} r={2} fill="#1e2535" />;
  };

  return (
    <div className="space-y-4">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Optimization</h1>

      {/* Controls */}
      <div className="bbg-card">
        <p className="bbg-header">Constraints</p>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">
              Max Single Asset: {fmtPct(maxSingle * 100)}
            </label>
            <input type="range" min={0.1} max={1} step={0.05} value={maxSingle}
              onChange={(e) => setMaxSingle(parseFloat(e.target.value))}
              className="w-full accent-bloomberg-gold" />
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">
              Simulations: {nSim.toLocaleString()}
            </label>
            <input type="range" min={500} max={8000} step={500} value={nSim}
              onChange={(e) => setNSim(parseInt(e.target.value))}
              className="w-full accent-bloomberg-gold" />
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Period</label>
            <select value={period} onChange={(e) => setPeriod(e.target.value)}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs">
              {["1y", "2y", "3y", "5y"].map((p) => <option key={p}>{p}</option>)}
            </select>
          </div>
        </div>
        <button onClick={() => mutate()} disabled={isPending}
          className="mt-3 bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-6 py-1.5 hover:opacity-90 disabled:opacity-50">
          {isPending ? "COMPUTING…" : "RUN OPTIMIZATION"}
        </button>
      </div>

      {result && (
        <>
          {/* Efficient Frontier scatter */}
          <div className="bbg-card">
            <p className="bbg-header">Efficient Frontier</p>
            <ResponsiveContainer width="100%" height={300}>
              <ScatterChart margin={{ top: 10, right: 20, bottom: 20, left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
                <XAxis dataKey="vol" name="Volatility %" type="number" domain={["auto", "auto"]}
                  tick={{ fontSize: 10, fill: "#8a9bb5" }} tickLine={false}
                  label={{ value: "Volatility (%)", position: "insideBottom", offset: -10, fontSize: 10, fill: "#8a9bb5" }} />
                <YAxis dataKey="ret" name="Return %" type="number" domain={["auto", "auto"]}
                  tick={{ fontSize: 10, fill: "#8a9bb5" }} tickLine={false} axisLine={false} width={40}
                  label={{ value: "Return (%)", angle: -90, position: "insideLeft", fontSize: 10, fill: "#8a9bb5" }} />
                <Tooltip cursor={false}
                  contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                  formatter={(v: number) => `${v.toFixed(2)}%`} />
                <Scatter data={result.frontier} shape={<CustomDot />} />
                {/* Max Sharpe */}
                <ReferenceDot x={result.max_sharpe.vol} y={result.max_sharpe.ret} r={6}
                  fill="#f3a712" stroke="#0b0f14" label={{ value: "Max Sharpe", position: "top", fontSize: 10, fill: "#f3a712" }} />
                {/* Min Vol */}
                <ReferenceDot x={result.min_vol.vol} y={result.min_vol.ret} r={6}
                  fill="#38b2ff" stroke="#0b0f14" label={{ value: "Min Vol", position: "top", fontSize: 10, fill: "#38b2ff" }} />
                {/* Current */}
                {result.current_metrics.volatility != null && (
                  <ReferenceDot x={result.current_metrics.volatility} y={result.current_metrics.return} r={6}
                    fill="#8a9bb5" stroke="#0b0f14" label={{ value: "Current", position: "top", fontSize: 10, fill: "#8a9bb5" }} />
                )}
              </ScatterChart>
            </ResponsiveContainer>
          </div>

          {/* Weights comparison */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[
              { label: "Max Sharpe Weights", data: result.max_sharpe.weights, color: "#f3a712" },
              { label: "Min Volatility Weights", data: result.min_vol.weights, color: "#38b2ff" },
              { label: "Risk Parity Weights", data: result.risk_parity, color: "#4dff4d" },
            ].map(({ label, data, color }) => (
              <div key={label} className="bbg-card">
                <p className="bbg-header" style={{ color }}>{label}</p>
                <table className="bbg-table">
                  <thead><tr><th>Ticker</th><th className="text-right">Weight</th></tr></thead>
                  <tbody>
                    {Object.entries(data).sort(([, a], [, b]) => b - a).map(([t, w]) => (
                      <tr key={t}>
                        <td className="text-bloomberg-gold">{t}</td>
                        <td className="text-right">{fmtPct((w as number) * 100)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
