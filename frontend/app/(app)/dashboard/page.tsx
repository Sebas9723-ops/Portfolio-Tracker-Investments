"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { usePortfolio, useSnapshots, useSaveSnapshot, usePortfolioHistory } from "@/lib/hooks/usePortfolio";
import { fetchTransactions } from "@/lib/api/transactions";
import { updateSettings } from "@/lib/api/settings";
import { fmtCurrency, fmtPct, fmtDate } from "@/lib/formatters";
import { useSettingsStore } from "@/lib/store/settingsStore";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from "recharts";
import { PortfolioLWChart } from "@/components/charts/PortfolioLWChart";
import { Save, RefreshCw, TrendingUp, TrendingDown } from "lucide-react";
import Link from "next/link";

// ── Colors ────────────────────────────────────────────────────────────────────
const PIE_COLORS = ["#f3a712", "#38b2ff", "#4dff4d", "#c084fc", "#fb923c", "#34d399", "#ff6b6b", "#60a5fa"];

function tickerBadgeColor(ticker: string): string {
  let h = 0;
  for (let i = 0; i < ticker.length; i++) h = ticker.charCodeAt(i) + ((h << 5) - h);
  return PIE_COLORS[Math.abs(h) % PIE_COLORS.length];
}

// ── Period filter ─────────────────────────────────────────────────────────────
const PERIODS = ["1W", "1M", "YTD", "1Y", "Max"] as const;
type Period = typeof PERIODS[number];

function filterHistory(data: { date: string; value: number }[], period: Period) {
  const ms = (d: number) => d * 864e5;
  const now = new Date();
  const cutoffs: Record<Period, Date | null> = {
    "1W":  new Date(Date.now() - ms(7)),
    "1M":  new Date(Date.now() - ms(30)),
    "YTD": new Date(now.getFullYear(), 0, 1),
    "1Y":  new Date(Date.now() - ms(365)),
    "Max": null,
  };
  const c = cutoffs[period];
  if (!c) return data;
  return data.filter((d) => new Date(d.date) >= c!);
}

// ── Center label for donut ────────────────────────────────────────────────────
function DonutCenter({ cx, cy, value, ccy }: { cx: number; cy: number; value: number; ccy: string }) {
  return (
    <g>
      <text x={cx} y={cy - 10} textAnchor="middle" fill="#64748b" fontSize={9} fontFamily="IBM Plex Mono, monospace">
        Total Net Worth
      </text>
      <text x={cx} y={cy + 12} textAnchor="middle" fill="#0f172a" fontSize={16} fontWeight="bold" fontFamily="IBM Plex Mono, monospace">
        {fmtCurrency(value, ccy, true)}
      </text>
    </g>
  );
}

// ── Badge ─────────────────────────────────────────────────────────────────────
function TickerBadge({ ticker }: { ticker: string }) {
  const color = tickerBadgeColor(ticker);
  const initials = ticker.replace(/[^A-Z]/g, "").slice(0, 2) || ticker.slice(0, 2).toUpperCase();
  return (
    <span
      className="inline-flex items-center justify-center w-8 h-8 rounded-full text-[10px] font-bold text-bloomberg-bg shrink-0"
      style={{ backgroundColor: color }}
    >
      {initials}
    </span>
  );
}

// ── Positive/negative ─────────────────────────────────────────────────────────
function Chg({ v, pct = false, className = "" }: { v: number | null | undefined; pct?: boolean; className?: string }) {
  if (v == null) return <span className="text-bloomberg-muted">—</span>;
  const pos = v >= 0;
  return (
    <span className={`flex items-center gap-0.5 ${pos ? "text-green-400" : "text-red-400"} ${className}`}>
      {pos ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
      {pct ? fmtPct(v) : `${pos ? "+" : ""}${v.toFixed(2)}`}
    </span>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const [chartPeriod, setChartPeriod] = useState<Period>("Max");
  const [editingBasis, setEditingBasis] = useState(false);
  const [basisInput, setBasisInput] = useState("");

  const { data: portfolio, isLoading, isFetching } = usePortfolio();
  const { mutate: saveSnap, isPending: saving } = useSaveSnapshot();
  const { data: historyData, isLoading: historyLoading } = usePortfolioHistory();
  const { data: transactions } = useQuery({ queryKey: ["transactions"], queryFn: fetchTransactions });
  const qc = useQueryClient();
  const base_currency = useSettingsStore((s) => s.base_currency);
  const cost_basis_usd = useSettingsStore((s) => s.cost_basis_usd);
  const setSettings = useSettingsStore((s) => s.setSettings);

  const { mutate: saveBasis } = useMutation({
    mutationFn: (v: number) => updateSettings({ cost_basis_usd: v }),
    onSuccess: (data) => { setSettings(data); qc.invalidateQueries({ queryKey: ["settings"] }); },
  });

  if (isLoading) {
    return <div className="flex items-center justify-center h-64 text-bloomberg-muted text-xs">Loading portfolio…</div>;
  }
  if (!portfolio || portfolio.rows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-bloomberg-muted text-xs">
        <p>No positions found.</p>
        <Link href="/manage" className="text-bloomberg-gold border border-bloomberg-gold px-4 py-1.5 text-[10px] hover:opacity-80">
          + Add Positions
        </Link>
      </div>
    );
  }

  const ccy = portfolio.base_currency || base_currency;
  const totalValue = portfolio.total_value_base;
  const dayChange = portfolio.total_day_change_base ?? 0;
  const dayChangePct = totalValue > 0 ? (dayChange / (totalValue - dayChange)) * 100 : 0;

  // Chart data — from automatic history (historical prices × shares)
  const allHistory = (historyData ?? []).slice().sort((a, b) => a.date.localeCompare(b.date));
  const chartData = filterHistory(allHistory, chartPeriod);

  // Period P&L from chart range
  const periodStart = chartData[0]?.value ?? totalValue;
  const periodChange = totalValue - periodStart;
  const periodChangePct = periodStart > 0 ? (periodChange / periodStart) * 100 : 0;

  // Allocation donut
  const pieData = portfolio.rows.map((r) => ({ name: r.ticker, value: r.value_base }));

  // Dividend transactions
  const divTxs = (transactions ?? []).filter((t) => t.action === "DIVIDEND");
  const totalDivReceived = divTxs.reduce((s, t) => s + t.quantity * t.price_native, 0);
  const ttmCutoff = new Date(); ttmCutoff.setFullYear(ttmCutoff.getFullYear() - 1);
  const ttmDivs = divTxs
    .filter((t) => new Date(t.date) >= ttmCutoff)
    .reduce((s, t) => s + t.quantity * t.price_native, 0);
  const divYieldTTM = totalValue > 0 ? (ttmDivs / totalValue) * 100 : 0;
  const divYoC = (portfolio.total_invested_base ?? 0) > 0
    ? (ttmDivs / portfolio.total_invested_base!) * 100
    : 0;

  // Dividends by year for bar chart
  const divByYear: Record<number, number> = {};
  divTxs.forEach((t) => {
    const yr = new Date(t.date).getFullYear();
    divByYear[yr] = (divByYear[yr] ?? 0) + t.quantity * t.price_native;
  });
  const divBarData = Object.entries(divByYear)
    .map(([yr, amt]) => ({ year: yr, amount: amt }))
    .sort((a, b) => Number(a.year) - Number(b.year));

  // Performance breakdown
  // When cost_basis_usd is set, use it as the basis so all metrics are FX-correct.
  // Falls back to backend's total_invested_base (current-FX, may drift).
  const invested = portfolio.total_invested_base ?? 0;
  const INCEPTION_DATE = "2026-03-26";
  const basis = cost_basis_usd ?? invested;
  const priceGain = basis > 0 ? totalValue - basis : (portfolio.total_unrealized_pnl ?? 0);
  const priceGainPct = basis > 0 ? ((totalValue - basis) / basis) * 100 : (portfolio.total_unrealized_pnl_pct ?? 0);
  const totalReturn = priceGain + totalDivReceived;
  const winners = portfolio.rows.filter((r) => (r.unrealized_pnl ?? 0) >= 0).length;
  const losers = portfolio.rows.length - winners;

  return (
    <div className="space-y-4">
      {/* Top bar */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Dashboard</h1>
          <p className="text-bloomberg-muted text-[10px]">
            {fmtDate(portfolio.as_of)}{isFetching && " · refreshing…"}
          </p>
        </div>
        <button
          onClick={() => saveSnap(undefined)}
          disabled={saving}
          className="flex items-center gap-1.5 text-[10px] text-bloomberg-muted border border-bloomberg-border px-3 py-1.5 hover:text-bloomberg-gold hover:border-bloomberg-gold"
        >
          {saving ? <RefreshCw size={11} className="animate-spin" /> : <Save size={11} />}
          Save Snapshot
        </button>
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">

        {/* ── LEFT COLUMN ── */}
        <div className="lg:col-span-2 space-y-4">

          {/* Hero: Value + Chart */}
          <div className="bbg-card">
            <div className="flex items-start justify-between mb-1">
              <div>
                <p className="text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">Portfolio</p>
                <div className="flex items-baseline gap-3">
                  <span className="text-bloomberg-text text-4xl font-bold tracking-tight">
                    {fmtCurrency(totalValue, ccy)}
                  </span>
                  {dayChange !== 0 && (
                    <Chg v={dayChangePct} pct className="text-xs" />
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <Chg v={periodChangePct} pct className="text-[10px]" />
                  <span className="text-bloomberg-muted text-[10px]">
                    ({periodChange >= 0 ? "+" : ""}{fmtCurrency(periodChange, ccy)}) · {chartPeriod}
                  </span>
                </div>
              </div>
              {/* Period selector */}
              <div className="flex gap-1 shrink-0">
                {PERIODS.map((p) => (
                  <button
                    key={p}
                    onClick={() => setChartPeriod(p)}
                    className={`text-[10px] px-2 py-0.5 border transition-colors ${
                      chartPeriod === p
                        ? "border-bloomberg-gold text-bloomberg-gold bg-bloomberg-gold/10"
                        : "border-bloomberg-border text-bloomberg-muted hover:border-bloomberg-muted"
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>

            {historyLoading ? (
              <div className="flex items-center justify-center h-40 text-bloomberg-muted text-xs mt-3">
                Loading history…
              </div>
            ) : chartData.length > 1 ? (
              <div className="mt-3">
                <PortfolioLWChart data={chartData} />
              </div>
            ) : (
              <div className="flex items-center justify-center h-40 text-bloomberg-muted text-xs border border-dashed border-bloomberg-border mt-3">
                No price data available for selected period
              </div>
            )}
          </div>

          {/* Positions table */}
          <div className="bbg-card">
            <div className="flex items-center justify-between mb-3">
              <p className="bbg-header mb-0">Positions</p>
              <div className="flex items-center gap-3 text-[10px] text-bloomberg-muted">
                <span className="text-green-400">{winners} ↑</span>
                <span className="text-red-400">{losers} ↓</span>
                <Link href="/manage" className="border border-bloomberg-border px-2 py-0.5 hover:text-bloomberg-gold hover:border-bloomberg-gold">
                  + Add
                </Link>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-bloomberg-border">
                    <th className="text-left pb-2 text-bloomberg-muted text-[10px] font-normal">Title</th>
                    <th className="text-right pb-2 text-bloomberg-muted text-[10px] font-normal">Buy In</th>
                    <th className="text-right pb-2 text-bloomberg-muted text-[10px] font-normal">Position</th>
                    <th className="text-right pb-2 text-bloomberg-muted text-[10px] font-normal">P/L</th>
                    <th className="text-right pb-2 text-bloomberg-muted text-[10px] font-normal">Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {portfolio.rows
                    .slice()
                    .sort((a, b) => b.value_base - a.value_base)
                    .map((row) => {
                      const totalBuyIn = row.avg_cost_native != null ? row.avg_cost_native * row.shares : null;
                      return (
                        <tr key={row.ticker} className="border-b border-bloomberg-border/40 hover:bg-bloomberg-card transition-colors">
                          {/* Badge + name */}
                          <td className="py-3 pr-4">
                            <div className="flex items-center gap-2.5">
                              <TickerBadge ticker={row.ticker} />
                              <div className="min-w-0">
                                <p className="text-bloomberg-text font-medium truncate max-w-[180px]">{row.name}</p>
                                <p className="text-bloomberg-muted text-[10px]">
                                  {row.ticker} · {row.shares.toFixed(3)} shares
                                </p>
                              </div>
                            </div>
                          </td>
                          {/* Buy in */}
                          <td className="py-3 text-right">
                            {totalBuyIn != null ? (
                              <>
                                <p className="text-bloomberg-text">{fmtCurrency(totalBuyIn, row.currency)}</p>
                                <p className="text-bloomberg-muted text-[10px]">
                                  {fmtCurrency(row.avg_cost_native!, row.currency)} avg
                                </p>
                              </>
                            ) : (
                              <span className="text-bloomberg-muted">—</span>
                            )}
                          </td>
                          {/* Position */}
                          <td className="py-3 text-right">
                            <p className="text-bloomberg-text font-medium">{fmtCurrency(row.value_base, ccy)}</p>
                            <p className="text-bloomberg-muted text-[10px]">
                              {fmtCurrency(row.price_native, row.currency)}
                              {row.change_pct_1d != null && (
                                <span className={row.change_pct_1d >= 0 ? " text-green-400" : " text-red-400"}>
                                  {" "}{fmtPct(row.change_pct_1d)}
                                </span>
                              )}
                            </p>
                          </td>
                          {/* P/L */}
                          <td className="py-3 text-right">
                            {row.unrealized_pnl != null ? (
                              <>
                                <p className={row.unrealized_pnl >= 0 ? "text-green-400 font-medium" : "text-red-400 font-medium"}>
                                  {row.unrealized_pnl >= 0 ? "+" : ""}{fmtCurrency(row.unrealized_pnl, ccy)}
                                </p>
                                <p className={`text-[10px] ${row.unrealized_pnl_pct != null && row.unrealized_pnl_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                                  {fmtPct(row.unrealized_pnl_pct)}
                                </p>
                              </>
                            ) : (
                              <span className="text-bloomberg-muted">—</span>
                            )}
                          </td>
                          {/* Weight */}
                          <td className="py-3 text-right">
                            <p className="text-bloomberg-muted">{row.weight.toFixed(1)}%</p>
                            <div className="w-12 h-0.5 bg-bloomberg-border ml-auto mt-1 rounded">
                              <div
                                className="h-0.5 rounded"
                                style={{ width: `${Math.min(row.weight, 100)}%`, backgroundColor: tickerBadgeColor(row.ticker) }}
                              />
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Dividends */}
          <div className="bbg-card">
            <div className="flex items-center justify-between mb-3">
              <p className="bbg-header mb-0">Dividends</p>
              <Link href="/income" className="text-bloomberg-muted text-[10px] hover:text-bloomberg-gold">
                Show more →
              </Link>
            </div>

            <div className="grid grid-cols-4 gap-2 mb-4">
              {[
                { label: "Total Received", value: fmtCurrency(totalDivReceived, ccy) },
                { label: "Yield TTM", value: divYieldTTM > 0 ? fmtPct(divYieldTTM) : "—" },
                { label: "YoC TTM", value: divYoC > 0 ? fmtPct(divYoC) : "—" },
                { label: "Payments", value: String(divTxs.length) },
              ].map(({ label, value }) => (
                <div key={label} className="border border-bloomberg-border p-2">
                  <p className="text-bloomberg-muted text-[9px] uppercase mb-1">{label}</p>
                  <p className="text-bloomberg-text text-xs font-bold">{value}</p>
                </div>
              ))}
            </div>

            {divBarData.length > 0 ? (
              <ResponsiveContainer width="100%" height={120}>
                <BarChart data={divBarData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" vertical={false} />
                  <XAxis dataKey="year" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} />
                  <YAxis tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false} width={50}
                    tickFormatter={(v) => fmtCurrency(v, ccy, true)} />
                  <Tooltip
                    contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                    formatter={(v: number) => [fmtCurrency(v, ccy), "Dividends"]}
                  />
                  <Bar dataKey="amount" fill="#4dff4d" fillOpacity={0.8} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="text-center text-bloomberg-muted text-[10px] py-4 border border-dashed border-bloomberg-border">
                No dividend transactions recorded
              </div>
            )}
          </div>
        </div>

        {/* ── RIGHT COLUMN ── */}
        <div className="space-y-4 lg:sticky lg:top-4">

          {/* Allocation donut */}
          <div className="bbg-card">
            <p className="bbg-header">Allocation</p>
            <div className="relative">
              <ResponsiveContainer width="100%" height={260}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={82}
                    outerRadius={115}
                    paddingAngle={2}
                    dataKey="value"
                    labelLine={false}
                    label={({ cx, cy }) => <DonutCenter cx={cx} cy={cy} value={totalValue} ccy={ccy} />}
                  >
                    {pieData.map((_, i) => (
                      <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                    formatter={(v: number, name: string) => [`${fmtCurrency(v, ccy)} (${((v / totalValue) * 100).toFixed(1)}%)`, name]}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
            {/* Legend */}
            <div className="space-y-1 mt-1">
              {portfolio.rows
                .slice()
                .sort((a, b) => b.weight - a.weight)
                .map((r, i) => (
                  <div key={r.ticker} className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: PIE_COLORS[i % PIE_COLORS.length] }} />
                      <span className="text-bloomberg-muted text-[10px]">{r.ticker}</span>
                    </div>
                    <span className="text-bloomberg-muted text-[10px]">{r.weight.toFixed(1)}%</span>
                  </div>
                ))}
            </div>
          </div>

          {/* Capital & Performance */}
          <div className="bbg-card space-y-3">
            {/* Capital */}
            <div>
              <p className="bbg-header">Capital</p>
              <div className="flex justify-between items-center text-xs border-b border-bloomberg-border/40 py-1.5">
                <span className="text-bloomberg-muted">Cost basis</span>
                {editingBasis ? (
                  <div className="flex items-center gap-1">
                    <input
                      type="number"
                      step="any"
                      value={basisInput}
                      onChange={(e) => setBasisInput(e.target.value)}
                      className="w-24 bg-bloomberg-bg border border-bloomberg-gold text-bloomberg-text px-2 py-0.5 text-xs text-right focus:outline-none"
                      autoFocus
                    />
                    <button
                      onClick={() => {
                        const v = parseFloat(basisInput);
                        if (!isNaN(v) && v > 0) saveBasis(v);
                        setEditingBasis(false);
                      }}
                      className="text-green-400 text-[10px] px-1 hover:opacity-80"
                    >✓</button>
                    <button onClick={() => setEditingBasis(false)} className="text-bloomberg-muted text-[10px] px-1">✕</button>
                  </div>
                ) : (
                  <button
                    onClick={() => { setBasisInput(String(basis)); setEditingBasis(true); }}
                    className="text-bloomberg-text font-medium hover:text-bloomberg-gold transition-colors"
                    title="Click to edit cost basis"
                  >
                    {fmtCurrency(basis, ccy)} <span className="text-[9px] text-bloomberg-muted ml-0.5">✎</span>
                  </button>
                )}
              </div>
            </div>

            {/* Performance breakdown */}
            <div>
              <p className="text-bloomberg-muted text-[10px] uppercase tracking-widest mb-2">Performance</p>
              <div className="space-y-1.5">
                {[
                  {
                    label: "Price gain",
                    pct: priceGainPct,
                    val: priceGain,
                  },
                  {
                    label: "Dividends",
                    pct: invested > 0 ? (totalDivReceived / invested) * 100 : 0,
                    val: totalDivReceived,
                  },
                ].map(({ label, pct, val }) => (
                  <div key={label} className="flex justify-between items-center text-xs">
                    <span className="text-bloomberg-muted">{label}</span>
                    <div className="text-right">
                      <span className={`font-medium ${val >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {val >= 0 ? "↑" : "↓"}{fmtPct(Math.abs(pct))}
                      </span>
                      <span className={`ml-2 ${val >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {val >= 0 ? "+" : ""}{fmtCurrency(val, ccy)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Total return */}
            <div className="border-t border-bloomberg-border pt-2">
              <div className="flex justify-between items-center text-xs">
                <div>
                  <span className="text-bloomberg-muted font-medium">Total return</span>
                  {cost_basis_usd != null && (
                    <span className="block text-[9px] text-bloomberg-muted">since {INCEPTION_DATE}</span>
                  )}
                </div>
                <div className="text-right">
                  <span className={`font-bold ${totalReturn >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {totalReturn >= 0 ? "+" : ""}{fmtCurrency(totalReturn, ccy)}
                  </span>
                  <span className={`block text-[10px] ${priceGainPct >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {priceGainPct >= 0 ? "+" : "-"}{Math.abs(priceGainPct).toFixed(2)}%
                  </span>
                </div>
              </div>
            </div>


            {/* Day change */}
            <div className="border-t border-bloomberg-border pt-2">
              <p className="text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1.5">Today</p>
              <div className="flex justify-between items-center text-xs">
                <span className="text-bloomberg-muted">Day change</span>
                <span className={`font-medium ${dayChange >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {dayChange >= 0 ? "+" : ""}{fmtCurrency(dayChange, ccy)}
                  <span className="ml-1 text-[10px]">({fmtPct(dayChangePct)})</span>
                </span>
              </div>
              <div className="flex justify-between items-center text-xs mt-1">
                <span className="text-bloomberg-muted">Positions</span>
                <span className="text-bloomberg-muted">
                  <span className="text-green-400">{winners}↑</span>
                  {" / "}
                  <span className="text-red-400">{losers}↓</span>
                  {" of "}{portfolio.rows.length}
                </span>
              </div>
            </div>

            {/* Quick links */}
            <div className="border-t border-bloomberg-border pt-2 grid grid-cols-2 gap-1">
              {[
                { label: "Analytics", href: "/analytics" },
                { label: "Optimize", href: "/optimization" },
                { label: "Rebalance", href: "/rebalancing" },
                { label: "Risk", href: "/risk" },
              ].map(({ label, href }) => (
                <Link
                  key={href}
                  href={href}
                  className="text-center text-[10px] text-bloomberg-muted border border-bloomberg-border py-1 hover:text-bloomberg-gold hover:border-bloomberg-gold transition-colors"
                >
                  {label}
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
