"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchRebalancing } from "@/lib/api/analytics";
import { fmtCurrency, fmtPct, colorClass } from "@/lib/formatters";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";

export default function RebalancingPage() {
  const [contribution, setContribution] = useState(0);
  const [tcModel, setTcModel] = useState("broker");

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["rebalancing", contribution, tcModel],
    queryFn: () => fetchRebalancing({ contribution, tc_model: tcModel }),
  });

  const totalTC = data?.reduce((s, r) => s + r.estimated_tc, 0) ?? 0;
  const buys = data?.filter((r) => r.trade_direction === "BUY") ?? [];
  const sells = data?.filter((r) => r.trade_direction === "SELL") ?? [];

  return (
    <div className="space-y-4">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Rebalancing</h1>

      <div className="bbg-card">
        <p className="bbg-header">Parameters</p>
        <div className="flex gap-6 items-end">
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Cash to Deploy</label>
            <input type="number" value={contribution}
              onChange={(e) => setContribution(parseFloat(e.target.value) || 0)}
              className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs w-32 focus:outline-none focus:border-bloomberg-gold"
              step="100" />
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Broker Model</label>
            <select value={tcModel} onChange={(e) => setTcModel(e.target.value)}
              className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs">
              {["broker", "etoro", "degiro", "ib"].map((m) => <option key={m}>{m}</option>)}
            </select>
          </div>
          <div className="text-bloomberg-muted text-xs">
            Est. total TC: <span className="text-bloomberg-gold">{fmtCurrency(totalTC)}</span>
          </div>
        </div>
      </div>

      {/* Drift chart */}
      {data && data.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Drift vs Target</p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 20 }} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false}
                tickFormatter={(v) => `${v.toFixed(1)}%`} />
              <YAxis dataKey="ticker" type="category" tick={{ fontSize: 10, fill: "#f3a712" }} tickLine={false} axisLine={false} width={60} />
              <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                formatter={(v: number) => [`${v.toFixed(2)}%`]} />
              <Bar dataKey="drift" barSize={12}>
                {data.map((r) => (
                  <Cell key={r.ticker} fill={r.drift > 0 ? "#ff4d4d" : r.drift < 0 ? "#4dff4d" : "#1e2535"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Trade table */}
      <div className="bbg-card">
        {isLoading ? (
          <div className="text-bloomberg-muted text-xs py-4">Loading…</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="bbg-table">
              <thead>
                <tr>
                  <th>Ticker</th><th>Name</th>
                  <th className="text-right">Current%</th>
                  <th className="text-right">Target%</th>
                  <th className="text-right">Drift%</th>
                  <th className="text-right">Trade $</th>
                  <th>Direction</th>
                  <th className="text-right">Est. TC</th>
                </tr>
              </thead>
              <tbody>
                {(data ?? []).map((r) => (
                  <tr key={r.ticker}>
                    <td className="text-bloomberg-gold font-medium">{r.ticker}</td>
                    <td className="text-bloomberg-muted">{r.name}</td>
                    <td className="text-right">{fmtPct(r.current_weight)}</td>
                    <td className="text-right">{fmtPct(r.target_weight)}</td>
                    <td className={`text-right ${colorClass(r.drift > 0 ? -1 : 1)}`}>{fmtPct(r.drift)}</td>
                    <td className="text-right">{fmtCurrency(Math.abs(r.trade_value))}</td>
                    <td className={r.trade_direction === "BUY" ? "positive" : r.trade_direction === "SELL" ? "negative" : "muted"}>
                      {r.trade_direction}
                    </td>
                    <td className="text-right text-bloomberg-muted">{fmtCurrency(r.estimated_tc)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
