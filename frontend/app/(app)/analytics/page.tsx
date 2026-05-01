"use client";
import { useState, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAnalytics, fetchRollingMetrics, fetchExtendedAnalytics, fetchVolRegime, fetchQuantAdvanced, fetchEquityCurve, fetchVsBenchmark, fetchRecommendations, fetchTaxLoss, fetchHealthScore, fetchAttribution, fetchPortfolioNews, runKellySizing, runMonteCarlo } from "@/lib/api/analytics";
import { fetchLastAgentResults, runAgentsNow } from "@/lib/api/agents";
import type { MacroAgentResult, DoctorAgentResult } from "@/lib/api/agents";
import type {
  FactorRisk, TrackingErrorBudget, QuantRegime, NaiveBenchmarkRow, WalkForward,
} from "@/lib/api/contribution";
import { useSettingsStore } from "@/lib/store/settingsStore";
import { Card, Metric, Text, BadgeDelta } from "@tremor/react";
import { fmtPct, fmtDate, MONTHS_SHORT } from "@/lib/formatters";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
  ComposedChart, Area, ReferenceLine, ReferenceArea,
} from "recharts";

const PERIODS = ["6m", "1y", "2y", "5y"];

// Group consecutive vol-regime dates into {x1, x2} ranges for ReferenceArea
function getRegimeRanges(
  series: { date: string; regime: string }[],
  regime: string,
): { x1: string; x2: string }[] {
  const ranges: { x1: string; x2: string }[] = [];
  let start: string | null = null;
  for (let i = 0; i < series.length; i++) {
    if (series[i].regime === regime && !start) {
      start = series[i].date;
    } else if (series[i].regime !== regime && start) {
      ranges.push({ x1: start, x2: series[i - 1].date });
      start = null;
    }
  }
  if (start) ranges.push({ x1: start, x2: series[series.length - 1].date });
  return ranges;
}

function fmt(v: number | null | undefined, digits = 3): string {
  if (v == null) return "—";
  return v.toFixed(digits);
}

export default function AnalyticsPage() {
  const [period, setPeriod] = useState("2y");
  const rolling_window = useSettingsStore((s) => s.rolling_window);
  const preferred_benchmark = useSettingsStore((s) => s.preferred_benchmark);

  const { data, isLoading } = useQuery({
    queryKey: ["analytics", period, preferred_benchmark],
    queryFn: () => fetchAnalytics(period, preferred_benchmark),
    staleTime: 5 * 60 * 1000,
  });

  const { data: rollingFull } = useQuery({
    queryKey: ["rolling-full", period, rolling_window],
    queryFn: () => fetchRollingMetrics(rolling_window, period),
    staleTime: 5 * 60 * 1000,
  });

  const { data: extended } = useQuery({
    queryKey: ["extended-analytics", period],
    queryFn: () => fetchExtendedAnalytics(period),
    staleTime: 5 * 60 * 1000,
  });

  const { data: volRegime } = useQuery({
    queryKey: ["vol-regime", period],
    queryFn: () => fetchVolRegime(period, 21),
    staleTime: 5 * 60 * 1000,
  });

  const { data: equityCurve } = useQuery({
    queryKey: ["equity-curve", period],
    queryFn: () => fetchEquityCurve(period),
    staleTime: 10 * 60 * 1000,
  });

  const [qaEnabled, setQaEnabled] = useState(false);
  const { data: quantAdvancedRaw, isFetching: qaFetching, refetch: refetchQA } = useQuery({
    queryKey: ["quant-advanced", period, preferred_benchmark],
    queryFn: () => fetchQuantAdvanced({ period, benchmark_ticker: preferred_benchmark }),
    enabled: qaEnabled,
    staleTime: 10 * 60 * 1000,
  });
  const qa = quantAdvancedRaw as {
    factor_risk?: FactorRisk;
    tracking_error_budget?: TrackingErrorBudget;
    regime?: QuantRegime;
    naive_benchmarks?: NaiveBenchmarkRow[];
    walk_forward?: WalkForward;
  } | undefined;

  const { data: vsBenchmark } = useQuery({
    queryKey: ["vs-benchmark", period, preferred_benchmark],
    queryFn: () => fetchVsBenchmark(period, preferred_benchmark),
    staleTime: 10 * 60 * 1000,
  });

  const { data: recs } = useQuery({
    queryKey: ["recommendations"],
    queryFn: fetchRecommendations,
    staleTime: 5 * 60 * 1000,
  });

  const { data: taxLoss } = useQuery({
    queryKey: ["tax-loss"],
    queryFn: () => fetchTaxLoss(5.0),
    staleTime: 10 * 60 * 1000,
  });

  const { data: healthScore } = useQuery({
    queryKey: ["health-score", period],
    queryFn: () => fetchHealthScore(period),
    staleTime: 5 * 60 * 1000,
  });

  const { data: attribution } = useQuery({
    queryKey: ["attribution"],
    queryFn: fetchAttribution,
    staleTime: 5 * 60 * 1000,
  });

  const { data: portfolioNews } = useQuery({
    queryKey: ["portfolio-news"],
    queryFn: fetchPortfolioNews,
    staleTime: 10 * 60 * 1000,
  });

  // Kelly calculator state
  const [kellyTicker, setKellyTicker] = useState("");
  const [kellyConviction, setKellyConviction] = useState(65);
  const [kellyExpRet, setKellyExpRet] = useState(12);
  const [kellyResult, setKellyResult] = useState<Awaited<ReturnType<typeof runKellySizing>> | null>(null);
  const [kellyLoading, setKellyLoading] = useState(false);

  // Monte Carlo state
  const [mcMonthly, setMcMonthly] = useState(500);
  const [mcYears, setMcYears] = useState(10);
  const [mcTarget, setMcTarget] = useState(100000);
  const [mcResult, setMcResult] = useState<Awaited<ReturnType<typeof runMonteCarlo>> | null>(null);
  const [mcLoading, setMcLoading] = useState(false);

  // Agent results state
  const [agentsRunning, setAgentsRunning] = useState(false);
  const [liveAgentResult, setLiveAgentResult] = useState<{ macro: MacroAgentResult | null; doctor: DoctorAgentResult | null } | null>(null);
  const [agentErrors, setAgentErrors] = useState<string[]>([]);

  const { data: lastAgentResults, refetch: refetchAgents } = useQuery({
    queryKey: ["last-agent-results"],
    queryFn: fetchLastAgentResults,
    staleTime: 10 * 60 * 1000,
  });

  const runAgents = useCallback(async () => {
    setAgentsRunning(true);
    setAgentErrors([]);
    try {
      const r = await runAgentsNow();
      setLiveAgentResult(r);
      const errs = r.errors ?? [];
      if (errs.length > 0) setAgentErrors(errs);
      refetchAgents();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setAgentErrors([`Request failed: ${msg}`]);
    }
    setAgentsRunning(false);
  }, [refetchAgents]);

  const runKelly = useCallback(async () => {
    if (!kellyTicker) return;
    setKellyLoading(true);
    try { const r = await runKellySizing({ ticker: kellyTicker, conviction_pct: kellyConviction, expected_annual_return: kellyExpRet }); setKellyResult(r); }
    catch (e) { console.error(e); }
    setKellyLoading(false);
  }, [kellyTicker, kellyConviction, kellyExpRet]);

  const runMC = useCallback(async () => {
    setMcLoading(true);
    try { const r = await runMonteCarlo({ monthly_contribution: mcMonthly, years: mcYears, target_goal: mcTarget }); setMcResult(r); }
    catch (e) { console.error(e); }
    setMcLoading(false);
  }, [mcMonthly, mcYears, mcTarget]);

  // Derived from optional data — must be before any early returns (React hooks rules)
  const vrSeries = volRegime?.series ?? [];
  const highVolRanges = useMemo(() => getRegimeRanges(vrSeries, "high"), [vrSeries]);
  const vrChart = useMemo(() => vrSeries.filter((_, i) => i % 2 === 0), [vrSeries]);

  if (isLoading) return <div className="text-bloomberg-muted text-xs p-4">Computing analytics…</div>;
  if (!data) return null;

  const { metrics, rolling, monthly_returns, drawdown_episodes, portfolio_series, benchmark_series } = data;

  const perfMap: Record<string, { portfolio?: number; benchmark?: number }> = {};
  portfolio_series.forEach((p) => { perfMap[p.date] = { portfolio: p.value }; });
  benchmark_series.forEach((b) => {
    if (!perfMap[b.date]) perfMap[b.date] = {};
    perfMap[b.date].benchmark = b.value;
  });
  const perfData = Object.entries(perfMap)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, v]) => ({ date, portfolio: v.portfolio, benchmark: v.benchmark }));

  const years = [...new Set(monthly_returns.map((m) => m.year))].sort();

  const ext = extended?.extended_ratios ?? {};
  const ff = extended?.fama_french ?? {};
  const perTicker = extended?.per_ticker_sharpe ?? {};
  const lowThr = volRegime?.low_threshold ?? 0;
  const highThr = volRegime?.high_threshold ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Analytics</h1>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1">
            {PERIODS.map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`text-[10px] px-2 py-1 border ${period === p ? "border-bloomberg-gold text-bloomberg-gold" : "border-bloomberg-border text-bloomberg-muted hover:border-bloomberg-muted"}`}
              >
                {p.toUpperCase()}
              </button>
            ))}
          </div>
          <button
            onClick={() => { setQaEnabled(true); refetchQA(); }}
            disabled={qaFetching}
            className="bg-bloomberg-gold text-bloomberg-bg text-[10px] font-bold px-3 py-1 hover:opacity-90 disabled:opacity-50 uppercase tracking-wider"
          >
            {qaFetching ? "COMPUTING…" : "QUANT ADV."}
          </button>
        </div>
      </div>

      {/* ── Health Score ── */}
      {healthScore && healthScore.score !== null && (
        <div className="bbg-card">
          <div className="flex items-center justify-between mb-3">
            <p className="bbg-header">Portfolio Health Score</p>
            <div className="flex items-center gap-3">
              <span className={`text-3xl font-black ${healthScore.score >= 85 ? "text-green-400" : healthScore.score >= 70 ? "text-bloomberg-gold" : healthScore.score >= 55 ? "text-yellow-500" : "text-red-400"}`}>
                {healthScore.score.toFixed(0)}
              </span>
              <span className={`text-xl font-black px-2 py-0.5 rounded ${healthScore.grade === "A" ? "bg-green-500/20 text-green-400" : healthScore.grade === "B" ? "bg-bloomberg-gold/20 text-bloomberg-gold" : healthScore.grade === "C" ? "bg-yellow-500/20 text-yellow-500" : "bg-red-500/20 text-red-400"}`}>
                {healthScore.grade}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {Object.entries(healthScore.components).map(([key, comp]) => (
              <div key={key} className="border border-bloomberg-border p-2">
                <p className="text-bloomberg-muted text-[9px] uppercase tracking-widest">{comp.label}</p>
                <div className="flex items-center gap-2 mt-1">
                  <div className="flex-1 h-1.5 bg-bloomberg-border rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${comp.score >= 20 ? "bg-green-500" : comp.score >= 12 ? "bg-bloomberg-gold" : "bg-red-500"}`} style={{ width: `${(comp.score / 25) * 100}%` }} />
                  </div>
                  <span className="text-bloomberg-text text-[10px] font-bold">{comp.score.toFixed(0)}/25</span>
                </div>
                <p className="text-bloomberg-muted text-[9px] mt-1">{comp.detail}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── AI Agents: Macro + Portfolio Doctor ── */}
      {(() => {
        const macro: MacroAgentResult | null = liveAgentResult?.macro ?? lastAgentResults?.macro?.result ?? null;
        const doctor: DoctorAgentResult | null = liveAgentResult?.doctor ?? lastAgentResults?.doctor?.result ?? null;
        const runAt = lastAgentResults?.doctor?.run_at;
        const REGIME_COLORS: Record<string, string> = {
          risk_on:     "text-green-400 border-green-400/40 bg-green-400/10",
          goldilocks:  "text-green-400 border-green-400/40 bg-green-400/10",
          risk_off:    "text-red-400 border-red-400/40 bg-red-400/10",
          crisis:      "text-red-400 border-red-400/40 bg-red-400/10",
          stagflation: "text-yellow-500 border-yellow-500/40 bg-yellow-500/10",
        };
        const URGENCY_COLORS: Record<string, string> = {
          low:    "text-green-400 bg-green-400/10",
          medium: "text-bloomberg-gold bg-bloomberg-gold/10",
          high:   "text-red-400 bg-red-400/10",
        };
        return (
          <div className="bbg-card">
            <div className="flex items-center justify-between mb-3">
              <p className="bbg-header mb-0">AI Agents — Macro + Portfolio Doctor</p>
              <div className="flex items-center gap-2">
                {runAt && <span className="text-[9px] text-bloomberg-muted">Last run: {new Date(runAt).toLocaleDateString()}</span>}
                <button
                  onClick={runAgents}
                  disabled={agentsRunning}
                  className="text-[10px] text-bloomberg-gold border border-bloomberg-gold/40 px-2.5 py-1 rounded-lg hover:bg-bloomberg-gold/10 transition-colors disabled:opacity-50"
                >
                  {agentsRunning ? "Analyzing…" : "🤖 Run now"}
                </button>
              </div>
            </div>

            {agentErrors.length > 0 && (
              <div className="mb-3 border border-red-500/40 bg-red-500/5 rounded p-2 space-y-1">
                {agentErrors.map((err, i) => (
                  <p key={i} className="text-red-400 text-[10px] font-mono">{err}</p>
                ))}
              </div>
            )}

            {!macro && !doctor && !agentsRunning && agentErrors.length === 0 && (
              <p className="text-bloomberg-muted text-[10px]">No results yet. Agents run automatically every Sunday at 18:00. You can run them manually now.</p>
            )}

            {agentsRunning && (
              <div className="space-y-2">
                {[...Array(2)].map((_, i) => <div key={i} className="h-10 bg-bloomberg-bg animate-pulse rounded" />)}
              </div>
            )}

            {(macro || doctor) && !agentsRunning && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Macro Agent */}
                {macro && (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <span className="text-[9px] text-bloomberg-muted uppercase tracking-widest">Macro Regime</span>

                      <span className={`text-[9px] px-2 py-0.5 rounded border font-bold uppercase ${REGIME_COLORS[macro.macro_regime] ?? "text-bloomberg-muted border-bloomberg-border"}`}>
                        {macro.macro_regime.replace("_", " ")}
                      </span>
                    </div>
                    <p className="text-bloomberg-text text-[11px] leading-relaxed">{macro.narrative}</p>
                    {Object.keys(macro.suggested_overlay).length > 0 && (
                      <div className="border border-bloomberg-border p-2 mt-1">
                        <p className="text-[9px] text-bloomberg-muted uppercase tracking-widest mb-1">Suggested Overlay</p>
                        <div className="flex flex-wrap gap-2">
                          {Object.entries(macro.suggested_overlay).map(([t, v]) => (
                            <span key={t} className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${v > 1 ? "text-green-400 bg-green-400/10" : "text-red-400 bg-red-400/10"}`}>
                              {t} {v > 1 ? "↑" : "↓"} {v.toFixed(2)}x
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Portfolio Doctor */}
                {doctor && (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <span className="text-[9px] text-bloomberg-muted uppercase tracking-widest">Urgency</span>
                      <span className={`text-[9px] px-2 py-0.5 rounded font-bold uppercase ${URGENCY_COLORS[doctor.urgency] ?? ""}`}>
                        {doctor.urgency}
                      </span>
                    </div>
                    <p className="text-bloomberg-text text-[11px] leading-relaxed">{doctor.diagnosis}</p>
                    <ul className="space-y-1 mt-1">
                      {doctor.actions.map((action, i) => (
                        <li key={i} className="flex items-start gap-1.5 text-[10px] text-bloomberg-text">
                          <span className="text-bloomberg-gold mt-0.5 shrink-0">›</span>
                          {action}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })()}

      {/* ── Equity Curve ── */}
      {equityCurve && equityCurve.series.length > 1 && (
        <div className="bbg-card">
          <p className="bbg-header">Portfolio Value History</p>
          <div className="h-52 sm:h-64">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={equityCurve.series} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e2530" />
                <XAxis
                  dataKey="date"
                  tick={{ fill: "#6b7280", fontSize: 9 }}
                  tickFormatter={(d) => d.slice(5)}
                  interval="preserveStartEnd"
                  minTickGap={40}
                />
                <YAxis
                  tick={{ fill: "#6b7280", fontSize: 9 }}
                  tickFormatter={(v) => `${equityCurve.base_currency} ${(v / 1000).toFixed(1)}k`}
                  width={60}
                />
                <Tooltip
                  contentStyle={{ background: "#0b0f14", border: "1px solid #1e2530", fontSize: 11 }}
                  formatter={(v: number, name: string) => [
                    `${equityCurve.base_currency} ${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                    name === "value" ? "Portfolio Value" : "Invested Capital",
                  ]}
                  labelFormatter={(d) => `Date: ${d}`}
                />
                <Legend wrapperStyle={{ fontSize: 10, color: "#6b7280" }} />
                {/* Invested capital as area baseline */}
                <Area type="monotone" dataKey="invested" fill="#1e2530" stroke="#374151" strokeWidth={1} fillOpacity={0.6} name="invested" dot={false} />
                {/* Portfolio value line */}
                <Line type="monotone" dataKey="value" stroke="#f3a712" strokeWidth={2} dot={false} name="value" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          {/* PnL summary strip */}
          {(() => {
            const last = equityCurve.series[equityCurve.series.length - 1];
            const first = equityCurve.series[0];
            if (!last || !first) return null;
            const gain = last.value - first.value;
            const gainPct = first.value > 0 ? (gain / first.value) * 100 : 0;
            const pnl = last.pnl;
            const pnlPct = last.pnl_pct;
            return (
              <div className="flex flex-wrap gap-4 mt-3 text-[10px]">
                <span className="text-bloomberg-muted">Start: <span className="text-bloomberg-text font-medium">{equityCurve.base_currency} {first.value.toLocaleString()}</span></span>
                <span className="text-bloomberg-muted">Current: <span className="text-bloomberg-text font-medium">{equityCurve.base_currency} {last.value.toLocaleString()}</span></span>
                <span className="text-bloomberg-muted">Period gain: <span className={gain >= 0 ? "text-green-400 font-medium" : "text-red-400 font-medium"}>{gain >= 0 ? "+" : ""}{gain.toFixed(2)} ({gainPct >= 0 ? "+" : ""}{gainPct.toFixed(2)}%)</span></span>
                {pnl != null && <span className="text-bloomberg-muted">Unrealized P&L: <span className={pnl >= 0 ? "text-green-400 font-medium" : "text-red-400 font-medium"}>{pnl >= 0 ? "+" : ""}{pnl.toFixed(2)} ({pnlPct != null ? `${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%` : ""})</span></span>}
              </div>
            );
          })()}
        </div>
      )}

      {/* ── Portfolio vs Benchmark ── */}
      {vsBenchmark && vsBenchmark.series.length > 1 && (
        <div className="bbg-card">
          <div className="flex items-center justify-between mb-2">
            <p className="bbg-header">Portfolio vs {vsBenchmark.benchmark_ticker} (Normalized to 100)</p>
            {vsBenchmark.alpha_total != null && (
              <span className={`text-[10px] font-bold ${vsBenchmark.alpha_total >= 0 ? "text-green-400" : "text-red-400"}`}>
                Alpha: {vsBenchmark.alpha_total >= 0 ? "+" : ""}{vsBenchmark.alpha_total.toFixed(2)} pts
              </span>
            )}
          </div>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={vsBenchmark.series} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e2530" />
                <XAxis dataKey="date" tick={{ fill: "#6b7280", fontSize: 9 }} tickFormatter={(d) => d.slice(5)} interval="preserveStartEnd" minTickGap={40} />
                <YAxis tick={{ fill: "#6b7280", fontSize: 9 }} width={40} tickFormatter={(v) => v.toFixed(0)} />
                <Tooltip
                  contentStyle={{ background: "#0b0f14", border: "1px solid #1e2530", fontSize: 11 }}
                  formatter={(v: number, name: string) => [`${v?.toFixed(2)}`, name === "portfolio" ? "Portfolio" : name === "benchmark" ? vsBenchmark.benchmark_ticker : "Alpha"]}
                  labelFormatter={(d) => `Date: ${d}`}
                />
                <Legend wrapperStyle={{ fontSize: 10, color: "#6b7280" }} />
                <ReferenceLine y={100} stroke="#374151" strokeDasharray="2 2" />
                <Area type="monotone" dataKey="alpha" fill="#f3a71215" stroke="none" name="alpha" />
                <Line type="monotone" dataKey="portfolio" stroke="#f3a712" strokeWidth={2} dot={false} name="portfolio" />
                <Line type="monotone" dataKey="benchmark" stroke="#6b7280" strokeWidth={1.5} dot={false} strokeDasharray="4 4" name="benchmark" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          {vsBenchmark.inception_date && (
            <p className="text-bloomberg-muted text-[9px] mt-2">Inception: {vsBenchmark.inception_date} · Both series normalized to 100 at inception</p>
          )}
        </div>
      )}

      {/* ── Recommendation Engine ── */}
      {recs && recs.cards.length > 0 && (
        <div className="bbg-card">
          <div className="flex items-center justify-between mb-3">
            <p className="bbg-header">Recommendation Engine</p>
            {recs.generated_at && (
              <span className="text-bloomberg-muted text-[9px]">Updated: {recs.generated_at.slice(0, 16).replace("T", " ")}</span>
            )}
          </div>
          <div className="space-y-2">
            {recs.cards.map((card, i) => {
              const colors = {
                action:  "border-l-red-500 bg-red-500/5",
                warning: "border-l-yellow-500 bg-yellow-500/5",
                info:    "border-l-blue-500 bg-blue-500/5",
              };
              const badges = {
                action:  "bg-red-500/20 text-red-400",
                warning: "bg-yellow-500/20 text-yellow-400",
                info:    "bg-blue-500/20 text-blue-400",
              };
              return (
                <div key={i} className={`border-l-2 pl-3 py-2 pr-2 rounded-r ${colors[card.severity]}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold uppercase ${badges[card.severity]}`}>{card.severity}</span>
                        {card.ticker && <span className="text-bloomberg-gold text-[10px] font-bold">{card.ticker}</span>}
                      </div>
                      <p className="text-bloomberg-text text-[11px] font-semibold">{card.title}</p>
                      <p className="text-bloomberg-muted text-[10px] mt-0.5">{card.body}</p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Core Metrics ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2 sm:gap-3">
        {[
          { label: "TWR",         value: metrics.twr != null ? fmtPct(metrics.twr) : "—",                                  delta: metrics.twr != null ? ((metrics.twr ?? 0) >= 0 ? "increase" : "decrease") : undefined },
          { label: "Ann. Return", value: metrics.annualized_return != null ? fmtPct(metrics.annualized_return) : "—",       delta: metrics.annualized_return != null ? ((metrics.annualized_return ?? 0) >= 0 ? "increase" : "decrease") : undefined },
          { label: "Sharpe",      value: metrics.sharpe?.toFixed(3) ?? "—",                                                 delta: undefined },
          { label: "Sortino",     value: metrics.sortino?.toFixed(3) ?? "—",                                                delta: undefined },
          { label: "Max DD",      value: metrics.max_drawdown != null ? fmtPct(metrics.max_drawdown) : "—",                 delta: "decrease" as const },
          { label: "Volatility",  value: metrics.annualized_vol != null ? fmtPct(metrics.annualized_vol) : "—",             delta: undefined },
          { label: "Alpha",       value: metrics.alpha != null ? fmtPct(metrics.alpha) : "—",                               delta: metrics.alpha != null ? ((metrics.alpha ?? 0) >= 0 ? "increase" : "decrease") : undefined, sub: `vs ${metrics.benchmark_ticker}` },
          { label: "Beta",        value: metrics.beta?.toFixed(3) ?? "—",                                                   delta: undefined },
          { label: "Calmar",      value: metrics.calmar?.toFixed(3) ?? "—",                                                 delta: undefined },
          { label: "Info Ratio",  value: metrics.information_ratio?.toFixed(3) ?? "—",                                      delta: undefined },
        ].map(({ label, value, delta, sub }) => (
          <Card key={label} className="p-2 sm:p-3 shadow-card rounded-xl border-slate-200">
            <Text className="text-[10px] uppercase tracking-widest text-slate-500">{label}</Text>
            <Metric className="text-base font-semibold text-slate-900 mt-0.5">{value}</Metric>
            {delta && <BadgeDelta deltaType={delta as "increase" | "decrease"} className="mt-1" size="xs" />}
            {sub && <Text className="text-[10px] text-slate-400 mt-0.5">{sub}</Text>}
          </Card>
        ))}
      </div>

      {/* ── Extended Ratios ── */}
      {Object.keys(ext).length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Extended Ratios</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-2">
            {[
              { label: "Treynor Ratio", v: ext.treynor, digits: 4 },
              { label: "Omega Ratio", v: ext.omega, digits: 4 },
              { label: "Tail Ratio", v: ext.tail_ratio, digits: 4 },
              { label: "Martin Ratio", v: ext.martin_ratio, digits: 4 },
              { label: "Ulcer Index", v: ext.ulcer_index, digits: 4, suffix: "%" },
              { label: "Tracking Error", v: ext.tracking_error, digits: 3, suffix: "%" },
              { label: "Win Rate vs BM", v: ext.win_rate_vs_benchmark, digits: 2, suffix: "%" },
              { label: "% Positive Days", v: ext.pct_positive_days, digits: 2, suffix: "%" },
              { label: "Skewness", v: ext.skewness, digits: 4 },
              { label: "Excess Kurtosis", v: ext.kurtosis, digits: 4 },
              { label: "Beta (CAPM)", v: ext.beta, digits: 3 },
              { label: "Info Ratio (ext)", v: ext.information_ratio, digits: 3 },
            ].map(({ label, v, digits = 3, suffix = "" }) => (
              <div key={label} className="flex justify-between border-b border-bloomberg-border/40 py-1">
                <span className="text-bloomberg-muted text-[10px]">{label}</span>
                <span className="text-bloomberg-text text-[10px] font-medium">
                  {v == null ? "—" : `${Number(v).toFixed(digits)}${suffix}`}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Per-Position Sharpe ── */}
      {Object.keys(perTicker).length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Per-Position Sharpe (Individual)</p>
          <p className="text-bloomberg-muted text-[10px] mb-3">
            Sharpe ratio computed from each ticker&apos;s own return history — not weighted by portfolio.
          </p>
          <table className="bbg-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th className="text-right">Ann. Return</th>
                <th className="text-right">Ann. Vol</th>
                <th className="text-right">Sharpe</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(perTicker)
                .sort(([, a], [, b]) => b.sharpe - a.sharpe)
                .map(([ticker, s]) => (
                  <tr key={ticker}>
                    <td className="text-bloomberg-gold font-medium">{ticker}</td>
                    <td className={`text-right ${(s.ann_return ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {s.ann_return != null ? fmtPct(s.ann_return) : "—"}
                    </td>
                    <td className="text-right text-bloomberg-muted">{fmtPct(s.ann_vol)}</td>
                    <td className={`text-right font-medium ${s.sharpe >= 1 ? "text-green-400" : s.sharpe >= 0 ? "text-bloomberg-gold" : "text-red-400"}`}>
                      {s.sharpe.toFixed(3)}
                    </td>
                  </tr>
                ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-bloomberg-border">
                <td className="font-semibold text-bloomberg-text pt-2">Portfolio (current)</td>
                <td className="text-right pt-2 text-green-600 font-semibold">{metrics.annualized_return != null ? fmtPct(metrics.annualized_return) : "—"}</td>
                <td className="text-right pt-2 text-bloomberg-muted font-semibold">{metrics.annualized_vol != null ? fmtPct(metrics.annualized_vol) : "—"}</td>
                <td className="text-right pt-2 font-bold text-bloomberg-text">{metrics.sharpe?.toFixed(3) ?? "—"}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {/* ── Fama-French 3-Factor ── */}
      {Object.keys(ff).length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Fama-French 3-Factor Model</p>
          <p className="text-bloomberg-muted text-[10px] mb-3">
            OLS regression of portfolio excess returns on market (SPY), size (IWM−SPY), and value (IVE−IVW) factors.
            t-stats shown in parentheses — |t| &gt; 2 is significant.
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <div className="bbg-card">
              <p className="text-bloomberg-muted text-[10px]">Alpha (ann.)</p>
              <p className={`text-sm font-bold ${(ff.alpha_annual ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                {fmtPct(ff.alpha_annual ?? 0)}
              </p>
              <p className="text-bloomberg-muted text-[9px]">t = {fmt(ff.t_alpha)}</p>
            </div>
            <div className="bbg-card">
              <p className="text-bloomberg-muted text-[10px]">β Market (Mkt-RF)</p>
              <p className="text-bloomberg-text text-sm font-bold">{fmt(ff.beta_mkt)}</p>
              <p className="text-bloomberg-muted text-[9px]">t = {fmt(ff.t_mkt)}</p>
            </div>
            <div className="bbg-card">
              <p className="text-bloomberg-muted text-[10px]">β SMB (Size)</p>
              <p className="text-bloomberg-text text-sm font-bold">{fmt(ff.beta_smb)}</p>
              <p className="text-bloomberg-muted text-[9px]">t = {fmt(ff.t_smb)}</p>
            </div>
            <div className="bbg-card">
              <p className="text-bloomberg-muted text-[10px]">β HML (Value)</p>
              <p className="text-bloomberg-text text-sm font-bold">{fmt(ff.beta_hml)}</p>
              <p className="text-bloomberg-muted text-[9px]">t = {fmt(ff.t_hml)}</p>
            </div>
          </div>
          <div className="flex gap-6 text-[10px]">
            <span className="text-bloomberg-muted">R² <span className="text-bloomberg-text font-bold">{ff.r_squared != null ? (ff.r_squared * 100).toFixed(2) : "—"}%</span></span>
            <span className="text-bloomberg-muted">N obs <span className="text-bloomberg-text">{ff.n_obs ?? "—"}</span></span>
            <span className="text-bloomberg-muted text-[9px] self-end">Proxies: Market=SPY · SMB=IWM−SPY · HML=IVE−IVW</span>
          </div>
        </div>
      )}

      {/* ── Volatility Regime ── */}
      {vrChart.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Volatility Regime (21-day rolling)</p>
          <div className="flex gap-4 mb-2 text-[10px]">
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-green-500/50 rounded-sm" /> Low (&lt;{lowThr.toFixed(1)}%)</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-yellow-500/50 rounded-sm" /> Medium</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-red-500/50 rounded-sm" /> High (&gt;{highThr.toFixed(1)}%)</span>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart data={vrChart} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} interval="preserveStartEnd" />
              <YAxis
                tick={{ fontSize: 9, fill: "#8a9bb5" }}
                tickLine={false}
                axisLine={false}
                width={40}
                tickFormatter={(v) => `${v.toFixed(0)}%`}
              />
              <Tooltip
                contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                formatter={(v: number, _n: string, props: { payload?: { regime?: string } }) => [
                  `${v.toFixed(2)}% — ${props.payload?.regime ?? ""}`,
                  "Vol",
                ]}
              />
              {/* Shade high-vol periods */}
              {highVolRanges.map((r, i) => (
                <ReferenceArea key={i} x1={r.x1} x2={r.x2} fill="#ff4d4d" fillOpacity={0.12} stroke="none" />
              ))}
              <ReferenceLine y={lowThr} stroke="#4dff4d" strokeDasharray="3 3" strokeWidth={1} />
              <ReferenceLine y={highThr} stroke="#ff4d4d" strokeDasharray="3 3" strokeWidth={1} />
              <Area
                type="monotone"
                dataKey="vol"
                stroke="#f3a712"
                strokeWidth={1.5}
                fill="#f3a71210"
                dot={false}
                name="Rolling Vol"
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Cumulative Return chart ── */}
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

      {/* ── Rolling Sharpe ── */}
      {rolling.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Rolling Sharpe Ratio</p>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={rolling} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false} width={35} />
              <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }} />
              <ReferenceLine y={0} stroke="#8a9bb5" strokeWidth={0.5} />
              <ReferenceLine y={1} stroke="#f3a712" strokeDasharray="3 3" strokeWidth={0.8} />
              <Line type="monotone" dataKey="sharpe" stroke="#f3a712" strokeWidth={1.5} dot={false} name="Sharpe" />
              <Line type="monotone" dataKey="sortino" stroke="#38b2ff" strokeWidth={1} dot={false} strokeDasharray="3 3" name="Sortino" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Rolling Volatility & Drawdown ── */}
      {rollingFull && (rollingFull as { date: string; volatility: number | null }[]).length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Rolling Volatility & Drawdown (63-day)</p>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={rollingFull as object[]} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} interval="preserveStartEnd" />
              <YAxis yAxisId="vol" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false} width={40}
                tickFormatter={(v) => `${v.toFixed(0)}%`} />
              <YAxis yAxisId="dd" orientation="right" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false} width={40}
                tickFormatter={(v) => `${v.toFixed(0)}%`} />
              <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                formatter={(v: number) => `${v.toFixed(2)}%`} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Line yAxisId="vol" type="monotone" dataKey="volatility" stroke="#f3a712" strokeWidth={1.5} dot={false} name="Volatility" />
              <Line yAxisId="dd" type="monotone" dataKey="drawdown" stroke="#ff4d4d" strokeWidth={1} dot={false} name="Drawdown" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Monthly Returns Calendar ── */}
      {monthly_returns.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Monthly Returns</p>
          <div className="overflow-x-auto">
            <table className="bbg-table text-center">
              <thead>
                <tr>
                  <th className="text-left">Year</th>
                  {MONTHS_SHORT.map((m, i) => (
                    <th key={m} className={i % 3 !== 0 ? "hidden sm:table-cell" : ""}>{m}</th>
                  ))}
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
                          <td key={i} className={`${v == null ? "muted" : v >= 0 ? "positive" : "negative"}${i % 3 !== 0 ? " hidden sm:table-cell" : ""}`}>
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

      {/* ── Drawdown Episodes ── */}
      {drawdown_episodes.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Top Drawdown Episodes</p>
          <table className="bbg-table">
            <thead>
              <tr>
                <th>Start</th><th>Trough</th><th>Recovery</th>
                <th className="text-right">Depth</th><th className="text-right">Duration</th>
              </tr>
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

      {/* ── Tax-Loss Harvesting ── */}
      {taxLoss && taxLoss.candidates.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Tax-Loss Harvesting Candidates</p>
          <p className="text-bloomberg-muted text-[10px] mb-3">
            Positions with unrealized losses &gt; 5%. Consult a tax advisor before acting. IRS wash-sale rule: 30-day window.
          </p>
          <table className="bbg-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th className="text-right">P&L</th>
                <th className="text-right">Loss %</th>
                <th className="text-right">Cost Basis</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {taxLoss.candidates.map((c) => (
                <tr key={c.ticker} className={c.wash_sale_risk ? "opacity-60" : ""}>
                  <td className="text-bloomberg-gold font-bold">{c.ticker}</td>
                  <td className="text-right text-red-400">{taxLoss.base_currency} {c.unrealized_pnl.toLocaleString(undefined, {maximumFractionDigits: 2})}</td>
                  <td className="text-right text-red-400 font-bold">{c.unrealized_pct.toFixed(1)}%</td>
                  <td className="text-right text-bloomberg-muted">{taxLoss.base_currency} {c.cost_basis.toLocaleString(undefined, {maximumFractionDigits: 2})}</td>
                  <td>
                    <div className="text-[10px]">
                      {c.wash_sale_risk && <span className="text-yellow-400 mr-1">⚠ Wash sale risk.</span>}
                      <span className="text-bloomberg-muted">{c.action}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Quant Advanced Analytics (manual trigger) ── */}
      {qa && (() => {
        const pct = (v: number | null | undefined, d = 1) =>
          v == null ? "—" : `${(v * 100).toFixed(d)}%`;

        return (
          <>
            {/* Factor Risk Decomposition */}
            {qa.factor_risk && qa.factor_risk.per_asset && Object.keys(qa.factor_risk.per_asset).length > 0 && (
              <div className="bbg-card">
                <p className="bbg-header">Factor Risk Decomposition</p>
                <div className="flex flex-wrap gap-4 text-[10px] mb-2">
                  <span className="text-bloomberg-muted">
                    Portfolio vol: <span className="text-bloomberg-gold font-bold">{pct(qa.factor_risk.portfolio_vol)}</span>
                  </span>
                  {qa.factor_risk.factor_decomposition?.r_squared != null && (
                    <>
                      <span className="text-bloomberg-muted">
                        Systematic: <span className="text-bloomberg-text">{qa.factor_risk.factor_decomposition.systematic_risk_pct as number}%</span>
                      </span>
                      <span className="text-bloomberg-muted">
                        Idiosyncratic: <span className="text-bloomberg-text">{qa.factor_risk.factor_decomposition.idiosyncratic_risk_pct as number}%</span>
                      </span>
                    </>
                  )}
                </div>
                <table className="bbg-table text-[10px]">
                  <thead>
                    <tr>
                      <th>Ticker</th>
                      <th className="text-right">Weight</th>
                      <th className="text-right">Vol Contribution</th>
                      <th className="text-right">% of Portfolio Vol</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(qa.factor_risk.per_asset)
                      .sort(([, a], [, b]) => b.vol_contribution_pct - a.vol_contribution_pct)
                      .map(([ticker, a]) => (
                        <tr key={ticker}>
                          <td className="text-bloomberg-gold font-medium">{ticker}</td>
                          <td className="text-right">{(a.weight * 100).toFixed(1)}%</td>
                          <td className="text-right text-bloomberg-muted">{pct(a.vol_contribution)}</td>
                          <td className={`text-right font-medium ${a.vol_contribution_pct > 30 ? "text-red-400" : a.vol_contribution_pct > 15 ? "text-bloomberg-gold" : "text-bloomberg-text"}`}>
                            {a.vol_contribution_pct.toFixed(1)}%
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Tracking Error Budget */}
            {qa.tracking_error_budget && qa.tracking_error_budget.total_te != null && (
              <div className="bbg-card">
                <p className="bbg-header">Tracking Error Budget</p>
                <div className="flex flex-wrap gap-4 text-[10px] mb-3">
                  <span className="text-bloomberg-muted">
                    TE (actual): <span className="text-bloomberg-gold font-bold">{pct(qa.tracking_error_budget.total_te)}</span>
                  </span>
                  <span className="text-bloomberg-muted">
                    Budget: <span className="text-bloomberg-text">{pct(qa.tracking_error_budget.te_budget)}</span>
                  </span>
                  <span className="text-bloomberg-muted">
                    Used: <span className={`font-bold ${qa.tracking_error_budget.within_budget ? "text-green-400" : "text-red-400"}`}>
                      {qa.tracking_error_budget.budget_used_pct.toFixed(1)}%
                    </span>
                  </span>
                  <span className={qa.tracking_error_budget.within_budget ? "text-green-400 font-bold" : "text-red-400 font-bold"}>
                    {qa.tracking_error_budget.within_budget ? "WITHIN BUDGET" : "OVER BUDGET"}
                  </span>
                </div>
                {qa.tracking_error_budget.per_asset && Object.keys(qa.tracking_error_budget.per_asset).length > 0 && (
                  <table className="bbg-table text-[10px]">
                    <thead>
                      <tr>
                        <th>Ticker</th>
                        <th className="text-right">TE Contribution</th>
                        <th className="text-right">Share of TE</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(qa.tracking_error_budget.per_asset)
                        .sort(([, a], [, b]) => b.te_share_pct - a.te_share_pct)
                        .map(([ticker, te]) => (
                          <tr key={ticker}>
                            <td className="text-bloomberg-gold font-medium">{ticker}</td>
                            <td className="text-right text-bloomberg-muted">{pct(te.te_contribution)}</td>
                            <td className={`text-right font-medium ${te.te_share_pct > 30 ? "text-red-400" : "text-bloomberg-text"}`}>
                              {te.te_share_pct.toFixed(1)}%
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {/* EWMA Regime Analysis */}
            {qa.regime && qa.regime.current_regime && (
              <div className="bbg-card">
                <p className="bbg-header">Quant Regime Analysis (EWMA-based)</p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                  <div className="bbg-card">
                    <p className="text-bloomberg-muted text-[10px]">Current Regime</p>
                    <p className={`text-sm font-bold ${qa.regime.current_regime === "low" ? "text-green-400" : qa.regime.current_regime === "normal" ? "text-bloomberg-gold" : qa.regime.current_regime === "high" ? "text-orange-400" : "text-red-400"}`}>
                      {qa.regime.current_regime.toUpperCase()}
                    </p>
                  </div>
                  <div className="bbg-card">
                    <p className="text-bloomberg-muted text-[10px]">Current Vol</p>
                    <p className="text-bloomberg-text text-sm font-bold">{pct(qa.regime.current_vol)}</p>
                  </div>
                  <div className="bbg-card">
                    <p className="text-bloomberg-muted text-[10px]">Equity Tilt</p>
                    <p className={`text-sm font-bold ${qa.regime.strategic.equity_tilt >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {qa.regime.strategic.equity_tilt >= 0 ? "+" : ""}{(qa.regime.strategic.equity_tilt * 100).toFixed(0)}%
                    </p>
                  </div>
                  <div className="bbg-card">
                    <p className="text-bloomberg-muted text-[10px]">Execution Hold</p>
                    <p className={`text-sm font-bold ${qa.regime.execution.hold ? "text-red-400" : "text-green-400"}`}>
                      {qa.regime.execution.hold ? "HOLD" : "GO"}
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-3 text-[10px]">
                  {Object.entries(qa.regime.regime_probabilities).map(([name, prob]) => (
                    <div key={name} className="flex flex-col items-center">
                      <span className="text-bloomberg-muted uppercase">{name}</span>
                      <span className="text-bloomberg-text font-bold">{(prob * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                </div>
                {qa.regime.execution.hold && qa.regime.execution.reason && (
                  <p className="text-bloomberg-gold text-[10px] mt-2">
                    Hold reason: {qa.regime.execution.reason}
                  </p>
                )}
              </div>
            )}

            {/* Naive Portfolio Benchmarks */}
            {qa.naive_benchmarks && qa.naive_benchmarks.length > 0 && (
              <div className="bbg-card">
                <p className="bbg-header">Portfolio vs Naive Benchmarks</p>
                <table className="bbg-table text-[10px]">
                  <thead>
                    <tr>
                      <th>Model</th>
                      <th className="text-right">Ann. Return</th>
                      <th className="text-right">Volatility</th>
                      <th className="text-right">Sharpe</th>
                      <th className="text-right">Cum. Return</th>
                      <th className="text-right">Max DD</th>
                    </tr>
                  </thead>
                  <tbody>
                    {qa.naive_benchmarks.map((row) => (
                      <tr key={row.model} className={row.model === "Your Portfolio" ? "border-t-2 border-bloomberg-gold" : ""}>
                        <td className={row.model === "Your Portfolio" ? "text-bloomberg-gold font-bold" : "text-bloomberg-text"}>
                          {row.model}
                        </td>
                        <td className={`text-right ${row.ann_return >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {pct(row.ann_return)}
                        </td>
                        <td className="text-right text-bloomberg-muted">{pct(row.volatility)}</td>
                        <td className={`text-right font-medium ${row.sharpe >= 1 ? "text-green-400" : row.sharpe >= 0 ? "text-bloomberg-gold" : "text-red-400"}`}>
                          {row.sharpe.toFixed(3)}
                        </td>
                        <td className={`text-right ${row.cum_return >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {pct(row.cum_return)}
                        </td>
                        <td className="text-right text-red-400">{pct(row.max_dd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Walk-Forward Validation */}
            {qa.walk_forward && qa.walk_forward.folds && qa.walk_forward.folds.length > 0 && (
              <div className="bbg-card">
                <p className="bbg-header">Walk-Forward Validation (Out-of-Sample)</p>
                <div className="flex flex-wrap gap-4 text-[10px] mb-2">
                  <span className="text-bloomberg-muted">
                    OOS Sharpe: <span className={`font-bold ${qa.walk_forward.oos_mean_sharpe >= 0.5 ? "text-green-400" : "text-bloomberg-gold"}`}>
                      {qa.walk_forward.oos_mean_sharpe.toFixed(3)} ±{qa.walk_forward.oos_sharpe_std.toFixed(3)}
                    </span>
                  </span>
                  <span className="text-bloomberg-muted">
                    Consistent edge: <span className={qa.walk_forward.consistent_edge ? "text-green-400 font-bold" : "text-red-400 font-bold"}>
                      {qa.walk_forward.consistent_edge ? "YES" : "NO"}
                    </span>
                  </span>
                  <span className="text-bloomberg-muted">
                    Positive folds: <span className="text-bloomberg-text">{qa.walk_forward.n_positive_folds}/{qa.walk_forward.folds.length}</span>
                  </span>
                </div>
                <table className="bbg-table text-[10px]">
                  <thead>
                    <tr>
                      <th>Fold</th>
                      <th>Period</th>
                      <th className="text-right">Ann. Return</th>
                      <th className="text-right">Sharpe</th>
                      <th className="text-right">Alpha</th>
                    </tr>
                  </thead>
                  <tbody>
                    {qa.walk_forward.folds.map((f) => (
                      <tr key={f.fold}>
                        <td className="text-bloomberg-muted">{f.fold}</td>
                        <td className="text-bloomberg-muted text-[9px]">{f.start} → {f.end}</td>
                        <td className={`text-right ${f.ann_return >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {pct(f.ann_return)}
                        </td>
                        <td className={`text-right font-medium ${f.sharpe >= 1 ? "text-green-400" : f.sharpe >= 0 ? "text-bloomberg-gold" : "text-red-400"}`}>
                          {f.sharpe.toFixed(3)}
                        </td>
                        <td className={`text-right ${f.alpha >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {pct(f.alpha)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        );
      })()}

      {/* ── Kelly Position Sizing ── */}
      <div className="bbg-card">
        <p className="bbg-header">Kelly Position Sizing Calculator</p>
        <p className="text-bloomberg-muted text-[10px] mb-3">Tamaño óptimo de posición según el criterio de Kelly. Se recomienda ½ Kelly para gestión del riesgo de ruina.</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">Ticker</label>
            <input type="text" value={kellyTicker} onChange={(e) => setKellyTicker(e.target.value.toUpperCase())}
              placeholder="NVDA" className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold uppercase" />
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">Convicción (%)</label>
            <input type="number" min={10} max={100} value={kellyConviction} onChange={(e) => setKellyConviction(Number(e.target.value))}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold" />
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">Retorno esperado (%)</label>
            <input type="number" min={1} max={100} value={kellyExpRet} onChange={(e) => setKellyExpRet(Number(e.target.value))}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold" />
          </div>
          <div className="flex items-end">
            <button onClick={runKelly} disabled={kellyLoading || !kellyTicker}
              className="w-full bg-bloomberg-gold text-bloomberg-bg text-[10px] font-bold px-3 py-1.5 hover:opacity-90 disabled:opacity-50 uppercase tracking-wider">
              {kellyLoading ? "…" : "Calcular"}
            </button>
          </div>
        </div>
        {kellyResult && (
          <div className="border-t border-bloomberg-border pt-3 space-y-3">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                { label: "Kelly Completo", value: `${kellyResult.kelly_pct.toFixed(1)}%`, sub: "Alto riesgo" },
                { label: "½ Kelly (recomendado)", value: `${kellyResult.half_kelly_pct.toFixed(1)}%`, sub: "Estándar" },
                { label: "¼ Kelly (conservador)", value: `${kellyResult.quarter_kelly_pct.toFixed(1)}%`, sub: "Máxima protección" },
                { label: "Monto ½ Kelly", value: `$${kellyResult.recommended_amount.toLocaleString(undefined, {maximumFractionDigits: 0})}`, sub: "Estimado" },
              ].map(({ label, value, sub }) => (
                <div key={label} className="border border-bloomberg-border p-2">
                  <p className="text-bloomberg-muted text-[9px] uppercase tracking-widest">{label}</p>
                  <p className="text-bloomberg-gold text-lg font-black mt-0.5">{value}</p>
                  <p className="text-bloomberg-muted text-[9px]">{sub}</p>
                </div>
              ))}
            </div>
            <p className="text-bloomberg-muted text-[10px]">
              <span className="text-bloomberg-text">Análisis:</span> {kellyResult.rationale} &middot; Vol estimada: {kellyResult.inputs.estimated_ann_vol_pct.toFixed(1)}%
            </p>
          </div>
        )}
      </div>

      {/* ── Monte Carlo Goal Simulator ── */}
      <div className="bbg-card">
        <p className="bbg-header">Monte Carlo — Simulador de Meta Financiera</p>
        <p className="text-bloomberg-muted text-[10px] mb-3">Proyección con DCA mensual usando 5,000 simulaciones basadas en el retorno/volatilidad histórica del portafolio.</p>
        <div className="grid grid-cols-3 gap-3 mb-3">
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">Aporte mensual ($)</label>
            <input type="number" min={0} value={mcMonthly} onChange={(e) => setMcMonthly(Number(e.target.value))}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold" />
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">Años</label>
            <input type="number" min={1} max={40} value={mcYears} onChange={(e) => setMcYears(Number(e.target.value))}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold" />
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">Meta ($)</label>
            <input type="number" min={1000} value={mcTarget} onChange={(e) => setMcTarget(Number(e.target.value))}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold" />
          </div>
        </div>
        <button onClick={runMC} disabled={mcLoading}
          className="bg-bloomberg-gold text-bloomberg-bg text-[10px] font-bold px-4 py-1.5 hover:opacity-90 disabled:opacity-50 uppercase tracking-wider mb-4">
          {mcLoading ? "Simulando…" : "Ejecutar Simulación"}
        </button>
        {mcResult && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                { label: "Prob. de meta", value: `${mcResult.probability_of_goal.toFixed(1)}%`, color: mcResult.probability_of_goal >= 70 ? "text-green-400" : mcResult.probability_of_goal >= 40 ? "text-bloomberg-gold" : "text-red-400" },
                { label: `Mediana (año ${mcResult.years})`, value: `$${mcResult.median_outcome.toLocaleString(undefined, {maximumFractionDigits: 0})}`, color: "text-bloomberg-text" },
                { label: "Retorno anual", value: `${mcResult.ann_return_pct.toFixed(1)}%`, color: "text-bloomberg-muted" },
                { label: "Volatilidad", value: `${mcResult.ann_vol_pct.toFixed(1)}%`, color: "text-bloomberg-muted" },
              ].map(({ label, value, color }) => (
                <div key={label} className="border border-bloomberg-border p-2">
                  <p className="text-bloomberg-muted text-[9px] uppercase tracking-widest">{label}</p>
                  <p className={`text-sm font-black mt-0.5 ${color}`}>{value}</p>
                </div>
              ))}
            </div>
            {mcResult.fan_series.length > 0 && (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={mcResult.fan_series} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e2530" />
                    <XAxis dataKey="year" tick={{ fill: "#6b7280", fontSize: 9 }} tickFormatter={(v) => `Y${v}`} />
                    <YAxis tick={{ fill: "#6b7280", fontSize: 9 }} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} width={48} />
                    <Tooltip contentStyle={{ background: "#0b0f14", border: "1px solid #1e2530", fontSize: 11 }}
                      formatter={(v: number) => [`$${v.toLocaleString(undefined, {maximumFractionDigits: 0})}`, ""]} />
                    <Area type="monotone" dataKey="p95" stroke="none" fill="#f3a71210" />
                    <Area type="monotone" dataKey="p75" stroke="none" fill="#f3a71218" />
                    <Area type="monotone" dataKey="p25" stroke="none" fill="#f3a71208" />
                    <Line type="monotone" dataKey="median" stroke="#f3a712" strokeWidth={2} dot={false} name="Mediana" />
                    <Line type="monotone" dataKey="p95" stroke="#4dff4d" strokeWidth={1} dot={false} strokeDasharray="3 3" name="P95" />
                    <Line type="monotone" dataKey="p5" stroke="#ff4d4d" strokeWidth={1} dot={false} strokeDasharray="3 3" name="P5" />
                    <ReferenceLine y={mcResult.target_goal} stroke="#f3a712" strokeDasharray="5 5" />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            )}
            <p className="text-bloomberg-muted text-[9px]">Rango P5–P95 sombreado · Línea punteada = meta · {mcResult.n_sims.toLocaleString()} simulaciones Monte Carlo.</p>
          </div>
        )}
      </div>

      {/* ── Return Attribution ── */}
      {attribution && attribution.rows.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Atribución de Retornos por Posición</p>
          <table className="bbg-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th className="text-right">Precio</th>
                <th className="text-right">FX</th>
                <th className="text-right">Dividendo</th>
                <th className="text-right">Total</th>
                <th className="text-right">P&L ({attribution.base_currency})</th>
              </tr>
            </thead>
            <tbody>
              {attribution.rows.map((r) => (
                <tr key={r.ticker}>
                  <td className="text-bloomberg-gold font-bold">{r.ticker}</td>
                  <td className={`text-right ${r.price_return_pct >= 0 ? "text-green-400" : "text-red-400"}`}>{r.price_return_pct >= 0 ? "+" : ""}{r.price_return_pct.toFixed(2)}%</td>
                  <td className="text-right text-bloomberg-muted">{r.fx_return_pct !== 0 ? `${r.fx_return_pct >= 0 ? "+" : ""}${r.fx_return_pct.toFixed(2)}%` : "—"}</td>
                  <td className={`text-right ${r.dividend_return_pct > 0 ? "text-green-400" : "text-bloomberg-muted"}`}>{r.dividend_return_pct > 0 ? `+${r.dividend_return_pct.toFixed(2)}%` : "—"}</td>
                  <td className={`text-right font-bold ${r.total_return_pct >= 0 ? "text-green-400" : "text-red-400"}`}>{r.total_return_pct >= 0 ? "+" : ""}{r.total_return_pct.toFixed(2)}%</td>
                  <td className={`text-right ${r.unrealized_pnl_base >= 0 ? "text-green-400" : "text-red-400"}`}>{r.unrealized_pnl_base >= 0 ? "+" : ""}{r.unrealized_pnl_base.toLocaleString(undefined, {maximumFractionDigits: 0})}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-bloomberg-border">
                <td className="font-bold text-bloomberg-text pt-2">Total</td>
                <td colSpan={3} />
                <td className={`text-right font-black pt-2 ${attribution.totals.total_return_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {attribution.totals.total_return_pct >= 0 ? "+" : ""}{attribution.totals.total_return_pct.toFixed(2)}%
                </td>
                <td className={`text-right font-black pt-2 ${attribution.totals.total_pnl_base >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {attribution.totals.total_pnl_base >= 0 ? "+" : ""}{attribution.totals.total_pnl_base.toLocaleString(undefined, {maximumFractionDigits: 0})}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {/* ── Portfolio News Feed ── */}
      {portfolioNews && portfolioNews.items.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">News Feed — Portafolio</p>
          <div className="space-y-2">
            {portfolioNews.items.map((item, i) => (
              <div key={i} className="flex items-start gap-3 border-b border-bloomberg-border/40 pb-2">
                <span className="text-bloomberg-gold font-bold text-[10px] w-16 shrink-0">{item.ticker}</span>
                <div className="flex-1 min-w-0">
                  {item.url ? (
                    <a href={item.url} target="_blank" rel="noopener noreferrer"
                      className="text-bloomberg-text text-[10px] hover:text-bloomberg-gold leading-snug line-clamp-2 block">
                      {item.title}
                    </a>
                  ) : (
                    <p className="text-bloomberg-text text-[10px] leading-snug line-clamp-2">{item.title}</p>
                  )}
                  <p className="text-bloomberg-muted text-[9px] mt-0.5">{item.source && `${item.source} · `}{item.published}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
