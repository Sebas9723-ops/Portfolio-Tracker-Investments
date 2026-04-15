"use client";
import { usePortfolio, useSaveSnapshot } from "@/lib/hooks/usePortfolio";
import { MetricCard } from "@/components/shared/MetricCard";
import { fmtCurrency, fmtPct, colorClass, fmtDate } from "@/lib/formatters";
import { useSettingsStore } from "@/lib/store/settingsStore";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
} from "recharts";
import { useSnapshots } from "@/lib/hooks/usePortfolio";
import { Save, RefreshCw } from "lucide-react";

const COLORS = ["#f3a712", "#4dff4d", "#ff4d4d", "#38b2ff", "#c084fc", "#fb923c", "#34d399"];

export default function DashboardPage() {
  const { data: portfolio, isLoading, isFetching } = usePortfolio();
  const { data: snapshots } = useSnapshots();
  const { mutate: saveSnap, isPending: saving } = useSaveSnapshot();
  const base_currency = useSettingsStore((s) => s.base_currency);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-bloomberg-muted text-xs">
        Loading portfolio…
      </div>
    );
  }

  if (!portfolio || portfolio.rows.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-bloomberg-muted text-xs">
        No positions found. Add positions in the Portfolio page.
      </div>
    );
  }

  const ccy = portfolio.base_currency || base_currency;
  const pieData = portfolio.rows.map((r) => ({ name: r.ticker, value: r.value_base }));

  // Snapshot chart data
  const chartData = snapshots
    ?.slice()
    .sort((a, b) => a.snapshot_date.localeCompare(b.snapshot_date))
    .map((s) => ({
      date: s.snapshot_date,
      value: s.total_value_base ?? 0,
    })) ?? [];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Dashboard</h1>
          <p className="text-bloomberg-muted text-[10px]">
            As of {fmtDate(portfolio.as_of)} · {ccy}
            {isFetching && " · refreshing…"}
          </p>
        </div>
        <button
          onClick={() => saveSnap()}
          disabled={saving}
          className="flex items-center gap-1.5 text-[10px] text-bloomberg-muted border border-bloomberg-border px-3 py-1.5 hover:text-bloomberg-gold hover:border-bloomberg-gold"
        >
          {saving ? <RefreshCw size={11} className="animate-spin" /> : <Save size={11} />}
          Save Snapshot
        </button>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          label="Total Value"
          value={fmtCurrency(portfolio.total_value_base, ccy)}
          delta={portfolio.total_day_change_base != null
            ? `${fmtCurrency(portfolio.total_day_change_base, ccy)} today`
            : undefined}
          deltaPositive={(portfolio.total_day_change_base ?? 0) >= 0}
        />
        <MetricCard
          label="Invested"
          value={portfolio.total_invested_base != null
            ? fmtCurrency(portfolio.total_invested_base, ccy)
            : "—"}
        />
        <MetricCard
          label="Unrealized P&L"
          value={portfolio.total_unrealized_pnl != null
            ? fmtCurrency(portfolio.total_unrealized_pnl, ccy)
            : "—"}
          delta={portfolio.total_unrealized_pnl_pct != null
            ? fmtPct(portfolio.total_unrealized_pnl_pct)
            : undefined}
          deltaPositive={(portfolio.total_unrealized_pnl ?? 0) >= 0}
        />
        <MetricCard
          label="Positions"
          value={String(portfolio.rows.length)}
          sub={`${portfolio.rows.filter((r) => (r.unrealized_pnl ?? 0) >= 0).length} winning`}
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Allocation pie */}
        <div className="bbg-card">
          <p className="bbg-header">Allocation</p>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={90}
                paddingAngle={2}
                dataKey="value"
              >
                {pieData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                formatter={(v: number) => fmtCurrency(v, ccy)}
              />
              <Legend
                iconSize={8}
                wrapperStyle={{ fontSize: 11 }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Portfolio value history */}
        <div className="bbg-card">
          <p className="bbg-header">Portfolio Value History</p>
          {chartData.length > 1 ? (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
                <defs>
                  <linearGradient id="goldGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f3a712" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#f3a712" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#8a9bb5" }} tickLine={false}
                  interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 10, fill: "#8a9bb5" }} tickLine={false} axisLine={false}
                  tickFormatter={(v) => fmtCurrency(v, ccy, true)} width={60} />
                <Tooltip
                  contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                  formatter={(v: number) => [fmtCurrency(v, ccy), "Value"]}
                />
                <Area type="monotone" dataKey="value" stroke="#f3a712" strokeWidth={1.5}
                  fill="url(#goldGrad)" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-52 text-bloomberg-muted text-xs">
              Save snapshots daily to build history
            </div>
          )}
        </div>
      </div>

      {/* Holdings table */}
      <div className="bbg-card">
        <p className="bbg-header">Holdings</p>
        <div className="overflow-x-auto">
          <table className="bbg-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Name</th>
                <th className="text-right">Price</th>
                <th className="text-right">1D%</th>
                <th className="text-right">Shares</th>
                <th className="text-right">Value</th>
                <th className="text-right">P&L</th>
                <th className="text-right">P&L%</th>
                <th className="text-right">Weight%</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.rows.map((row) => (
                <tr key={row.ticker}>
                  <td className="text-bloomberg-gold font-medium">{row.ticker}</td>
                  <td className="text-bloomberg-muted">{row.name}</td>
                  <td className="text-right">{fmtCurrency(row.price_native, row.currency)}</td>
                  <td className={`text-right ${colorClass(row.change_pct_1d)}`}>
                    {fmtPct(row.change_pct_1d)}
                  </td>
                  <td className="text-right text-bloomberg-muted">{row.shares.toFixed(4)}</td>
                  <td className="text-right">{fmtCurrency(row.value_base, ccy)}</td>
                  <td className={`text-right ${colorClass(row.unrealized_pnl)}`}>
                    {row.unrealized_pnl != null ? fmtCurrency(row.unrealized_pnl, ccy) : "—"}
                  </td>
                  <td className={`text-right ${colorClass(row.unrealized_pnl_pct)}`}>
                    {fmtPct(row.unrealized_pnl_pct)}
                  </td>
                  <td className="text-right text-bloomberg-muted">{row.weight.toFixed(1)}%</td>
                  <td className="text-bloomberg-muted text-[10px]">{row.data_source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
