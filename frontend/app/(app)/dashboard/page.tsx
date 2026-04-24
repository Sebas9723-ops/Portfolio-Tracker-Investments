"use client";
import { useState, memo, useEffect } from "react";
import dynamic from "next/dynamic";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { usePortfolio, usePortfolioHistory } from "@/lib/hooks/usePortfolio";
import { fetchTransactions } from "@/lib/api/transactions";
import { backfillCapitalSnapshots } from "@/lib/api/portfolio";
import { fetchPortfolioBreakdown, fetchAnalytics } from "@/lib/api/analytics";
import { updateSettings } from "@/lib/api/settings";
import { fmtCurrency, fmtPct, fmtDate } from "@/lib/formatters";
import { useSettingsStore } from "@/lib/store/settingsStore";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  ComposedChart, Area, Line,
} from "recharts";
import { RefreshCw, TrendingUp, TrendingDown } from "lucide-react";
import Link from "next/link";
import type { PortfolioRow } from "@/lib/types";

const PortfolioLWChart = dynamic(
  () => import("@/components/charts/PortfolioLWChart").then((m) => ({ default: m.PortfolioLWChart })),
  { ssr: false, loading: () => <div className="h-40 bg-bloomberg-border/30 animate-pulse rounded" /> }
);

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
  const dark = typeof document !== "undefined" && document.documentElement.classList.contains("dark");
  return (
    <g>
      <text x={cx} y={cy - 10} textAnchor="middle" fill="#64748b" fontSize={9} fontFamily="IBM Plex Mono, monospace">
        Total Net Worth
      </text>
      <text x={cx} y={cy + 12} textAnchor="middle" fill={dark ? "#e2e8f0" : "#0f172a"} fontSize={16} fontWeight="bold" fontFamily="IBM Plex Mono, monospace">
        {fmtCurrency(value, ccy, true)}
      </text>
    </g>
  );
}

// ── Market hours (UTC) ────────────────────────────────────────────────────────
// Returns true when the exchange for the given ticker is currently open.
// Hours are approximate UTC ranges; DST shifts are ~±1h and acceptable.
function isMarketOpen(ticker: string): boolean {
  const now = new Date();
  const day = now.getUTCDay(); // 0=Sun, 6=Sat
  if (day === 0 || day === 6) return false; // weekend

  const h = now.getUTCHours();
  const m = now.getUTCMinutes();
  const mins = h * 60 + m; // minutes since midnight UTC

  const upper = ticker.toUpperCase();

  // XETRA (.DE) and major EU exchanges: ~08:00–16:30 UTC
  if (/\.(DE|PA|AM|MI|BR|VI|MC)$/.test(upper)) {
    return mins >= 8 * 60 && mins < 16 * 60 + 30;
  }
  // LSE (.L, .UK): ~08:00–16:30 UTC
  if (/\.(L|UK)$/.test(upper)) {
    return mins >= 8 * 60 && mins < 16 * 60 + 30;
  }
  // US exchanges (NYSE / NASDAQ): 14:30–21:00 UTC
  return mins >= 14 * 60 + 30 && mins < 21 * 60;
}

// ── Badge ─────────────────────────────────────────────────────────────────────
function TickerBadge({ ticker }: { ticker: string }) {
  const color = tickerBadgeColor(ticker);
  const initials = ticker.replace(/[^A-Z]/g, "").slice(0, 2) || ticker.slice(0, 2).toUpperCase();
  const open = isMarketOpen(ticker);
  return (
    <span className="relative inline-flex shrink-0">
      <span
        className="inline-flex items-center justify-center w-8 h-8 rounded-full text-[10px] font-bold text-bloomberg-bg"
        style={{ backgroundColor: color }}
      >
        {initials}
      </span>
      {/* Market status dot — bottom-right corner of the badge */}
      <span
        className={`absolute bottom-0 right-0 w-2 h-2 rounded-full border border-white ${open ? "bg-green-400" : "bg-red-400"}`}
        title={open ? "Market open" : "Market closed"}
      />
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

// ── Memoized positions row ────────────────────────────────────────────────────
const PositionRow = memo(function PositionRow({ row, ccy }: { row: PortfolioRow; ccy: string }) {
  const totalBuyIn = row.avg_cost_native != null ? row.avg_cost_native * row.shares : null;
  return (
    <tr className="border-b border-bloomberg-border/40 hover:bg-bloomberg-card transition-colors">
      <td className="py-2.5 pr-3">
        <div className="flex items-center gap-2">
          <TickerBadge ticker={row.ticker} />
          <div className="min-w-0">
            <p className="text-bloomberg-text font-medium truncate max-w-[100px] sm:max-w-[160px] md:max-w-[200px]">{row.name}</p>
            <p className="text-bloomberg-muted text-[10px]">{row.ticker} · {row.shares.toFixed(3)}</p>
          </div>
        </div>
      </td>
      <td className="py-2.5 text-right hidden sm:table-cell">
        {totalBuyIn != null ? (
          <>
            <p className="text-bloomberg-text">{fmtCurrency(totalBuyIn, row.cost_currency)}</p>
            <p className="text-bloomberg-muted text-[10px]">{fmtCurrency(row.avg_cost_native!, row.cost_currency)} avg</p>
          </>
        ) : (
          <span className="text-bloomberg-muted">—</span>
        )}
      </td>
      <td className="py-2.5 text-right">
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
      <td className="py-2.5 text-right">
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
      <td className="py-2.5 text-right hidden md:table-cell">
        <p className="text-bloomberg-muted">{row.weight.toFixed(1)}%</p>
        <div className="w-12 h-0.5 bg-bloomberg-border ml-auto mt-1 rounded">
          <div className="h-0.5 rounded" style={{ width: `${Math.min(row.weight, 100)}%`, backgroundColor: tickerBadgeColor(row.ticker) }} />
        </div>
      </td>
    </tr>
  );
});

// ── Page ──────────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const [chartPeriod, setChartPeriod] = useState<Period>("Max");
  const [chartMode, setChartMode] = useState<"value" | "benchmark">("value");
  const [editingBasis, setEditingBasis] = useState(false);
  const [basisInput, setBasisInput] = useState("");
  const [donutView, setDonutView] = useState<"weights" | "sectors" | "regions">("weights");

  const { data: portfolio, isLoading, isFetching } = usePortfolio();
  const { data: historyData, isLoading: historyLoading, refetch: refetchHistory } = usePortfolioHistory();
  const { data: transactions } = useQuery({ queryKey: ["transactions"], queryFn: fetchTransactions });
  const { data: breakdown } = useQuery({ queryKey: ["portfolioBreakdown"], queryFn: fetchPortfolioBreakdown, staleTime: 60 * 60 * 1000 });
  const { data: analyticsData } = useQuery({
    queryKey: ["analytics", "1y"],
    queryFn: () => fetchAnalytics("1y"),
    staleTime: 60 * 60 * 1000,
    enabled: chartMode === "benchmark",
  });
  const qc = useQueryClient();
  const base_currency = useSettingsStore((s) => s.base_currency);
  const cost_basis_usd = useSettingsStore((s) => s.cost_basis_usd);
  const setSettings = useSettingsStore((s) => s.setSettings);

  // Run backfill once if history has no invested data yet (existing positions without snapshots)
  useEffect(() => {
    if (!historyData || historyData.length === 0) return;
    const hasInvested = historyData.some((h) => (h as any).invested > 0);
    if (!hasInvested) {
      backfillCapitalSnapshots().then(() => refetchHistory()).catch(() => {});
    }
  }, [historyData]);

  const { mutate: saveBasis } = useMutation({
    mutationFn: (v: number) => updateSettings({ cost_basis_usd: v }),
    onSuccess: (data) => { setSettings(data); qc.invalidateQueries({ queryKey: ["settings"] }); },
  });

  if (isLoading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-5 w-40 bg-bloomberg-border/40 rounded" />
        <div className="bbg-card space-y-3">
          <div className="h-10 w-48 bg-bloomberg-border/40 rounded" />
          <div className="h-40 bg-bloomberg-border/30 rounded" />
        </div>
        <div className="bbg-card space-y-2">
          {[1,2,3].map((i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-bloomberg-border/40" />
              <div className="flex-1 space-y-1">
                <div className="h-3 w-32 bg-bloomberg-border/40 rounded" />
                <div className="h-2 w-20 bg-bloomberg-border/30 rounded" />
              </div>
              <div className="h-3 w-16 bg-bloomberg-border/40 rounded" />
            </div>
          ))}
        </div>
      </div>
    );
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
  // Build history: keep all backend data, then upsert today's live value so
  // purchases made today are visible and no stale drop appears at the end.
  // Skip weekends — markets are closed, lightweight-charts uses business-day
  // mode and a Sat/Sun point would appear displaced to the following Monday.
  const localToday = new Date().toLocaleDateString("en-CA"); // "YYYY-MM-DD" in local tz
  const todayDow = new Date().getDay(); // 0 = Sun, 6 = Sat
  const isTradingDay = todayDow !== 0 && todayDow !== 6;
  const allHistory = (historyData ?? [])
    .filter((d) => d.date !== localToday)           // remove any stale today entry
    .concat(isTradingDay ? [{ date: localToday, value: totalValue }] : []) // live point on weekdays only
    .slice()
    .sort((a, b) => a.date.localeCompare(b.date));
  const chartData = filterHistory(allHistory, chartPeriod);

  // Period P&L from chart range
  const periodStart = chartData[0]?.value ?? totalValue;
  const periodChange = totalValue - periodStart;
  const periodChangePct = periodStart > 0 ? (periodChange / periodStart) * 100 : 0;

  // Benchmark overlay — normalize analytics series to start at 100
  const normSeries = (s: { date: string; value: number }[]) => {
    if (!s.length) return s;
    const first = s[0].value;
    return s.map((d) => ({ date: d.date, value: first !== 0 ? 100 + d.value - first : 100 }));
  };
  const bmPortfolioSeries = analyticsData?.portfolio_series ? normSeries(analyticsData.portfolio_series) : undefined;
  const bmBenchmarkSeries = analyticsData?.benchmark_series ? normSeries(analyticsData.benchmark_series) : undefined;
  const bmTicker = analyticsData?.metrics?.benchmark_ticker ?? "VOO";

  // Contributions tracker — cumulative invested vs portfolio value.
  // Primary source: BUY transactions sorted by date → true step function.
  // Fallback: total_invested_base (backend auto-computes from avg_cost × shares × FX).
  const autoInvested = (portfolio.total_invested_base && portfolio.total_invested_base > 0)
    ? portfolio.total_invested_base
    : (cost_basis_usd ?? 0);

  // Capital invested: use backend-persisted snapshot (step function) when available,
  // fall back to flat autoInvested (shares × avg_cost today).
  const contributionsData = allHistory.map((h) => ({
    date: h.date.slice(5),
    value: Math.round(h.value),
    invested: Math.round((h as any).invested ?? autoInvested),
  }));

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
  const basis = (portfolio.total_invested_base && portfolio.total_invested_base > 0)
    ? portfolio.total_invested_base
    : (cost_basis_usd ?? 0);
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
        {isFetching && <RefreshCw size={11} className="animate-spin text-bloomberg-muted" />}
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-start">

        {/* ── LEFT COLUMN ── */}
        <div className="md:col-span-2 space-y-4">

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
                    <div className="flex flex-col">
                      <Chg v={dayChangePct} pct className="text-xs" />
                      <span className="text-[10px] text-bloomberg-muted">
                        {dayChange >= 0 ? "+" : ""}{fmtCurrency(dayChange, ccy)} today
                      </span>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <Chg v={periodChangePct} pct className="text-[10px]" />
                  <span className="text-bloomberg-muted text-[10px]">
                    ({periodChange >= 0 ? "+" : ""}{fmtCurrency(periodChange, ccy)}) · {chartPeriod}
                  </span>
                </div>
              </div>
              <div className="flex flex-col items-end gap-1 shrink-0">
                {/* Chart mode toggle */}
                <div className="flex gap-1">
                  {(["value", "benchmark"] as const).map((m) => (
                    <button
                      key={m}
                      onClick={() => setChartMode(m)}
                      className={`text-[9px] px-2 py-0.5 border transition-colors ${
                        chartMode === m
                          ? "border-bloomberg-gold text-bloomberg-gold bg-bloomberg-gold/10"
                          : "border-bloomberg-border text-bloomberg-muted hover:border-bloomberg-muted"
                      }`}
                    >
                      {m === "value" ? "$ VALUE" : `% vs ${bmTicker}`}
                    </button>
                  ))}
                </div>
                {/* Period selector — only in value mode */}
                {chartMode === "value" && (
                  <div className="flex gap-1">
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
                )}
              </div>
            </div>

            {chartMode === "benchmark" ? (
              <div className="mt-3">
                {bmPortfolioSeries && bmBenchmarkSeries ? (
                  <>
                    <div className="flex items-center gap-4 mb-2">
                      <span className="flex items-center gap-1 text-[10px]" style={{ color: "#f3a712" }}>
                        <span className="w-4 h-0.5 inline-block" style={{ background: "#f3a712" }} /> Portfolio
                      </span>
                      <span className="flex items-center gap-1 text-[10px] text-bloomberg-muted">
                        <span className="w-4 h-0.5 inline-block border-t border-dashed" style={{ borderColor: "#94a3b8" }} /> {bmTicker}
                      </span>
                    </div>
                    <PortfolioLWChart
                      data={bmPortfolioSeries}
                      benchmark={bmBenchmarkSeries}
                      benchmarkLabel={bmTicker}
                    />
                  </>
                ) : (
                  <div className="flex items-center justify-center h-40 text-bloomberg-muted text-xs border border-dashed border-bloomberg-border">
                    Loading benchmark data…
                  </div>
                )}
              </div>
            ) : historyLoading ? (
              <div className="mt-3 h-40 rounded overflow-hidden">
                <div className="w-full h-full bg-bloomberg-border/30 animate-pulse rounded" />
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
                    <th className="text-right pb-2 text-bloomberg-muted text-[10px] font-normal hidden sm:table-cell">Buy In</th>
                    <th className="text-right pb-2 text-bloomberg-muted text-[10px] font-normal">Position</th>
                    <th className="text-right pb-2 text-bloomberg-muted text-[10px] font-normal">P/L</th>
                    <th className="text-right pb-2 text-bloomberg-muted text-[10px] font-normal hidden md:table-cell">Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {portfolio.rows
                    .slice()
                    .sort((a, b) => b.value_base - a.value_base)
                    .map((row) => (
                      <PositionRow key={row.ticker} row={row} ccy={ccy} />
                    ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Contributions Tracker */}
          {contributionsData.length > 1 && (
            <div className="bbg-card">
              <p className="bbg-header">Capital vs Portfolio Value</p>
              <div className="flex items-center gap-4 mb-2">
                <span className="flex items-center gap-1.5 text-[10px]" style={{ color: "#f3a712" }}>
                  <span className="w-3 h-3 rounded-sm inline-block opacity-60" style={{ background: "#f3a712" }} /> Portfolio Value
                </span>
                <span className="flex items-center gap-1.5 text-[10px] text-bloomberg-muted">
                  <span className="w-3 h-0.5 inline-block border-t-2 border-dashed" style={{ borderColor: "#38b2ff" }} /> Capital Invested
                </span>
              </div>
              <ResponsiveContainer width="100%" height={160}>
                <ComposedChart data={contributionsData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fontSize: 9 }} tickLine={false} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 9 }} tickLine={false} axisLine={false} width={55}
                    tickFormatter={(v) => v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : `$${v}`} />
                  <Tooltip
                    formatter={(v: number, name: string) => [fmtCurrency(v, ccy), name === "value" ? "Portfolio" : "Invested"]}
                    labelFormatter={(l) => `2026-${l}`}
                  />
                  <Area type="monotone" dataKey="value" fill="rgba(243,167,18,0.15)" stroke="#f3a712" strokeWidth={1.5} dot={false} name="value" />
                  <Line type="monotone" dataKey="invested" stroke="#38b2ff" strokeWidth={1.5} strokeDasharray="4 3" dot={false} name="invested" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Dividends */}
          <div className="bbg-card">
            <div className="flex items-center justify-between mb-3">
              <p className="bbg-header mb-0">Dividends</p>
              <Link href="/income" className="text-bloomberg-muted text-[10px] hover:text-bloomberg-gold">
                Show more →
              </Link>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
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
            <div className="flex items-center justify-between mb-2">
              <p className="bbg-header mb-0">Allocation</p>
              <div className="flex gap-1">
                {(["weights", "sectors", "regions"] as const).map((v) => (
                  <button key={v} onClick={() => setDonutView(v)}
                    className={`text-[9px] px-2 py-0.5 border capitalize ${donutView === v ? "border-bloomberg-gold text-bloomberg-gold" : "border-bloomberg-border text-bloomberg-muted"}`}>
                    {v}
                  </button>
                ))}
              </div>
            </div>
            {(() => {
              const data =
                donutView === "weights"
                  ? pieData
                  : donutView === "sectors"
                  ? Object.entries(breakdown?.sectors ?? {}).map(([name, value]) => ({ name, value }))
                  : Object.entries(breakdown?.regions ?? {}).map(([name, value]) => ({ name, value }));
              const total = data.reduce((s, d) => s + d.value, 0);
              return (
                <>
                  <div className="relative">
                    <ResponsiveContainer width="100%" height={260}>
                      <PieChart>
                        <Pie
                          data={data}
                          cx="50%"
                          cy="50%"
                          innerRadius={82}
                          outerRadius={115}
                          paddingAngle={2}
                          dataKey="value"
                          labelLine={false}
                          label={donutView === "weights"
                            ? ({ cx, cy }) => <DonutCenter cx={cx} cy={cy} value={totalValue} ccy={ccy} />
                            : undefined}
                        >
                          {data.map((_, i) => (
                            <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip
                          contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                          formatter={(v: number, name: string) =>
                            donutView === "weights"
                              ? [`${fmtCurrency(v, ccy)} (${((v / totalValue) * 100).toFixed(1)}%)`, name]
                              : [`${v.toFixed(1)}%`, name]
                          }
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="space-y-1 mt-1">
                    {data
                      .slice()
                      .sort((a, b) => b.value - a.value)
                      .map((d, i) => (
                        <div key={d.name} className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: PIE_COLORS[i % PIE_COLORS.length] }} />
                            <span className="text-bloomberg-muted text-[10px]">{d.name}</span>
                          </div>
                          <span className="text-bloomberg-muted text-[10px]">
                            {donutView === "weights" ? `${((d.value / totalValue) * 100).toFixed(1)}%` : `${d.value.toFixed(1)}%`}
                          </span>
                        </div>
                      ))}
                  </div>
                </>
              );
            })()}
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
