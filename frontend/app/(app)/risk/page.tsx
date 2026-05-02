"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchVaR, fetchStressTest, fetchCorrelation, fetchRiskBudget, fetchFxExposure } from "@/lib/api/analytics";
import { useAIChat } from "@/lib/context/aiChatContext";
import { MetricCard } from "@/components/shared/MetricCard";
import { fmtCurrency, fmtPct } from "@/lib/formatters";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
  PieChart, Pie, Legend,
} from "recharts";

const COLORS = ["#f3a712", "#4dff4d", "#38b2ff", "#ff4d4d", "#c084fc", "#fb923c"];

export default function RiskPage() {
  const { openWith } = useAIChat();
  const [confidence, setConfidence] = useState(0.95);
  const { data: varData, isLoading: varLoading } = useQuery({ queryKey: ["var", confidence], queryFn: () => fetchVaR(confidence), staleTime: 5 * 60 * 1000 });
  const { data: stress } = useQuery({ queryKey: ["stress"], queryFn: fetchStressTest, staleTime: 5 * 60 * 1000 });
  const { data: corr } = useQuery({ queryKey: ["correlation"], queryFn: () => fetchCorrelation(), staleTime: 5 * 60 * 1000 });
  const { data: budget } = useQuery({ queryKey: ["riskbudget"], queryFn: () => fetchRiskBudget(), staleTime: 5 * 60 * 1000 });
  const { data: fx } = useQuery({ queryKey: ["fxexposure"], queryFn: fetchFxExposure, staleTime: 5 * 60 * 1000 });

  return (
    <div className="space-y-4">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Risk</h1>

      {/* VaR */}
      <div className="bbg-card">
        <div className="flex items-center justify-between mb-3">
          <p className="bbg-header mb-0">Value at Risk (1-day)</p>
          <div className="flex gap-1">
            {[0.90, 0.95, 0.99].map((c) => (
              <button key={c} onClick={() => setConfidence(c)}
                className={`text-[10px] px-2 py-0.5 border ${confidence === c ? "border-bloomberg-gold text-bloomberg-gold" : "border-bloomberg-border text-bloomberg-muted"}`}>
                {fmtPct((1 - c) * 100)} tail
              </button>
            ))}
          </div>
        </div>
        {varLoading && !varData && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="bbg-card animate-pulse h-14 bg-bloomberg-bg" />
            ))}
          </div>
        )}
        {varData && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetricCard label="Historical VaR" value={fmtCurrency(varData.var_historical)} deltaPositive={false} />
            <MetricCard label="Parametric VaR" value={fmtCurrency(varData.var_parametric)} deltaPositive={false} />
            <MetricCard label="Historical CVaR" value={fmtCurrency(varData.cvar_historical)} deltaPositive={false} />
            <MetricCard label="Parametric CVaR" value={fmtCurrency(varData.cvar_parametric)} deltaPositive={false} />
          </div>
        )}
      </div>

      {/* Stress tests */}
      {stress && stress.length > 0 && (
        <div className="bbg-card">
          <div className="flex items-center justify-between mb-0">
            <p className="bbg-header mb-0">Stress Tests</p>
            <button
              onClick={() => openWith("Interpret my current risk profile: VaR, stress tests, and correlations. What should I know?")}
              className="flex items-center gap-1.5 text-[10px] text-[#f3a712] border border-[#f3a712]/40 px-2.5 py-1 rounded-lg hover:bg-[#f3a712]/10 transition-colors"
            >
              🤖 Interpret my risk
            </button>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={stress} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
              <XAxis dataKey="scenario" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} />
              <YAxis tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false}
                tickFormatter={(v) => `${v.toFixed(0)}%`} width={40} />
              <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                formatter={(v: number) => [`${v.toFixed(2)}%`]} />
              <Bar dataKey="portfolio_impact_pct" barSize={20}>
                {stress.map((s, i) => (
                  <Cell key={i} fill={s.portfolio_impact_pct >= 0 ? "#4dff4d" : "#ff4d4d"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Risk budget */}
        {budget && Object.keys(budget).length > 0 && (
          <div className="bbg-card">
            <p className="bbg-header">Risk Contribution</p>
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie data={Object.entries(budget).map(([name, value]) => ({ name, value }))}
                  cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={2} dataKey="value">
                  {Object.keys(budget).map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Pie>
                <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                  formatter={(v: number) => [`${v.toFixed(2)}%`]} />
                <Legend iconSize={8} wrapperStyle={{ fontSize: 10 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* FX exposure */}
        {fx && Object.keys(fx).length > 0 && (
          <div className="bbg-card">
            <p className="bbg-header">FX Exposure (non-base)</p>
            <table className="bbg-table mt-2">
              <thead><tr><th>Currency</th><th className="text-right">Exposure %</th></tr></thead>
              <tbody>
                {Object.entries(fx).sort(([, a], [, b]) => b - a).map(([ccy, pct]) => (
                  <tr key={ccy}>
                    <td className="text-bloomberg-gold">{ccy}</td>
                    <td className="text-right">{fmtPct(pct as number)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Correlation heatmap */}
      {corr && corr.tickers?.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Correlation Heatmap</p>
          <p className="text-bloomberg-muted text-[10px] mb-3">
            Daily returns. <span className="text-red-400">Red</span> = high correlation (concentration risk). <span className="text-blue-400">Blue</span> = negative (diversification benefit). <span className="text-bloomberg-gold">Gold</span> = diagonal.
          </p>
          <div className="overflow-x-auto">
            <div style={{ minWidth: `${corr.tickers.length * 60 + 100}px` }}>
              <div className="flex">
                <div className="w-24 shrink-0" />
                {corr.tickers.map((t: string) => (
                  <div key={t} className="w-14 shrink-0 text-[8px] text-bloomberg-muted text-center truncate px-0.5 pb-1 font-bold" title={t}>
                    {t.length > 8 ? t.slice(0, 8) : t}
                  </div>
                ))}
              </div>
              {corr.tickers.map((rowTicker: string, i: number) => (
                <div key={rowTicker} className="flex items-center">
                  <div className="w-24 shrink-0 text-[9px] text-bloomberg-gold font-bold truncate pr-2">{rowTicker}</div>
                  {corr.matrix[i].map((val: number, j: number) => {
                    const isDiag = i === j;
                    const abs = Math.abs(val);
                    let bg = "";
                    let textColor = "#cbd5e1";
                    if (isDiag) {
                      bg = "rgba(243,167,18,0.35)";
                      textColor = "#f3a712";
                    } else if (val > 0.7) {
                      bg = `rgba(220,38,38,${0.3 + abs * 0.5})`;
                      textColor = "#fca5a5";
                    } else if (val > 0.4) {
                      bg = `rgba(251,146,60,${0.2 + abs * 0.5})`;
                      textColor = "#fed7aa";
                    } else if (val > 0.15) {
                      bg = `rgba(251,191,36,${0.15 + abs * 0.4})`;
                      textColor = "#fde68a";
                    } else if (val < -0.3) {
                      bg = `rgba(59,130,246,${0.2 + abs * 0.5})`;
                      textColor = "#bfdbfe";
                    } else {
                      bg = "rgba(30,41,59,0.6)";
                      textColor = "#94a3b8";
                    }
                    return (
                      <div key={j}
                        className="w-14 h-10 shrink-0 flex items-center justify-center text-[9px] font-bold border border-bloomberg-bg/10 cursor-default"
                        style={{ background: bg, color: textColor }}
                        title={`${rowTicker} ↔ ${corr.tickers[j]}: ${val.toFixed(3)}`}
                      >
                        {val.toFixed(2)}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
