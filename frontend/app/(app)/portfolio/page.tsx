"use client";
import { useState, useCallback, memo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchPositions, upsertPosition, deletePosition } from "@/lib/api/portfolio";
import { fetchCash } from "@/lib/api/transactions";
import { fetchAnalytics, fetchRebalancing, fetchFxExposure } from "@/lib/api/analytics";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { fmtCurrency, fmtPct, colorClass } from "@/lib/formatters";
import { useSettingsStore } from "@/lib/store/settingsStore";
import { Plus, Trash2 } from "lucide-react";
import type { Position } from "@/lib/types";
import { BarChart as TremorBarChart } from "@tremor/react";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
  XAxis, YAxis, CartesianGrid,
  LineChart, Line,
} from "recharts";

const COLORS = ["#f3a712", "#4dff4d", "#ff4d4d", "#38b2ff", "#c084fc", "#fb923c", "#34d399"];

function inferCurrency(ticker: string): string {
  const t = ticker.trim().toUpperCase();
  if (["IGLN.L", "IGLN.UK", "EIMI.UK", "EIMI.L"].includes(t)) return "USD";
  if (t.endsWith(".DE") || t.endsWith(".PA") || t.endsWith(".AM") ||
      t.endsWith(".MI") || t.endsWith(".BR") || t.endsWith(".VI") || t.endsWith(".MC")) return "EUR";
  if (t.endsWith(".L") || t.endsWith(".UK")) return "GBP";
  if (t.endsWith(".AX")) return "AUD";
  return "USD";
}

import type { PortfolioRow } from "@/lib/types";

const PositionRow = memo(function PositionRow({
  row, ccy, onDelete,
}: { row: PortfolioRow; ccy: string; onDelete: (ticker: string) => void }) {
  return (
    <tr key={row.ticker}>
      <td className="text-bloomberg-gold font-medium">{row.ticker}</td>
      <td className="text-bloomberg-muted hidden sm:table-cell max-w-[120px] truncate">{row.name}</td>
      <td className="text-right hidden md:table-cell">{fmtCurrency(row.price_native, row.currency)}</td>
      <td className={`text-right ${colorClass(row.change_pct_1d)}`}>{fmtPct(row.change_pct_1d)}</td>
      <td className="text-right text-bloomberg-muted hidden sm:table-cell">{row.shares.toFixed(4)}</td>
      <td className="text-right">{fmtCurrency(row.value_base, ccy)}</td>
      <td className={`text-right hidden sm:table-cell ${colorClass(row.unrealized_pnl)}`}>
        {row.unrealized_pnl != null ? fmtCurrency(row.unrealized_pnl, ccy) : "—"}
      </td>
      <td className={`text-right ${colorClass(row.unrealized_pnl_pct)}`}>{fmtPct(row.unrealized_pnl_pct)}</td>
      <td className="text-right text-bloomberg-muted hidden md:table-cell">{row.weight.toFixed(1)}%</td>
      <td className="text-bloomberg-muted text-[10px] hidden lg:table-cell">{row.data_source}</td>
      <td>
        <button
          onClick={() => { if (confirm(`Delete ${row.ticker}?`)) onDelete(row.ticker); }}
          className="text-bloomberg-muted hover:text-bloomberg-red"
        >
          <Trash2 size={11} />
        </button>
      </td>
    </tr>
  );
});

export default function PortfolioPage() {
  const { data: positions, isLoading } = useQuery({ queryKey: ["positions"], queryFn: fetchPositions, staleTime: 5 * 60 * 1000 });
  const { data: cash } = useQuery({ queryKey: ["cash"], queryFn: fetchCash, staleTime: 5 * 60 * 1000 });
  const { data: portfolio } = usePortfolio();
  const { data: rebalancing } = useQuery({ queryKey: ["rebalancing", 0, "broker"], queryFn: () => fetchRebalancing({}), staleTime: 5 * 60 * 1000 });
  const { data: analytics } = useQuery({ queryKey: ["analytics", "1y"], queryFn: () => fetchAnalytics("1y"), staleTime: 5 * 60 * 1000 });
  const { data: fx } = useQuery({ queryKey: ["fxexposure"], queryFn: fetchFxExposure, staleTime: 5 * 60 * 1000 });

  const qc = useQueryClient();
  const base_currency = useSettingsStore((s) => s.base_currency);
  const cost_basis_usd = useSettingsStore((s) => s.cost_basis_usd);
  const ccy = portfolio?.base_currency || base_currency;

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ticker: "", name: "", shares: "", avg_cost_native: "", currency: "USD" });


  const addMutation = useMutation({
    mutationFn: upsertPosition,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["positions"] });
      qc.invalidateQueries({ queryKey: ["portfolio"] });
      qc.invalidateQueries({ queryKey: ["cash"] });
      qc.invalidateQueries({ queryKey: ["rebalancing"] });
      qc.invalidateQueries({ queryKey: ["analytics"] });
      qc.invalidateQueries({ queryKey: ["fxexposure"] });
      qc.invalidateQueries({ queryKey: ["portfolioBreakdown"] });
      setShowForm(false);
      setForm({ ticker: "", name: "", shares: "", avg_cost_native: "", currency: "USD" });
    },
  });

  const delMutation = useMutation({
    mutationFn: deletePosition,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["positions"] });
      qc.invalidateQueries({ queryKey: ["portfolio"] });
      qc.invalidateQueries({ queryKey: ["cash"] });
      qc.invalidateQueries({ queryKey: ["rebalancing"] });
      qc.invalidateQueries({ queryKey: ["analytics"] });
      qc.invalidateQueries({ queryKey: ["fxexposure"] });
      qc.invalidateQueries({ queryKey: ["portfolioBreakdown"] });
    },
  });

  const handleDelete = useCallback((ticker: string) => delMutation.mutate(ticker), [delMutation]);

  if (isLoading) return <div className="text-bloomberg-muted text-xs p-4">Loading…</div>;

  // Current Return: (current value - cost basis) / cost basis
  const INCEPTION_DATE = "2026-03-26";
  const totalValue = portfolio?.total_value_base ?? 0;
  const invested = portfolio?.total_invested_base ?? 0;
  // Prefer backend-computed invested_base (avg_cost × shares × FX, kept accurate by broker agent).
  // Fall back to manual cost_basis_usd only when backend has nothing.
  const basis = invested > 0 ? invested : (cost_basis_usd ?? 0);
  const currentReturnVal = basis > 0 ? totalValue - basis : null;
  const currentReturnPct = basis > 0 ? ((totalValue - basis) / basis) * 100 : null;

  // Allocation pie data from portfolio
  const pieData = (portfolio?.rows ?? []).map((r) => ({ name: r.ticker, value: r.value_base }));

  // Weight vs Target from rebalancing
  // Backend already returns weights as percentages (e.g. 20.76 for 20.76%)
  const weightData = (rebalancing ?? []).map((r) => ({
    ticker: r.ticker,
    "Current%": r.current_weight,
    "Target%": r.target_weight,
  }));

  // Performance vs benchmark from analytics
  const perfMap: Record<string, { portfolio?: number; benchmark?: number }> = {};
  (analytics?.portfolio_series ?? []).forEach((p) => { perfMap[p.date] = { portfolio: p.value }; });
  (analytics?.benchmark_series ?? []).forEach((b) => {
    if (!perfMap[b.date]) perfMap[b.date] = {};
    perfMap[b.date].benchmark = b.value;
  });
  const perfData = Object.entries(perfMap)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, v]) => ({ date, portfolio: v.portfolio, benchmark: v.benchmark }))
    .filter((_, i, arr) => i % Math.max(1, Math.floor(arr.length / 60)) === 0); // downsample

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Portfolio</h1>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 text-[10px] text-bloomberg-muted border border-bloomberg-border px-3 py-1.5 hover:text-bloomberg-gold hover:border-bloomberg-gold"
        >
          <Plus size={11} /> Add Position
        </button>
      </div>

      {/* Add form */}
      {showForm && (
        <div className="bbg-card">
          <p className="bbg-header">New Position</p>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {(["ticker", "name", "shares", "avg_cost_native", "currency"] as const).map((field) => (
              <div key={field}>
                <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">{field}</label>
                <input
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
                  value={form[field]}
                  onChange={(e) => {
                    const val = e.target.value;
                    if (field === "ticker") {
                      setForm((f) => ({ ...f, ticker: val.toUpperCase(), currency: inferCurrency(val) }));
                    } else {
                      setForm((f) => ({ ...f, [field]: val }));
                    }
                  }}
                />
              </div>
            ))}
          </div>
          <div className="flex gap-2 mt-3">
            <button
              onClick={() => addMutation.mutate({
                ticker: form.ticker.toUpperCase(),
                name: form.name || form.ticker.toUpperCase(),
                shares: parseFloat(form.shares) || 0,
                avg_cost_native: form.avg_cost_native ? parseFloat(form.avg_cost_native) : undefined,
                currency: form.currency || "USD",
              })}
              className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-4 py-1 hover:opacity-90"
            >
              SAVE
            </button>
            <button onClick={() => setShowForm(false)} className="text-bloomberg-muted text-xs px-3 py-1 border border-bloomberg-border hover:text-bloomberg-text">
              CANCEL
            </button>
          </div>
        </div>
      )}

      {/* Current Return metric */}
      {currentReturnPct != null && currentReturnVal != null && (
        <div className="bbg-card flex items-center justify-between">
          <div>
            <p className="text-bloomberg-muted text-[10px] uppercase tracking-widest mb-0.5">Current Return</p>
            <p className="text-[11px] text-bloomberg-muted">since {INCEPTION_DATE}</p>
          </div>
          <div className="text-right">
            <p className={`text-2xl font-bold ${currentReturnPct >= 0 ? "text-green-400" : "text-red-400"}`}>
              {currentReturnPct >= 0 ? "+" : "-"}{Math.abs(currentReturnPct).toFixed(2)}%
            </p>
            <p className={`text-xs mt-0.5 ${currentReturnVal >= 0 ? "text-green-400" : "text-red-400"}`}>
              {currentReturnVal >= 0 ? "+" : ""}{fmtCurrency(currentReturnVal, ccy)}
            </p>
          </div>
        </div>
      )}

      {/* Intraday + Monthly table */}
      {portfolio && (
        <div className="bbg-card">
          <p className="bbg-header">Holdings · Intraday & Monthly</p>
          <div className="overflow-x-auto">
            <table className="bbg-table">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th className="hidden sm:table-cell">Name</th>
                  <th className="text-right hidden md:table-cell">Price</th>
                  <th className="text-right">1D%</th>
                  <th className="text-right hidden sm:table-cell">Shares</th>
                  <th className="text-right">Value</th>
                  <th className="text-right hidden sm:table-cell">P&L</th>
                  <th className="text-right">P&L%</th>
                  <th className="text-right hidden md:table-cell">Weight%</th>
                  <th className="hidden lg:table-cell">Src</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {portfolio.rows.map((row) => (
                  <PositionRow key={row.ticker} row={row} ccy={ccy} onDelete={handleDelete} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Charts row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Allocation donut */}
        {pieData.length > 0 && (
          <div className="bbg-card">
            <p className="bbg-header">Allocation</p>
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={55} outerRadius={85}
                  paddingAngle={2} dataKey="value">
                  {pieData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Pie>
                <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                  formatter={(v: number) => fmtCurrency(v, ccy)} />
                <Legend iconSize={8} wrapperStyle={{ fontSize: 10 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Weight vs Target */}
        {weightData.length > 0 && (
          <div className="bbg-card">
            <p className="bbg-header">Weight vs Target</p>
            <TremorBarChart
              data={weightData}
              index="ticker"
              categories={["Current%", "Target%"]}
              colors={["amber", "blue"]}
              valueFormatter={(v) => `${v.toFixed(1)}%`}
              showLegend
              className="h-44 mt-2"
            />
          </div>
        )}
      </div>

      {/* Performance vs Benchmark */}
      {perfData.length > 1 && (
        <div className="bbg-card">
          <p className="bbg-header">Performance vs {analytics?.metrics.benchmark_ticker ?? "VOO"} (1Y)</p>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={perfData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false}
                tickFormatter={(v) => `${v?.toFixed(0)}%`} width={40} />
              <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                formatter={(v: number) => `${v?.toFixed(2)}%`} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Line type="monotone" dataKey="portfolio" stroke="#f3a712" strokeWidth={1.5} dot={false} name="Portfolio" />
              <Line type="monotone" dataKey="benchmark" stroke="#8a9bb5" strokeWidth={1} dot={false}
                name={analytics?.metrics.benchmark_ticker ?? "VOO"} strokeDasharray="4 4" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Currency Exposure */}
      {fx && Object.keys(fx).length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Currency Exposure</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {Object.entries(fx as Record<string, number>)
              .sort(([, a], [, b]) => b - a)
              .map(([currency, pct]) => (
                <div key={currency} className="text-center">
                  <p className="text-bloomberg-gold text-sm font-bold">{currency}</p>
                  <p className="text-bloomberg-text text-xs">{fmtPct(pct)}</p>
                  <div className="mt-1 h-1 bg-bloomberg-border rounded">
                    <div className="h-1 rounded" style={{ width: `${Math.min(pct, 100)}%`, background: "#f3a712" }} />
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Positions management table */}
      <div className="bbg-card">
        <p className="bbg-header">Position Records</p>
        <div className="overflow-x-auto">
          <table className="bbg-table">
            <thead>
              <tr>
                <th>Ticker</th><th>Name</th>
                <th className="text-right">Shares</th>
                <th className="text-right">Avg Cost</th>
                <th>Currency</th><th>Market</th><th></th>
              </tr>
            </thead>
            <tbody>
              {(positions || []).map((p: Position) => (
                <tr key={p.id}>
                  <td className="text-bloomberg-gold font-medium">{p.ticker}</td>
                  <td className="text-bloomberg-muted">{p.name}</td>
                  <td className="text-right">{p.shares.toFixed(4)}</td>
                  <td className="text-right">{p.avg_cost_native != null ? fmtCurrency(p.avg_cost_native, p.currency) : "—"}</td>
                  <td>{p.currency}</td>
                  <td className="text-bloomberg-muted">{p.market}</td>
                  <td>
                    <button onClick={() => { if (confirm(`Delete ${p.ticker}?`)) delMutation.mutate(p.ticker); }}
                      className="text-bloomberg-muted hover:text-bloomberg-red">
                      <Trash2 size={11} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Cash balances */}
      {cash && cash.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Cash Balances</p>
          <table className="bbg-table">
            <thead><tr><th>Account</th><th>Currency</th><th className="text-right">Amount</th></tr></thead>
            <tbody>
              {cash.map((c, i) => (
                <tr key={i}>
                  <td className="text-bloomberg-muted">{c.account_name || "—"}</td>
                  <td>{c.currency}</td>
                  <td className="text-right">{fmtCurrency(c.amount, c.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
