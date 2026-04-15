"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAnalytics } from "@/lib/api/analytics";
import { MetricCard } from "@/components/shared/MetricCard";
import { fmtPct, fmtDate, MONTHS_SHORT } from "@/lib/formatters";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
  AreaChart, Area,
} from "recharts";

const PERIODS = ["6m", "1y", "2y", "5y"];

export default function AnalyticsPage() {
  const [period, setPeriod] = useState("2y");
  const { data, isLoading } = useQuery({
    queryKey: ["analytics", period],
    queryFn: () => fetchAnalytics(period),
  });

  if (isLoading) return <div className="text-bloomberg-muted text-xs p-4">Computing analytics…</div>;
  if (!data) return null;

  const { metrics, rolling, monthly_returns, drawdown_episodes, portfolio_series, benchmark_series } = data;

  // Merge portfolio + benchmark series for charting
  const perfMap: Record<string, { portfolio?: number; benchmark?: number }> = {};
  portfolio_series.forEach((p) => { perfMap[p.date] = { portfolio: p.value }; });
  benchmark_series.forEach((b) => {
    if (!perfMap[b.date]) perfMap[b.date] = {};
    perfMap[b.date].benchmark = b.value;
  });
  const perfData = Object.entries(perfMap)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, v]) => ({ date, portfolio: v.portfolio, benchmark: v.benchmark }));

  // Monthly returns heatmap
  const years = [...new Set(monthly_returns.map((m) => m.year))].sort();

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Analytics</h1>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button key={p} onClick={() => setPeriod(p)}
              className={`text-[10px] px-2 py-1 border ${period === p ? "border-bloomberg-gold text-bloomberg-gold" : "border-bloomberg-border text-bloomberg-muted hover:border-bloomberg-muted"}`}>
              {p.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <MetricCard label="TWR" value={metrics.twr != null ? fmtPct(metrics.twr) : "—"} deltaPositive={(metrics.twr ?? 0) >= 0} />
        <MetricCard label="Ann. Return" value={metrics.annualized_return != null ? fmtPct(metrics.annualized_return) : "—"} deltaPositive={(metrics.annualized_return ?? 0) >= 0} />
        <MetricCard label="Sharpe" value={metrics.sharpe?.toFixed(3) ?? "—"} />
        <MetricCard label="Sortino" value={metrics.sortino?.toFixed(3) ?? "—"} />
        <MetricCard label="Max DD" value={metrics.max_drawdown != null ? fmtPct(metrics.max_drawdown) : "—"} deltaPositive={false} />
        <MetricCard label="Volatility" value={metrics.annualized_vol != null ? fmtPct(metrics.annualized_vol) : "—"} />
        <MetricCard label="Alpha" value={metrics.alpha != null ? fmtPct(metrics.alpha) : "—"} deltaPositive={(metrics.alpha ?? 0) >= 0} sub={`vs ${metrics.benchmark_ticker}`} />
        <MetricCard label="Beta" value={metrics.beta?.toFixed(3) ?? "—"} />
        <MetricCard label="Calmar" value={metrics.calmar?.toFixed(3) ?? "—"} />
        <MetricCard label="Info Ratio" value={metrics.information_ratio?.toFixed(3) ?? "—"} />
      </div>

      {/* Cumulative returns chart */}
      <div className="bbg-card">
        <p className="bbg-header">Cumulative Return vs {metrics.benchmark_ticker}</p>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={perfData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
            <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false}
              tickFormatter={(v) => `${v.toFixed(0)}%`} width={40} />
            <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
              formatter={(v: number) => [`${v?.toFixed(2)}%`]} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Line type="monotone" dataKey="portfolio" stroke="#f3a712" strokeWidth={1.5} dot={false} name="Portfolio" />
            <Line type="monotone" dataKey="benchmark" stroke="#8a9bb5" strokeWidth={1} dot={false} name={metrics.benchmark_ticker} strokeDasharray="4 4" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Rolling Sharpe */}
      {rolling.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Rolling Sharpe Ratio</p>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={rolling} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false} width={35} />
              <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }} />
              <Line type="monotone" dataKey="sharpe" stroke="#f3a712" strokeWidth={1.5} dot={false} />
              <Line type="monotone" dataKey="sortino" stroke="#38b2ff" strokeWidth={1} dot={false} strokeDasharray="3 3" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Monthly returns calendar */}
      {monthly_returns.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Monthly Returns</p>
          <div className="overflow-x-auto">
            <table className="bbg-table text-center">
              <thead>
                <tr>
                  <th className="text-left">Year</th>
                  {MONTHS_SHORT.map((m) => <th key={m}>{m}</th>)}
                  <th>Full Yr</th>
                </tr>
              </thead>
              <tbody>
                {years.map((yr) => {
                  const yearData = monthly_returns.filter((m) => m.year === yr);
                  const annual = yearData.reduce((acc, m) => acc * (1 + (m.portfolio_return ?? 0) / 100), 1) - 1;
                  return (
                    <tr key={yr}>
                      <td className="text-bloomberg-gold text-left">{yr}</td>
                      {Array.from({ length: 12 }, (_, i) => {
                        const m = yearData.find((d) => d.month === i + 1);
                        const v = m?.portfolio_return;
                        return (
                          <td key={i} className={v == null ? "muted" : v >= 0 ? "positive" : "negative"}>
                            {v != null ? `${v.toFixed(1)}%` : "—"}
                          </td>
                        );
                      })}
                      <td className={annual >= 0 ? "positive font-medium" : "negative font-medium"}>
                        {fmtPct(annual * 100)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Drawdown episodes */}
      {drawdown_episodes.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Top Drawdown Episodes</p>
          <table className="bbg-table">
            <thead>
              <tr><th>Start</th><th>Trough</th><th>Recovery</th><th className="text-right">Depth</th><th className="text-right">Duration</th></tr>
            </thead>
            <tbody>
              {drawdown_episodes.slice(0, 5).map((d, i) => (
                <tr key={i}>
                  <td className="text-bloomberg-muted">{fmtDate(d.start)}</td>
                  <td className="text-bloomberg-muted">{fmtDate(d.trough)}</td>
                  <td className="text-bloomberg-muted">{d.end ? fmtDate(d.end) : "Ongoing"}</td>
                  <td className="text-right negative">{fmtPct(d.depth)}</td>
                  <td className="text-right text-bloomberg-muted">{d.duration_days}d</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
