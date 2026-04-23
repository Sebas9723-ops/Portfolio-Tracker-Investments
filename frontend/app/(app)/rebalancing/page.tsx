"use client";
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchRebalancing, fetchRequiredForMaxSharpe } from "@/lib/api/analytics";
import { fetchContributionPlan } from "@/lib/api/contribution";
import type { ContributionPlanResponse } from "@/lib/api/contribution";
import { useAIChat } from "@/lib/context/aiChatContext";
import { fetchSettings, updateSettings } from "@/lib/api/settings";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { useProfileStore } from "@/lib/store/profileStore";
import { fmtCurrency, fmtPct } from "@/lib/formatters";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, ReferenceLine,
} from "recharts";
import type { TickerFloorCap, CombinationRange } from "@/lib/types";
import { QuantResultBadge } from "@/components/quant/QuantResultBadge";
import { CorrelationAlerts } from "@/components/quant/CorrelationAlerts";
import { SlippageBreakdown } from "@/components/quant/SlippageBreakdown";

const PROFILE_LABELS: Record<string, { label: string; color: string; bg: string }> = {
  conservative: { label: "Conservative", color: "#2563eb", bg: "#eff6ff" },
  base:         { label: "Base",         color: "#16a34a", bg: "#f0fdf4" },
  aggressive:   { label: "Aggressive",   color: "#dc2626", bg: "#fef2f2" },
};

function ProfileBadge() {
  const { profile } = useProfileStore();
  const info = PROFILE_LABELS[profile];
  if (!info) return null;
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold"
      style={{ color: info.color, background: info.bg }}
    >
      Profile: {info.label}
    </span>
  );
}

function DriftBadge({ drift, threshold }: { drift: number; threshold: number }) {
  if (drift > threshold) {
    return (
      <span className="px-1.5 py-0.5 text-[9px] font-bold bg-red-900/40 text-red-400 border border-red-800">
        OVERWEIGHT
      </span>
    );
  }
  if (drift < -threshold) {
    return (
      <span className="px-1.5 py-0.5 text-[9px] font-bold bg-green-900/30 text-green-400 border border-green-800">
        UNDERWEIGHT
      </span>
    );
  }
  return (
    <span className="px-1.5 py-0.5 text-[9px] font-bold bg-bloomberg-bg text-bloomberg-muted border border-bloomberg-border">
      ON TARGET
    </span>
  );
}

export default function RebalancingPage() {
  const { openWith } = useAIChat();
  const [contributionStr, setContributionStr] = useState("0");
  const contribution = parseFloat(contributionStr) || 0;
  const [tcModel, setTcModel] = useState("broker");
  const [msPeriod, setMsPeriod] = useState("2y");
  const [quantData, setQuantData] = useState<ContributionPlanResponse | null>(null);
  const [quantError, setQuantError] = useState<string | null>(null);
  const [horizon, setHorizon] = useState<"short" | "medium" | "long">("long");
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });

  // Sync horizon from persisted settings on load
  useEffect(() => {
    if (settings?.time_horizon) {
      setHorizon(settings.time_horizon);
    }
  }, [settings?.time_horizon]);

  const handleSetHorizon = (h: "short" | "medium" | "long") => {
    setHorizon(h);
    updateSettings({ time_horizon: h }).then(() => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    });
  };

  const quantMutation = useMutation({
    mutationFn: fetchContributionPlan,
    onSuccess: (data) => {
      setQuantData(data);
      setQuantError(null);
    },
    onError: (err: Error) => {
      setQuantError(err.message ?? "Optimization failed");
    },
  });

  const { data: portfolio } = usePortfolio();
  const { profile } = useProfileStore();
  const rows = portfolio?.rows ?? [];
  const totalValue = portfolio?.total_value_base ?? 0;
  const ccy = portfolio?.base_currency ?? "USD";

  // Motor 1 & 2 — active constraints for the current profile
  const motor1Rules: Record<string, TickerFloorCap> = settings?.ticker_weight_rules?.[profile] ?? {};
  const motor2Ranges: CombinationRange[] = settings?.combination_ranges?.[profile] ?? [];

  const { data, isLoading } = useQuery({
    queryKey: ["rebalancing", contribution, tcModel],
    queryFn: () => fetchRebalancing({ contribution, tc_model: tcModel }),
  });

  const msMaxSingle = settings?.max_single_asset ?? 0.40;
  const { data: msData, isLoading: msLoading, refetch: refetchMs } = useQuery({
    queryKey: ["rebalancing-max-sharpe", msPeriod, msMaxSingle],
    queryFn: () => fetchRequiredForMaxSharpe({ period: msPeriod, max_single_asset: msMaxSingle }),
    enabled: false,
  });

  const totalTC = data?.reduce((s, r) => s + r.estimated_tc, 0) ?? 0;
  const threshold = 5; // 5% drift threshold for badge (display only)


  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Rebalancing</h1>
        <ProfileBadge />
      </div>

      {/* Parameters */}
      <div className="bbg-card">
        <p className="bbg-header">Parameters</p>
        <div className="flex flex-wrap gap-6 items-end">
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Cash to Deploy ({ccy})</label>
            <input
              type="number"
              value={contributionStr}
              onChange={(e) => setContributionStr(e.target.value)}
              className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs w-36 focus:outline-none focus:border-bloomberg-gold"
              step="100"
            />
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Broker Model</label>
            <select
              value={tcModel}
              onChange={(e) => setTcModel(e.target.value)}
              className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs"
            >
              {["broker", "etoro", "degiro", "ib"].map((m) => <option key={m}>{m}</option>)}
            </select>
          </div>
          <div className="text-bloomberg-muted text-xs">
            Est. total TC: <span className="text-bloomberg-gold">{fmtCurrency(totalTC)}</span>
          </div>
        </div>
      </div>

      {/* Active Constraints (Motor 1 + Motor 2) */}
      {(Object.keys(motor1Rules).length > 0 || motor2Ranges.length > 0) && (
        <div className="bbg-card">
          <p className="bbg-header">Active Constraints — {profile.charAt(0).toUpperCase() + profile.slice(1)} Profile</p>
          <p className="text-bloomberg-muted text-[10px] mb-3">
            These rules are applied when computing target weights and the contribution plan. Edit them in Optimization → Motor 1 / Motor 2.
          </p>
          <div className="flex flex-wrap gap-6">
            {Object.keys(motor1Rules).length > 0 && (
              <div>
                <p className="text-bloomberg-muted text-[10px] uppercase mb-1">Motor 1 — Floor / Cap per Ticker</p>
                <table className="bbg-table text-xs">
                  <thead>
                    <tr>
                      <th>Ticker</th>
                      <th className="text-right">Floor</th>
                      <th className="text-right">Cap</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(motor1Rules).map(([t, rule]) => (
                      <tr key={t}>
                        <td className="text-bloomberg-gold font-medium">{t}</td>
                        <td className="text-right text-bloomberg-muted">{fmtPct((rule.floor ?? 0) * 100)}</td>
                        <td className="text-right text-bloomberg-muted">{fmtPct((rule.cap ?? 1) * 100)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {motor2Ranges.length > 0 && (
              <div>
                <p className="text-bloomberg-muted text-[10px] uppercase mb-1">Motor 2 — Combination Ranges</p>
                <table className="bbg-table text-xs">
                  <thead>
                    <tr>
                      <th>Tickers</th>
                      <th className="text-right">Min</th>
                      <th className="text-right">Max</th>
                    </tr>
                  </thead>
                  <tbody>
                    {motor2Ranges.map((r) => (
                      <tr key={r.id}>
                        <td className="text-bloomberg-gold font-medium">{r.tickers.join(" + ")}</td>
                        <td className="text-right text-bloomberg-muted">{r.min != null ? fmtPct(r.min) : "—"}</td>
                        <td className="text-right text-bloomberg-muted">{r.max != null ? fmtPct(r.max) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Deviation Monitor */}
      <div className="bbg-card">
        <p className="bbg-header">Deviation Monitor</p>
        {isLoading ? (
          <div className="text-bloomberg-muted text-xs py-4">Loading…</div>
        ) : (
          <>
            <div className="overflow-x-auto mb-4">
              <table className="bbg-table">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Name</th>
                    <th className="text-right">Current%</th>
                    <th className="text-right">Target%</th>
                    <th className="text-right">Drift%</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {(data ?? []).map((r) => (
                    <tr key={r.ticker}>
                      <td className="text-bloomberg-gold font-medium">{r.ticker}</td>
                      <td className="text-bloomberg-muted">{r.name}</td>
                      <td className="text-right">{fmtPct(r.current_weight)}</td>
                      <td className="text-right">{fmtPct(r.target_weight)}</td>
                      <td className={`text-right font-medium ${r.drift > 0 ? "text-red-400" : r.drift < 0 ? "text-green-400" : "text-bloomberg-muted"}`}>
                        {r.drift > 0 ? "+" : ""}{fmtPct(r.drift)}
                      </td>
                      <td>
                        <DriftBadge drift={r.drift} threshold={threshold} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Drift chart */}
            {data && data.length > 0 && (
              <ResponsiveContainer width="100%" height={Math.max(160, data.length * 28)}>
                <BarChart
                  data={data}
                  margin={{ top: 5, right: 20, bottom: 5, left: 20 }}
                  layout="vertical"
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" horizontal={false} />
                  <XAxis
                    type="number"
                    tick={{ fontSize: 9, fill: "#8a9bb5" }}
                    tickLine={false}
                    tickFormatter={(v) => `${v.toFixed(1)}%`}
                  />
                  <YAxis
                    dataKey="ticker"
                    type="category"
                    tick={{ fontSize: 10, fill: "#f3a712" }}
                    tickLine={false}
                    axisLine={false}
                    width={60}
                  />
                  <Tooltip
                    contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                    formatter={(v: number) => [`${v.toFixed(2)}%`, "Drift"]}
                  />
                  <ReferenceLine x={0} stroke="#8a9bb5" strokeWidth={1} />
                  <ReferenceLine x={threshold} stroke="#ff4d4d" strokeDasharray="3 3" strokeWidth={1} />
                  <ReferenceLine x={-threshold} stroke="#4dff4d" strokeDasharray="3 3" strokeWidth={1} />
                  <Bar dataKey="drift" barSize={12}>
                    {(data ?? []).map((r) => (
                      <Cell
                        key={r.ticker}
                        fill={r.drift > threshold ? "#ff4d4d" : r.drift < -threshold ? "#4dff4d" : "#8a9bb5"}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </>
        )}
      </div>

      {/* ── Quant Contribution Planner ──────────────────────────────── */}
      {contribution > 0 && (
        <div className="bbg-card">
          <div className="flex items-center justify-between mb-3">
            <p className="bbg-header mb-0">
              Contribution Planner — Quant Engine
            </p>
            <button
              onClick={() =>
                quantMutation.mutate({ available_cash: contribution, profile, time_horizon: horizon })
              }
              disabled={quantMutation.isPending}
              className="bg-bloomberg-gold text-bloomberg-bg text-[10px] font-bold px-5 py-1.5 hover:opacity-90 disabled:opacity-50 uppercase tracking-wider"
            >
              {quantMutation.isPending ? "OPTIMIZING…" : "RUN OPTIMIZATION"}
            </button>
          </div>

          {/* Time horizon selector */}
          <div className="flex items-center gap-3 mb-3">
            <span className="text-bloomberg-muted text-[10px] uppercase tracking-wider">Time Horizon</span>
            <div className="flex gap-1">
              {(["short", "medium", "long"] as const).map((h) => (
                <button
                  key={h}
                  onClick={() => handleSetHorizon(h)}
                  className={`px-2 py-0.5 text-[10px] uppercase tracking-wider border transition-colors ${
                    horizon === h
                      ? "border-bloomberg-gold text-bloomberg-gold bg-bloomberg-gold/10"
                      : "border-bloomberg-border text-bloomberg-muted hover:border-bloomberg-muted"
                  }`}
                >
                  {h === "short" ? "< 3yr" : h === "medium" ? "3–10yr" : "> 10yr"}
                </button>
              ))}
            </div>
            <span className="text-bloomberg-muted text-[10px]">
              {horizon === "short"
                ? "high λ, strict CVaR, XGB-weighted"
                : horizon === "medium"
                ? "balanced λ, moderate CVaR"
                : "low λ, relaxed CVaR, FF5-weighted"}
            </span>
          </div>

          <p className="text-bloomberg-muted text-[10px] mb-3">
            Deploy{" "}
            <span className="text-bloomberg-gold font-bold">
              {fmtCurrency(contribution, ccy)}
            </span>{" "}
            using CVaR-constrained optimization with Ledoit-Wolf covariance,
            HMM 4-state regime detection, GARCH covariance, Fama-French 5-factor returns, and XGBoost Black-Litterman views.
          </p>

          {quantMutation.isPending && (
            <div className="flex items-center gap-2 text-bloomberg-muted text-xs py-4">
              <span className="animate-pulse">Running ML pipeline + robust optimization…</span>
            </div>
          )}

          {quantError && (
            <div className="text-red-400 text-xs py-2 border border-red-900/40 px-3">
              {quantError}
            </div>
          )}

          {quantData && (
            <div className="space-y-4">
              {/* Regime + metrics badge */}
              <QuantResultBadge
                regime={quantData.regime}
                regimeConfidence={quantData.regime_confidence}
                regimeProbs={quantData.regime_probs}
                expectedReturn={quantData.quant_result.expected_return}
                expectedSharpe={quantData.quant_result.expected_sharpe}
                cvar95={quantData.quant_result.cvar_95}
                optimizationTimestamp={quantData.optimization_timestamp}
                mlDiagnostics={quantData.ml_diagnostics}
              />

              {/* Correlation alerts */}
              {quantData.correlation_alerts.length > 0 && (
                <CorrelationAlerts alerts={quantData.correlation_alerts} />
              )}

              {/* Slippage allocation table */}
              {quantData.contribution_plan.allocations.length === 0 ? (
                <p className="text-bloomberg-muted text-xs">
                  Portfolio is already at target — no buys needed.
                </p>
              ) : (
                <>
                  <SlippageBreakdown
                    allocations={quantData.contribution_plan.allocations}
                    slippageBreakdown={quantData.slippage_breakdown}
                    currency={ccy}
                  />
                  <div className="flex flex-wrap gap-4 text-[10px] pt-1">
                    <div>
                      <span className="text-bloomberg-muted">Total cash: </span>
                      <span className="font-semibold text-bloomberg-text">
                        {fmtCurrency(quantData.contribution_plan.total_cash, ccy)}
                      </span>
                    </div>
                    <div>
                      <span className="text-bloomberg-muted">Total slippage: </span>
                      <span className="font-semibold text-red-400">
                        -{fmtCurrency(quantData.contribution_plan.total_slippage, ccy)}
                      </span>
                    </div>
                    <div>
                      <span className="text-bloomberg-muted">Net invested: </span>
                      <span className="font-bold text-green-400">
                        {fmtCurrency(quantData.contribution_plan.net_invested, ccy)}
                      </span>
                    </div>
                  </div>
                </>
              )}

              {/* ── Quant Analytics V2 Panels ── */}
              {quantData.quant_analytics_v2 && (() => {
                const qa = quantData.quant_analytics_v2!;
                const pct = (v: number | null | undefined, d = 1) =>
                  v == null ? "—" : `${(v * 100).toFixed(d)}%`;

                return (
                  <>
                    {/* Panel 1: Execution Plan */}
                    {qa.rebalancing_bands && qa.rebalancing_bands.trades.length > 0 && (
                      <div className="bbg-card">
                        <p className="bbg-header">Execution Plan (Band Rebalancing)</p>
                        <div className="flex flex-wrap gap-4 text-[10px] mb-2">
                          <span className="text-bloomberg-muted">
                            Turnover: <span className="text-bloomberg-gold font-bold">{pct(qa.rebalancing_bands.turnover)}</span>
                          </span>
                          <span className="text-bloomberg-muted">
                            Executable trades: <span className="text-bloomberg-text font-bold">{qa.rebalancing_bands.n_executable}</span>
                          </span>
                          {qa.rebalancing_bands.suppressed.length > 0 && (
                            <span className="text-bloomberg-muted">
                              Suppressed: <span className="text-bloomberg-muted">{qa.rebalancing_bands.suppressed.join(", ")}</span>
                            </span>
                          )}
                        </div>
                        <table className="bbg-table text-[10px]">
                          <thead>
                            <tr>
                              <th>Ticker</th>
                              <th className="text-right">Current%</th>
                              <th className="text-right">Target%</th>
                              <th className="text-right">Drift%</th>
                              <th>Action</th>
                              <th className="text-right">Est TC</th>
                            </tr>
                          </thead>
                          <tbody>
                            {qa.rebalancing_bands.trades.map((t) => (
                              <tr key={t.ticker}>
                                <td className="text-bloomberg-gold font-medium">{t.ticker}</td>
                                <td className="text-right">{t.current_w_pct.toFixed(1)}%</td>
                                <td className="text-right">{t.target_w_pct.toFixed(1)}%</td>
                                <td className={`text-right font-medium ${t.drift_w_pct > 0 ? "text-red-400" : t.drift_w_pct < 0 ? "text-green-400" : "text-bloomberg-muted"}`}>
                                  {t.drift_w_pct > 0 ? "+" : ""}{t.drift_w_pct.toFixed(2)}%
                                </td>
                                <td className={t.action === "BUY" ? "text-green-400" : t.action === "SELL" ? "text-red-400" : "text-bloomberg-muted"}>
                                  {t.action}
                                </td>
                                <td className="text-right text-bloomberg-muted">{fmtCurrency(t.est_tc)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Panel 2: Net Alpha After Costs */}
                    {qa.net_alpha && qa.net_alpha.length > 0 && (
                      <div className="bbg-card">
                        <p className="bbg-header">Net Alpha After Transaction Costs</p>
                        <p className="text-bloomberg-muted text-[10px] mb-2">
                          Trades are suppressed when net alpha after costs is below the minimum edge threshold.
                        </p>
                        <table className="bbg-table text-[10px]">
                          <thead>
                            <tr>
                              <th>Ticker</th>
                              <th className="text-right">Exp. Return</th>
                              <th className="text-right">TC Drag</th>
                              <th className="text-right">Net Alpha</th>
                              <th>Trade?</th>
                            </tr>
                          </thead>
                          <tbody>
                            {qa.net_alpha.map((row) => (
                              <tr key={row.ticker}>
                                <td className="text-bloomberg-gold font-medium">{row.ticker}</td>
                                <td className="text-right">{pct(row.expected_return)}</td>
                                <td className="text-right text-red-400">-{pct(row.ann_tc_drag, 3)}</td>
                                <td className={`text-right font-bold ${row.net_alpha >= 0 ? "text-green-400" : "text-red-400"}`}>
                                  {pct(row.net_alpha)}
                                </td>
                                <td className={row.has_edge ? "text-green-400" : "text-bloomberg-muted"}>
                                  {row.has_edge ? "YES" : "NO"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Panel 3: Liquidity Analysis */}
                    {qa.liquidity && qa.liquidity.length > 0 && (
                      <div className="bbg-card">
                        <p className="bbg-header">Liquidity Analysis (30-day ADV)</p>
                        <table className="bbg-table text-[10px]">
                          <thead>
                            <tr>
                              <th>Ticker</th>
                              <th className="text-right">Score</th>
                              <th className="text-right">Days to Liquidate</th>
                              <th className="text-right">ADV 30d</th>
                              <th>Flag</th>
                            </tr>
                          </thead>
                          <tbody>
                            {qa.liquidity.map((row) => (
                              <tr key={row.ticker}>
                                <td className="text-bloomberg-gold font-medium">{row.ticker}</td>
                                <td className={`text-right font-medium ${row.liquidity_score >= 0.8 ? "text-green-400" : row.liquidity_score >= 0.5 ? "text-bloomberg-gold" : "text-red-400"}`}>
                                  {row.liquidity_score.toFixed(2)}
                                </td>
                                <td className="text-right">
                                  {row.days_to_liquidate != null ? row.days_to_liquidate.toFixed(1) : "∞"}
                                </td>
                                <td className="text-right text-bloomberg-muted">
                                  {row.adv_30d > 0 ? fmtCurrency(row.adv_30d) : "—"}
                                </td>
                                <td className={row.flag === "OK" ? "text-green-400" : "text-bloomberg-gold"}>
                                  {row.flag}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Panel 4: Expected Return Bands */}
                    {qa.return_bands && qa.return_bands.length > 0 && (
                      <div className="bbg-card">
                        <p className="bbg-header">Expected Return Bands (Bootstrap 90% CI)</p>
                        <table className="bbg-table text-[10px]">
                          <thead>
                            <tr>
                              <th>Ticker</th>
                              <th className="text-right">Low</th>
                              <th className="text-right">Median</th>
                              <th className="text-right">High</th>
                              <th className="text-right">Sharpe (median)</th>
                              <th>Reliable</th>
                            </tr>
                          </thead>
                          <tbody>
                            {qa.return_bands.map((row) => (
                              <tr key={row.ticker}>
                                <td className="text-bloomberg-gold font-medium">{row.ticker}</td>
                                <td className="text-right text-bloomberg-muted">{pct(row.return_low)}</td>
                                <td className={`text-right font-medium ${row.return_median >= 0 ? "text-green-400" : "text-red-400"}`}>
                                  {pct(row.return_median)}
                                </td>
                                <td className="text-right text-bloomberg-muted">{pct(row.return_high)}</td>
                                <td className={`text-right ${row.sharpe_median >= 1 ? "text-green-400" : row.sharpe_median >= 0 ? "text-bloomberg-gold" : "text-red-400"}`}>
                                  {row.sharpe_median.toFixed(2)}
                                </td>
                                <td className={row.reliable ? "text-green-400" : "text-bloomberg-muted"}>
                                  {row.reliable ? "YES" : "LOW CI"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Panel 5: Walk-Forward Validation */}
                    {qa.walk_forward && qa.walk_forward.folds && qa.walk_forward.folds.length > 0 && (
                      <div className="bbg-card">
                        <p className="bbg-header">Walk-Forward Validation (Out-of-Sample)</p>
                        <div className="flex flex-wrap gap-4 text-[10px] mb-2">
                          <span className="text-bloomberg-muted">
                            OOS Sharpe: <span className={`font-bold ${qa.walk_forward.oos_mean_sharpe >= 0.5 ? "text-green-400" : "text-bloomberg-gold"}`}>
                              {qa.walk_forward.oos_mean_sharpe.toFixed(3)}
                            </span>
                          </span>
                          <span className="text-bloomberg-muted">
                            ±{qa.walk_forward.oos_sharpe_std.toFixed(3)}
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

                    {/* Panel 6: Dynamic Weight Caps */}
                    {qa.dynamic_caps && Object.keys(qa.dynamic_caps.caps).length > 0 && (
                      <div className="bbg-card">
                        <p className="bbg-header">Dynamic Weight Caps</p>
                        <p className="text-bloomberg-muted text-[10px] mb-2">
                          Adaptive per-asset caps based on pairwise correlation and concentration.
                          Top-heavy: <span className="text-bloomberg-gold">{qa.dynamic_caps.top_heavy_tickers.join(", ") || "—"}</span>
                        </p>
                        <table className="bbg-table text-[10px]">
                          <thead>
                            <tr>
                              <th>Ticker</th>
                              <th className="text-right">Suggested Cap</th>
                              <th className="text-right">Avg Pairwise Corr</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(qa.dynamic_caps.caps)
                              .sort(([, a], [, b]) => b - a)
                              .map(([ticker, cap]) => (
                                <tr key={ticker}>
                                  <td className="text-bloomberg-gold font-medium">{ticker}</td>
                                  <td className="text-right text-bloomberg-text">{(cap * 100).toFixed(1)}%</td>
                                  <td className="text-right text-bloomberg-muted">
                                    {(qa.dynamic_caps!.mean_pairwise_corr[ticker] ?? 0).toFixed(2)}
                                  </td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Panel 7: Expected Drawdown Profile */}
                    {qa.drawdown_profile && Object.keys(qa.drawdown_profile).length > 0 && (
                      <div className="bbg-card">
                        <p className="bbg-header">Expected Drawdown Profile (Monte Carlo)</p>
                        <table className="bbg-table text-[10px]">
                          <thead>
                            <tr>
                              <th>Horizon</th>
                              <th className="text-right">Expected Max DD</th>
                              <th className="text-right">Worst (p95)</th>
                              <th className="text-right">Median Recovery</th>
                              <th className="text-right">P(DD &gt; 20%)</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(qa.drawdown_profile).map(([yr, h]) => (
                              <tr key={yr}>
                                <td className="text-bloomberg-gold font-medium">{yr}Y</td>
                                <td className="text-right text-red-400">{pct(h.expected_max_dd)}</td>
                                <td className="text-right text-red-400">{pct(h.worst_dd_p95)}</td>
                                <td className="text-right text-bloomberg-muted">{h.median_recovery_months.toFixed(0)} mo</td>
                                <td className="text-right text-bloomberg-muted">{(h.prob_drawdown_gt_20pct * 100).toFixed(0)}%</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Panel 8: Model Drift Monitor */}
                    {qa.model_drift && qa.model_drift.per_asset && Object.keys(qa.model_drift.per_asset).length > 0 && (
                      <div className="bbg-card">
                        <p className="bbg-header">Model Parameter Drift Monitor</p>
                        <div className="flex flex-wrap gap-4 text-[10px] mb-2">
                          <span className="text-bloomberg-muted">
                            Engine: <span className={qa.model_drift.engine_healthy ? "text-green-400 font-bold" : "text-red-400 font-bold"}>
                              {qa.model_drift.engine_healthy ? "STABLE" : "DRIFTING"}
                            </span>
                          </span>
                          <span className="text-bloomberg-muted">
                            Mean drift: <span className="text-bloomberg-text">{qa.model_drift.mean_drift_score.toFixed(3)}</span>
                          </span>
                          {qa.model_drift.n_alerts > 0 && (
                            <span className="text-red-400 font-bold">{qa.model_drift.n_alerts} alert(s)</span>
                          )}
                        </div>
                        <table className="bbg-table text-[10px]">
                          <thead>
                            <tr>
                              <th>Ticker</th>
                              <th className="text-right">Sharpe (3mo)</th>
                              <th className="text-right">Sharpe (12mo)</th>
                              <th className="text-right">Drift Score</th>
                              <th>Alert</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(qa.model_drift.per_asset)
                              .sort(([, a], [, b]) => b.drift_score - a.drift_score)
                              .map(([ticker, d]) => (
                                <tr key={ticker}>
                                  <td className="text-bloomberg-gold font-medium">{ticker}</td>
                                  <td className={`text-right ${d.sharpe_short >= 0 ? "text-green-400" : "text-red-400"}`}>
                                    {d.sharpe_short.toFixed(2)}
                                  </td>
                                  <td className={`text-right ${d.sharpe_long >= 0 ? "text-green-400" : "text-red-400"}`}>
                                    {d.sharpe_long.toFixed(2)}
                                  </td>
                                  <td className={`text-right font-medium ${d.drift_score > 0.5 ? "text-red-400" : d.drift_score > 0.25 ? "text-bloomberg-gold" : "text-bloomberg-muted"}`}>
                                    {d.drift_score.toFixed(3)}
                                  </td>
                                  <td className={d.alert ? "text-red-400 font-bold" : "text-bloomberg-muted"}>
                                    {d.alert ? "⚠" : "OK"}
                                  </td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Panel 9: Naive Portfolio Benchmarks */}
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
                                <td className="text-right text-red-400">{pct(row.max_dd)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                );
              })()}
            </div>
          )}

          {!quantData && !quantMutation.isPending && (
            <p className="text-bloomberg-muted text-[10px]">
              Press <span className="text-bloomberg-gold font-semibold">RUN OPTIMIZATION</span> to
              compute the optimal allocation with slippage breakdown.
            </p>
          )}
        </div>
      )}

      {/* Trade Suggestions */}
      <div className="bbg-card">
        <div className="flex items-center justify-between mb-0">
          <p className="bbg-header mb-0">Trade Suggestions</p>
          <button
            onClick={() => openWith("I have $250 to deploy. Given the current drift of each position and the Motor 1 constraints, give me the exact USD amount for each ETF.")}
            className="flex items-center gap-1.5 text-[10px] text-[#f3a712] border border-[#f3a712]/40 px-2.5 py-1 rounded-lg hover:bg-[#f3a712]/10 transition-colors"
          >
            🤖 How much to buy this month?
          </button>
        </div>
        {isLoading ? (
          <div className="text-bloomberg-muted text-xs py-4">Loading…</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="bbg-table">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Name</th>
                  <th className="text-right">Trade {ccy}</th>
                  <th>Direction</th>
                  <th className="text-right">Est. TC</th>
                </tr>
              </thead>
              <tbody>
                {(data ?? []).filter((r) => r.trade_direction !== "HOLD").map((r) => (
                  <tr key={r.ticker}>
                    <td className="text-bloomberg-gold font-medium">{r.ticker}</td>
                    <td className="text-bloomberg-muted">{r.name}</td>
                    <td className="text-right">{fmtCurrency(Math.abs(r.trade_value), ccy)}</td>
                    <td className={r.trade_direction === "BUY" ? "text-green-400" : "text-red-400"}>
                      {r.trade_direction}
                    </td>
                    <td className="text-right text-bloomberg-muted">{fmtCurrency(r.estimated_tc, ccy)}</td>
                  </tr>
                ))}
                {(data ?? []).filter((r) => r.trade_direction === "HOLD").length > 0 && (
                  <tr>
                    <td colSpan={5} className="text-bloomberg-muted text-[10px] pt-2">
                      {data!.filter((r) => r.trade_direction === "HOLD").map((r) => r.ticker).join(", ")} — HOLD (within threshold)
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Required Contribution — Profile-aware */}
      <div className="bbg-card">
        <p className="bbg-header" style={{ color: "#f3a712" }}>
          Required Contribution to Reach{" "}
          {profile === "aggressive" ? "Max Return" : profile === "conservative" ? "Max Sharpe" : "Target Return"}{" "}
          (No Selling)
        </p>
        <p className="text-bloomberg-muted text-[10px] mb-3">
          Minimum cash needed to reach the {PROFILE_LABELS[profile]?.label ?? profile} profile optimal weights without selling any existing positions.
        </p>

        <div className="flex flex-wrap gap-4 items-end mb-3">
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">History Period</label>
            <select
              value={msPeriod}
              onChange={(e) => setMsPeriod(e.target.value)}
              className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs"
            >
              {["1y", "2y", "3y", "5y", "10y"].map((p) => <option key={p}>{p}</option>)}
            </select>
          </div>
          <button
            onClick={() => refetchMs()}
            disabled={msLoading}
            className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-6 py-1.5 hover:opacity-90 disabled:opacity-50"
          >
            {msLoading ? "COMPUTING…" : "COMPUTE"}
          </button>
        </div>

        {msData && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <div className="bbg-card">
                <p className="text-bloomberg-muted text-[10px]">Required Contribution</p>
                <p className="text-bloomberg-gold text-sm font-bold">{fmtCurrency(msData.required_contribution, ccy)}</p>
              </div>
              <div className="bbg-card">
                <p className="text-bloomberg-muted text-[10px]">Current Portfolio</p>
                <p className="text-bloomberg-text text-sm font-bold">{fmtCurrency(msData.total_value, ccy)}</p>
              </div>
              <div className="bbg-card">
                <p className="text-bloomberg-muted text-[10px]">Portfolio After</p>
                <p className="text-bloomberg-text text-sm font-bold">{fmtCurrency(msData.total_after, ccy)}</p>
              </div>
              <div className="bbg-card">
                <p className="text-bloomberg-muted text-[10px]">Assets in Plan</p>
                <p className="text-bloomberg-text text-sm font-bold">
                  {Object.values(msData.buy_plan).filter((x: { buy_value: number }) => x.buy_value > 0).length}
                </p>
              </div>
            </div>
            {msData.profile_metrics && Object.keys(msData.profile_metrics).length > 0 && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">Target Ann. Return</p>
                  <p className="text-green-400 text-sm font-bold">{msData.profile_metrics.ann_return?.toFixed(1)}%</p>
                </div>
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">Target Volatility</p>
                  <p className="text-bloomberg-text text-sm font-bold">{msData.profile_metrics.ann_vol?.toFixed(1)}%</p>
                </div>
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">Target Sharpe</p>
                  <p className="text-bloomberg-gold text-sm font-bold">{msData.profile_metrics.sharpe?.toFixed(3)}</p>
                </div>
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">Target Max DD</p>
                  <p className="text-red-400 text-sm font-bold">{msData.profile_metrics.max_drawdown?.toFixed(1)}%</p>
                </div>
              </div>
            )}

            <table className="bbg-table">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th className="text-right">Current Weight</th>
                  <th className="text-right">Target Weight</th>
                  <th className="text-right">Buy Amount</th>
                  <th className="text-right">% of Contribution</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(msData.buy_plan)
                  .sort(([, a], [, b]) => b.buy_value - a.buy_value)
                  .map(([ticker, plan]) => (
                    <tr key={ticker}>
                      <td className="text-bloomberg-gold font-medium">{ticker}</td>
                      <td className="text-right">{fmtPct(plan.current_weight)}</td>
                      <td className="text-right">{fmtPct(plan.target_weight)}</td>
                      <td className={`text-right font-medium ${plan.buy_value > 0 ? "text-green-400" : "text-bloomberg-muted"}`}>
                        {plan.buy_value > 0 ? fmtCurrency(plan.buy_value, ccy) : "—"}
                      </td>
                      <td className="text-right text-bloomberg-muted">
                        {plan.buy_pct > 0 ? fmtPct(plan.buy_pct) : "—"}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
}
