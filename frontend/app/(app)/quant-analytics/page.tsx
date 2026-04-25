"use client";
import { useState, useCallback } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { fetchQuantAdvanced } from "@/lib/api/analytics";
import { fmtCurrency } from "@/lib/formatters";
import type { BLExplanationRow, QuantAnalyticsV2 } from "@/lib/api/contribution";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Legend,
} from "recharts";

const OptimizationPage = dynamic(
  () => import("@/app/(app)/optimization/page"),
  { ssr: false, loading: () => <div className="h-40 bg-bloomberg-border/30 animate-pulse rounded" /> }
);

const pct = (v: number | null | undefined, d = 1) =>
  v == null ? "—" : `${(v * 100).toFixed(d)}%`;

// ── Executive Health Score ────────────────────────────────────────────────────
type ModuleStatus = { label: string; status: "pass" | "warn" | "fail" | "na"; detail: string };

function computeHealthScore(qa: QuantAnalyticsV2): { score: number; modules: ModuleStatus[]; signals: string[] } {
  const modules: ModuleStatus[] = [];
  const signals: string[] = [];

  // 1. Band Rebalancing
  if (qa.rebalancing_bands) {
    const urgent = qa.rebalancing_bands.trades.filter((t) => Math.abs(t.drift_w_pct) > 5).length;
    const s = urgent === 0 ? "pass" : urgent <= 2 ? "warn" : "fail";
    modules.push({ label: "Rebalancing", status: s, detail: `${qa.rebalancing_bands.trades.length} trades, turnover ${pct(qa.rebalancing_bands.turnover)}` });
    if (urgent > 0) signals.push(`${urgent} position(s) with drift >5% — rebalancing recommended.`);
  } else modules.push({ label: "Rebalancing", status: "na", detail: "No data" });

  // 2. Net Alpha
  if (qa.net_alpha) {
    const noEdge = qa.net_alpha.filter((r) => !r.has_edge).length;
    const s = noEdge === 0 ? "pass" : noEdge <= qa.net_alpha.length / 2 ? "warn" : "fail";
    modules.push({ label: "Net Alpha", status: s, detail: `${qa.net_alpha.length - noEdge}/${qa.net_alpha.length} positions with net edge` });
    if (noEdge > 0) signals.push(`${noEdge} position(s) have negative net alpha after transaction costs.`);
  } else modules.push({ label: "Net Alpha", status: "na", detail: "No data" });

  // 3. Tax Drag
  if (qa.after_tax_drag) {
    const drag = qa.after_tax_drag.tax_drag;
    const s = drag < 0.01 ? "pass" : drag < 0.03 ? "warn" : "fail";
    modules.push({ label: "Tax Drag", status: s, detail: `Drag: ${pct(drag)} · Liability: ${fmtCurrency(qa.after_tax_drag.total_tax_liability)}` });
    if (drag >= 0.02) signals.push(`Tax drag of ${pct(drag)} — consider tax-loss harvesting.`);
  } else modules.push({ label: "Tax Drag", status: "na", detail: "No data" });

  // 4. Liquidity
  if (qa.liquidity) {
    const flagged = qa.liquidity.filter((r) => r.flag !== "OK").length;
    const s = flagged === 0 ? "pass" : flagged === 1 ? "warn" : "fail";
    modules.push({ label: "Liquidity", status: s, detail: `${flagged} position(s) flagged` });
    if (flagged > 0) signals.push(`${flagged} position(s) have liquidity constraints — review before large trades.`);
  } else modules.push({ label: "Liquidity", status: "na", detail: "No data" });

  // 5. Model Agreement
  if (qa.model_agreement) {
    const score = qa.model_agreement.agreement_score;
    const s = score >= 0.7 ? "pass" : score >= 0.4 ? "warn" : "fail";
    modules.push({ label: "Model Agreement", status: s, detail: `Score: ${score.toFixed(2)} across ${qa.model_agreement.n_models} models` });
    if (score < 0.5) signals.push(`Low model agreement (${score.toFixed(2)}) — high uncertainty in optimal allocation.`);
  } else modules.push({ label: "Model Agmt", status: "na", detail: "No data" });

  // 6. Return Bands
  if (qa.return_bands) {
    const wide = qa.return_bands.filter((r) => !r.reliable).length;
    const s = wide === 0 ? "pass" : wide <= 2 ? "warn" : "fail";
    modules.push({ label: "Return Bands", status: s, detail: `${qa.return_bands.length - wide}/${qa.return_bands.length} reliable estimates` });
  } else modules.push({ label: "Return Bands", status: "na", detail: "No data" });

  // 7. BL Explanation
  const blHasViews = qa.bl_explanation && qa.bl_explanation.some((r) => r.has_view);
  modules.push({ label: "BL Views", status: blHasViews ? "pass" : "warn", detail: blHasViews ? "Views active" : "No views configured" });

  // 8. TE Budget
  if (qa.tracking_error_budget) {
    const within = qa.tracking_error_budget.within_budget;
    modules.push({ label: "TE Budget", status: within ? "pass" : "fail", detail: `${qa.tracking_error_budget.budget_used_pct.toFixed(1)}% of budget used` });
    if (!within) signals.push(`Tracking error exceeds budget (${qa.tracking_error_budget.budget_used_pct.toFixed(0)}% used).`);
  } else modules.push({ label: "TE Budget", status: "na", detail: "No data" });

  // 9. Walk-Forward
  if (qa.walk_forward) {
    const edge = qa.walk_forward.consistent_edge;
    const sharpe = qa.walk_forward.oos_mean_sharpe;
    const s = edge && sharpe >= 0.5 ? "pass" : !edge ? "fail" : "warn";
    modules.push({ label: "Walk-Forward", status: s, detail: `OOS Sharpe: ${sharpe.toFixed(2)} · Edge: ${edge ? "YES" : "NO"}` });
    if (!edge) signals.push(`No consistent out-of-sample edge detected — strategy may be overfitted.`);
  } else modules.push({ label: "Walk-Forward", status: "na", detail: "No data" });

  // 10. Regime
  if (qa.regime) {
    const reg = qa.regime.current_regime;
    const s = reg === "low" || reg === "normal" ? "pass" : reg === "high" ? "warn" : "fail";
    modules.push({ label: "Regime", status: s, detail: `${reg?.toUpperCase()} vol · ${(qa.regime.regime_confidence * 100).toFixed(0)}% confidence` });
    if (reg === "crisis") signals.push("Portfolio in CRISIS regime — execution hold recommended.");
    if (qa.regime.recent_flip) signals.push("Recent regime flip detected — increase monitoring frequency.");
  } else modules.push({ label: "Regime", status: "na", detail: "No data" });

  // 11. Dynamic Caps
  if (qa.dynamic_caps) {
    const topHeavy = qa.dynamic_caps.top_heavy_tickers.length;
    const s = topHeavy === 0 ? "pass" : topHeavy === 1 ? "warn" : "fail";
    modules.push({ label: "Dynamic Caps", status: s, detail: `${topHeavy} top-heavy ticker(s), concentration ${(qa.dynamic_caps.top_n_concentration * 100).toFixed(1)}%` });
    if (topHeavy > 0) signals.push(`Concentration risk: ${qa.dynamic_caps.top_heavy_tickers.join(", ")} exceed dynamic weight caps.`);
  } else modules.push({ label: "Dyn. Caps", status: "na", detail: "No data" });

  // 12. Drawdown Profile
  if (qa.drawdown_profile) {
    const horizons = Object.values(qa.drawdown_profile);
    const worst = Math.max(...horizons.map((h) => h.prob_drawdown_gt_20pct));
    const s = worst < 0.25 ? "pass" : worst < 0.5 ? "warn" : "fail";
    modules.push({ label: "Drawdown", status: s, detail: `Max P(DD>20%): ${(worst * 100).toFixed(0)}%` });
    if (worst >= 0.4) signals.push(`High probability of >20% drawdown in some horizon — review risk tolerance.`);
  } else modules.push({ label: "Drawdown", status: "na", detail: "No data" });

  // 13. Model Drift
  if (qa.model_drift) {
    const s = qa.model_drift.engine_healthy ? "pass" : "fail";
    modules.push({ label: "Model Drift", status: s, detail: qa.model_drift.engine_healthy ? "Engine stable" : `${qa.model_drift.n_alerts} alert(s)` });
    if (!qa.model_drift.engine_healthy) signals.push(`Model drift detected in ${qa.model_drift.n_alerts} asset(s) — parameters may be stale.`);
  } else modules.push({ label: "Model Drift", status: "na", detail: "No data" });

  // 14. Naive Benchmarks
  if (qa.naive_benchmarks) {
    const portfolio = qa.naive_benchmarks.find((r) => r.model === "Your Portfolio");
    const others = qa.naive_benchmarks.filter((r) => r.model !== "Your Portfolio");
    const beating = others.filter((r) => (portfolio?.sharpe ?? 0) > r.sharpe).length;
    const s = beating >= others.length * 0.6 ? "pass" : beating >= others.length * 0.3 ? "warn" : "fail";
    modules.push({ label: "vs Naive", status: s, detail: `Beats ${beating}/${others.length} naive benchmarks by Sharpe` });
    if (beating < others.length * 0.3) signals.push("Portfolio underperforms most naive benchmarks — consider simplifying allocation.");
  } else modules.push({ label: "vs Naive", status: "na", detail: "No data" });

  // 15. Factor Risk
  if (qa.factor_risk) {
    const topContrib = Math.max(...Object.values(qa.factor_risk.per_asset).map((a) => a.vol_contribution_pct));
    const s = topContrib < 25 ? "pass" : topContrib < 40 ? "warn" : "fail";
    modules.push({ label: "Factor Risk", status: s, detail: `Max single-asset vol contribution: ${topContrib.toFixed(1)}%` });
    if (topContrib >= 35) signals.push(`Single asset drives ${topContrib.toFixed(0)}% of portfolio volatility — concentration risk.`);
  } else modules.push({ label: "Factor Risk", status: "na", detail: "No data" });

  const scored = modules.filter((m) => m.status !== "na");
  const passScore = scored.filter((m) => m.status === "pass").length;
  const warnScore = scored.filter((m) => m.status === "warn").length * 0.5;
  const score = scored.length > 0 ? Math.round(((passScore + warnScore) / scored.length) * 100) : 0;

  return { score, modules, signals };
}

function StatusBadge({ status }: { status: ModuleStatus["status"] }) {
  const cls = {
    pass: "bg-green-900/40 text-green-400 border-green-800",
    warn: "bg-yellow-900/30 text-yellow-400 border-yellow-800",
    fail: "bg-red-900/30 text-red-400 border-red-800",
    na:   "bg-bloomberg-border/20 text-bloomberg-muted border-bloomberg-border/40",
  }[status];
  const icon = { pass: "✓", warn: "⚠", fail: "✕", na: "—" }[status];
  return <span className={`text-[8px] font-bold px-1 py-0.5 border rounded ${cls}`}>{icon}</span>;
}

function ScoreRing({ score }: { score: number }) {
  const color = score >= 70 ? "#22c55e" : score >= 45 ? "#f3a712" : "#ef4444";
  const label = score >= 70 ? "HEALTHY" : score >= 45 ? "CAUTION" : "AT RISK";
  return (
    <div className="flex flex-col items-center justify-center w-24 h-24 rounded-full border-4" style={{ borderColor: color }}>
      <span className="text-2xl font-bold" style={{ color }}>{score}</span>
      <span className="text-[8px] font-bold" style={{ color }}>{label}</span>
    </div>
  );
}

const MODULES = [
  "Band Rebalancing", "Net Alpha", "Tax Drag", "Liquidity", "Model Agreement",
  "Return Bands", "BL Explainability", "TE Budget", "Walk-Forward", "Regime Probs",
  "Dynamic Caps", "Drawdown Profile", "Model Drift", "Naive Benchmarks", "Factor Risk",
];

export default function QuantAnalyticsPage() {
  const [tab, setTab] = useState<"quant" | "optimization">("quant");
  const [period, setPeriod] = useState("2y");
  const [triggered, setTriggered] = useState(false);

  const { data: qa, isFetching, isError, error, refetch } = useQuery({
    queryKey: ["quant-advanced-full", period],
    queryFn: () =>
      fetchQuantAdvanced({ period, benchmark_ticker: "VOO", n_bootstrap: 500, n_dd_sims: 1000 }),
    enabled: triggered,
    staleTime: 10 * 60 * 1000,
    retry: false,
  });

  const handleRun = useCallback(() => {
    if (!triggered) {
      setTriggered(true);
    } else {
      refetch();
    }
  }, [triggered, refetch]);

  return (
    <div className="space-y-4">
      {/* Header + tabs */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Quant & Optimization</h1>
          <p className="text-bloomberg-muted text-[10px] mt-0.5">
            15-module engine · efficient frontier · Black-Litterman · rebalancing
          </p>
        </div>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 border-b border-bloomberg-border">
        {([["quant", "⚗ Quant Engine (15 modules)"], ["optimization", "◎ Optimization"]] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`text-[10px] px-4 py-2 font-semibold transition-colors border-b-2 -mb-px ${
              tab === key
                ? "border-bloomberg-gold text-bloomberg-gold"
                : "border-transparent text-bloomberg-muted hover:text-bloomberg-text"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── OPTIMIZATION TAB ── */}
      {tab === "optimization" && <OptimizationPage />}

      {/* ── QUANT ENGINE TAB ── */}
      {tab === "quant" && <>
      <div className="flex items-center justify-between">
        <p className="text-bloomberg-muted text-[10px]">15 modules — execution · return attribution · risk · validation</p>
        <div className="flex items-center gap-2">
          <select
            value={period}
            onChange={(e) => { setPeriod(e.target.value); setTriggered(false); }}
            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs"
          >
            {["1y", "2y", "3y", "5y"].map((p) => <option key={p}>{p}</option>)}
          </select>
          <button
            onClick={handleRun}
            disabled={isFetching}
            className="bg-bloomberg-gold text-bloomberg-bg text-[10px] font-bold px-5 py-1.5 hover:opacity-90 disabled:opacity-50 uppercase tracking-wider"
          >
            {isFetching ? "COMPUTING…" : triggered ? "RE-RUN" : "RUN ALL 15 MODULES"}
          </button>
        </div>
      </div>

      {/* Error state */}
      {isError && (
        <div className="bbg-card border border-red-800 bg-red-900/20">
          <p className="text-red-400 text-xs font-bold mb-1">Error running quant engine</p>
          <p className="text-red-400/70 text-[10px]">{(error as any)?.message || "Backend error — check that all dependencies are installed."}</p>
        </div>
      )}

      {/* Idle state — module list */}
      {!qa && !isFetching && !isError && (
        <div className="bbg-card">
          <p className="text-bloomberg-muted text-[10px] mb-3">
            Press <span className="text-bloomberg-gold font-semibold">RUN ALL 15 MODULES</span> to execute the full quant analytics pipeline against your live portfolio.
          </p>
          <div className="grid grid-cols-3 md:grid-cols-5 gap-1.5">
            {MODULES.map((m, i) => (
              <div key={m} className="text-bloomberg-muted border border-bloomberg-border/50 px-2 py-1 text-[10px] text-center">
                <span className="text-bloomberg-gold text-[9px] mr-1">{i + 1}.</span>{m}
              </div>
            ))}
          </div>
        </div>
      )}

      {isFetching && (
        <div className="bbg-card py-6">
          <p className="text-bloomberg-muted text-xs animate-pulse text-center">
            Running 15 analytics modules — Ledoit-Wolf · Bootstrap · MC · Walk-Forward…
          </p>
        </div>
      )}

      {qa && (() => {
        const { score, modules, signals } = computeHealthScore(qa);
        return (
        <>
          {/* ── Executive Intelligence Summary ── */}
          <div className="bbg-card">
            <p className="bbg-header">Portfolio Intelligence Summary</p>
            <div className="flex flex-col md:flex-row gap-6 items-start">
              {/* Score ring */}
              <div className="flex flex-col items-center gap-2 shrink-0">
                <ScoreRing score={score} />
                <p className="text-bloomberg-muted text-[9px] text-center">Health Score<br />(15 modules)</p>
              </div>

              {/* Module grid */}
              <div className="flex-1">
                <div className="grid grid-cols-3 sm:grid-cols-5 gap-1.5 mb-3">
                  {modules.map((m) => (
                    <div key={m.label} className="border border-bloomberg-border/50 p-1.5 text-center" title={m.detail}>
                      <div className="flex items-center justify-center gap-1 mb-0.5">
                        <StatusBadge status={m.status} />
                      </div>
                      <p className="text-bloomberg-muted text-[8px] leading-tight">{m.label}</p>
                    </div>
                  ))}
                </div>

                {/* Key signals */}
                {signals.length > 0 && (
                  <div className="space-y-1">
                    <p className="text-bloomberg-muted text-[9px] uppercase tracking-widest">Key Signals</p>
                    {signals.map((s, i) => (
                      <div key={i} className="flex items-start gap-2 text-[10px]">
                        <span className="text-bloomberg-gold shrink-0 mt-0.5">›</span>
                        <span className="text-bloomberg-text">{s}</span>
                      </div>
                    ))}
                  </div>
                )}
                {signals.length === 0 && (
                  <div className="text-green-400 text-[10px] flex items-center gap-1.5">
                    <span>✓</span> All modules clear — portfolio within normal parameters.
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* ── 1. Band Rebalancing ── */}
          {qa.rebalancing_bands && qa.rebalancing_bands.trades.length > 0 && (
            <div className="bbg-card">
              <div className="flex items-center justify-between mb-2">
                <p className="bbg-header mb-0">1 · Band Rebalancing</p>
                <div className="flex gap-4 text-[10px]">
                  <span className="text-bloomberg-muted">Turnover: <span className="text-bloomberg-gold font-bold">{pct(qa.rebalancing_bands.turnover)}</span></span>
                  <span className="text-bloomberg-muted">Executable: <span className="text-bloomberg-text font-bold">{qa.rebalancing_bands.n_executable}</span></span>
                  {qa.rebalancing_bands.suppressed.length > 0 && (
                    <span className="text-bloomberg-muted">Suppressed: {qa.rebalancing_bands.suppressed.join(", ")}</span>
                  )}
                </div>
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

          {/* ── 2. Net Alpha After Costs ── */}
          {qa.net_alpha && qa.net_alpha.length > 0 && (
            <div className="bbg-card">
              <p className="bbg-header">2 · Net Alpha After Transaction Costs</p>
              <table className="bbg-table text-[10px]">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th className="text-right">Exp. Return</th>
                    <th className="text-right">TC Drag (ann.)</th>
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

          {/* ── 3. After-Tax Drag ── */}
          {qa.after_tax_drag && (
            <div className="bbg-card">
              <p className="bbg-header">3 · After-Tax Drag</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">After-Tax Return</p>
                  <p className={`text-sm font-bold ${qa.after_tax_drag.after_tax_return >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {pct(qa.after_tax_drag.after_tax_return)}
                  </p>
                </div>
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">Tax Drag</p>
                  <p className="text-red-400 text-sm font-bold">-{pct(qa.after_tax_drag.tax_drag)}</p>
                </div>
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">Total Tax Liability</p>
                  <p className="text-bloomberg-text text-sm font-bold">{fmtCurrency(qa.after_tax_drag.total_tax_liability)}</p>
                </div>
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">Open Positions</p>
                  <p className="text-bloomberg-text text-sm font-bold">{qa.after_tax_drag.positions.length}</p>
                </div>
              </div>
              {qa.after_tax_drag.positions.length > 0 && (
                <table className="bbg-table text-[10px]">
                  <thead>
                    <tr>
                      <th>Ticker</th>
                      <th className="text-right">Shares</th>
                      <th className="text-right">Cost Basis</th>
                      <th className="text-right">Gain</th>
                      <th className="text-right">Holding</th>
                      <th className="text-right">Tax</th>
                    </tr>
                  </thead>
                  <tbody>
                    {qa.after_tax_drag.positions.map((p, i) => (
                      <tr key={i}>
                        <td className="text-bloomberg-gold font-medium">{p.ticker}</td>
                        <td className="text-right">{p.shares}</td>
                        <td className="text-right text-bloomberg-muted">{fmtCurrency(p.cost_basis)}</td>
                        <td className={`text-right ${p.gain >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {fmtCurrency(p.gain)}
                        </td>
                        <td className="text-right text-bloomberg-muted">{p.holding_days}d</td>
                        <td className="text-right text-red-400">{fmtCurrency(p.tax_liability)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* ── 4. Liquidity Score ── */}
          {qa.liquidity && qa.liquidity.length > 0 && (
            <div className="bbg-card">
              <p className="bbg-header">4 · Liquidity Analysis (30-day ADV)</p>
              <table className="bbg-table text-[10px]">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th className="text-right">Score</th>
                    <th className="text-right">Days to Liquidate</th>
                    <th className="text-right">Daily Capacity</th>
                    <th className="text-right">Position Value</th>
                    <th>Flag</th>
                  </tr>
                </thead>
                <tbody>
                  {qa.liquidity.map((row) => (
                    <tr key={row.ticker}>
                      <td className="text-bloomberg-gold font-medium">{row.ticker}</td>
                      <td className={`text-right font-medium ${row.liquidity_score >= 0.8 ? "text-green-400" : row.liquidity_score >= 0.5 ? "text-bloomberg-gold" : "text-red-400"}`}>
                        {row.liquidity_score.toFixed(3)}
                      </td>
                      <td className="text-right">{row.days_to_liquidate != null ? row.days_to_liquidate.toFixed(1) : "∞"}</td>
                      <td className="text-right text-bloomberg-muted">
                        {row.daily_capacity > 0 ? fmtCurrency(row.daily_capacity) : "—"}
                      </td>
                      <td className="text-right text-bloomberg-muted">{fmtCurrency(row.position_value)}</td>
                      <td className={row.flag === "OK" ? "text-green-400" : "text-bloomberg-gold"}>{row.flag}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── 5. Model Agreement ── */}
          {qa.model_agreement && (
            <div className="bbg-card">
              <p className="bbg-header">5 · Model Agreement Score</p>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-3">
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">Agreement Score</p>
                  <p className={`text-sm font-bold ${qa.model_agreement.agreement_score >= 0.7 ? "text-green-400" : qa.model_agreement.agreement_score >= 0.4 ? "text-bloomberg-gold" : "text-red-400"}`}>
                    {qa.model_agreement.agreement_score.toFixed(3)}
                  </p>
                </div>
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">Models Compared</p>
                  <p className="text-bloomberg-text text-sm font-bold">{qa.model_agreement.n_models}</p>
                </div>
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">High-Conflict Tickers</p>
                  <p className={`text-sm font-bold ${qa.model_agreement.high_conflict_tickers.length === 0 ? "text-green-400" : "text-bloomberg-gold"}`}>
                    {qa.model_agreement.high_conflict_tickers.length === 0 ? "None" : qa.model_agreement.high_conflict_tickers.join(", ")}
                  </p>
                </div>
              </div>
              <table className="bbg-table text-[10px]">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th className="text-right">Consensus Weight</th>
                    <th className="text-right">Weight Std Dev</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(qa.model_agreement.consensus_weights)
                    .sort(([, a], [, b]) => b - a)
                    .map(([ticker, w]) => (
                      <tr key={ticker}>
                        <td className={`font-medium ${qa.model_agreement!.high_conflict_tickers.includes(ticker) ? "text-bloomberg-gold" : "text-bloomberg-text"}`}>
                          {ticker}
                        </td>
                        <td className="text-right">{(w * 100).toFixed(1)}%</td>
                        <td className="text-right text-bloomberg-muted">
                          ±{((qa.model_agreement!.weight_std_by_ticker[ticker] ?? 0) * 100).toFixed(1)}%
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── 6. Expected Return Bands ── */}
          {qa.return_bands && qa.return_bands.length > 0 && (
            <div className="bbg-card">
              <p className="bbg-header">6 · Expected Return Bands (Bootstrap 90% CI)</p>
              <table className="bbg-table text-[10px]">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th className="text-right">Low (5%)</th>
                    <th className="text-right">Median</th>
                    <th className="text-right">High (95%)</th>
                    <th className="text-right">Band Width</th>
                    <th className="text-right">Sharpe (median)</th>
                    <th>Signal</th>
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
                      <td className="text-right text-bloomberg-muted">{pct(row.band_width)}</td>
                      <td className={`text-right ${row.sharpe_median >= 1 ? "text-green-400" : row.sharpe_median >= 0 ? "text-bloomberg-gold" : "text-red-400"}`}>
                        {row.sharpe_median.toFixed(2)}
                      </td>
                      <td className={row.reliable ? "text-green-400" : "text-bloomberg-muted"}>
                        {row.reliable ? "RELIABLE" : "WIDE CI"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── 7. BL Explainability ── */}
          {qa.bl_explanation && qa.bl_explanation.length > 0 && (
            <div className="bbg-card">
              <p className="bbg-header">7 · Black-Litterman Posterior Explainability</p>
              <table className="bbg-table text-[10px]">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th className="text-right">Equilibrium</th>
                    <th className="text-right">Posterior</th>
                    <th className="text-right">View Pull</th>
                    <th>View?</th>
                    <th>Dominant</th>
                  </tr>
                </thead>
                <tbody>
                  {(qa.bl_explanation as BLExplanationRow[]).map((row) => (
                    <tr key={row.ticker}>
                      <td className="text-bloomberg-gold font-medium">{row.ticker}</td>
                      <td className="text-right text-bloomberg-muted">{pct(row.equilibrium_return)}</td>
                      <td className={`text-right ${row.posterior_return >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {pct(row.posterior_return)}
                      </td>
                      <td className={`text-right ${row.view_pull >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {row.view_pull >= 0 ? "+" : ""}{pct(row.view_pull)}
                      </td>
                      <td className={row.has_view ? "text-bloomberg-gold" : "text-bloomberg-muted"}>
                        {row.has_view ? "YES" : "—"}
                      </td>
                      <td className="text-bloomberg-muted">{row.dominant_source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {(!qa.bl_explanation || qa.bl_explanation.length === 0) && (
            <div className="bbg-card">
              <p className="bbg-header">7 · Black-Litterman Posterior Explainability</p>
              <p className="text-bloomberg-muted text-[10px]">
                No BL views configured. Add views in Optimization → Black-Litterman to see posterior decomposition.
              </p>
            </div>
          )}

          {/* ── 8. Tracking Error Budget ── */}
          {qa.tracking_error_budget && qa.tracking_error_budget.total_te != null && (
            <div className="bbg-card">
              <p className="bbg-header">8 · Tracking Error Budget</p>
              <div className="flex flex-wrap gap-4 text-[10px] mb-3">
                <span className="text-bloomberg-muted">TE actual: <span className="text-bloomberg-gold font-bold">{pct(qa.tracking_error_budget.total_te)}</span></span>
                <span className="text-bloomberg-muted">Budget: <span className="text-bloomberg-text">{pct(qa.tracking_error_budget.te_budget)}</span></span>
                <span className="text-bloomberg-muted">Used: <span className={`font-bold ${qa.tracking_error_budget.within_budget ? "text-green-400" : "text-red-400"}`}>
                  {qa.tracking_error_budget.budget_used_pct.toFixed(1)}%
                </span></span>
                <span className={`font-bold uppercase text-[10px] ${qa.tracking_error_budget.within_budget ? "text-green-400" : "text-red-400"}`}>
                  {qa.tracking_error_budget.within_budget ? "✓ Within Budget" : "⚠ Over Budget"}
                </span>
              </div>
              {Object.keys(qa.tracking_error_budget.per_asset).length > 0 && (
                <table className="bbg-table text-[10px]">
                  <thead>
                    <tr>
                      <th>Ticker</th>
                      <th className="text-right">TE Contribution</th>
                      <th className="text-right">Share of Total TE</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(qa.tracking_error_budget.per_asset)
                      .sort(([, a], [, b]) => b.te_share_pct - a.te_share_pct)
                      .map(([ticker, te]) => (
                        <tr key={ticker}>
                          <td className="text-bloomberg-gold font-medium">{ticker}</td>
                          <td className="text-right text-bloomberg-muted">{pct(te.te_contribution)}</td>
                          <td className={`text-right font-medium ${te.te_share_pct > 30 ? "text-red-400" : te.te_share_pct > 15 ? "text-bloomberg-gold" : "text-bloomberg-text"}`}>
                            {te.te_share_pct.toFixed(1)}%
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* ── 9. Walk-Forward Validation ── */}
          {qa.walk_forward && qa.walk_forward.folds && qa.walk_forward.folds.length > 0 && (
            <div className="bbg-card">
              <p className="bbg-header">9 · Walk-Forward Validation (Out-of-Sample)</p>
              <div className="flex flex-wrap gap-4 text-[10px] mb-3">
                <span className="text-bloomberg-muted">OOS Sharpe: <span className={`font-bold ${qa.walk_forward.oos_mean_sharpe >= 0.5 ? "text-green-400" : "text-bloomberg-gold"}`}>
                  {qa.walk_forward.oos_mean_sharpe.toFixed(3)} ±{qa.walk_forward.oos_sharpe_std.toFixed(3)}
                </span></span>
                <span className="text-bloomberg-muted">OOS Alpha: <span className={`${qa.walk_forward.oos_mean_alpha >= 0 ? "text-green-400" : "text-red-400"} font-bold`}>
                  {pct(qa.walk_forward.oos_mean_alpha)}
                </span></span>
                <span className="text-bloomberg-muted">Consistent edge: <span className={qa.walk_forward.consistent_edge ? "text-green-400 font-bold" : "text-red-400 font-bold"}>
                  {qa.walk_forward.consistent_edge ? "YES" : "NO"}
                </span></span>
                <span className="text-bloomberg-muted">Positive folds: <span className="text-bloomberg-text">{qa.walk_forward.n_positive_folds}/{qa.walk_forward.folds.length}</span></span>
              </div>
              <table className="bbg-table text-[10px]">
                <thead>
                  <tr>
                    <th>Fold</th>
                    <th>Start</th>
                    <th>End</th>
                    <th className="text-right">Ann. Return</th>
                    <th className="text-right">Volatility</th>
                    <th className="text-right">Sharpe</th>
                    <th className="text-right">Alpha</th>
                  </tr>
                </thead>
                <tbody>
                  {qa.walk_forward.folds.map((f) => (
                    <tr key={f.fold}>
                      <td className="text-bloomberg-muted">{f.fold}</td>
                      <td className="text-bloomberg-muted text-[9px]">{f.start}</td>
                      <td className="text-bloomberg-muted text-[9px]">{f.end}</td>
                      <td className={`text-right ${f.ann_return >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {pct(f.ann_return)}
                      </td>
                      <td className="text-right text-bloomberg-muted">{pct(f.volatility)}</td>
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

          {/* ── 10. Regime Probabilities ── */}
          {qa.regime && qa.regime.current_regime && (
            <div className="bbg-card">
              <p className="bbg-header">10 · Regime Probabilities (EWMA-based)</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">Current Regime</p>
                  <p className={`text-sm font-bold ${qa.regime.current_regime === "low" ? "text-green-400" : qa.regime.current_regime === "normal" ? "text-bloomberg-gold" : qa.regime.current_regime === "high" ? "text-orange-400" : "text-red-400"}`}>
                    {qa.regime.current_regime.toUpperCase()}
                  </p>
                </div>
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">Current Vol (ann.)</p>
                  <p className="text-bloomberg-text text-sm font-bold">{pct(qa.regime.current_vol)}</p>
                </div>
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">Confidence</p>
                  <p className="text-bloomberg-gold text-sm font-bold">{(qa.regime.regime_confidence * 100).toFixed(0)}%</p>
                </div>
                <div className="bbg-card">
                  <p className="text-bloomberg-muted text-[10px]">Execution</p>
                  <p className={`text-sm font-bold ${qa.regime.execution.hold ? "text-red-400" : "text-green-400"}`}>
                    {qa.regime.execution.hold ? "HOLD" : "GO"}
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-4 gap-2 mb-3">
                {Object.entries(qa.regime.regime_probabilities).map(([name, prob]) => (
                  <div key={name} className="bbg-card text-center">
                    <p className="text-bloomberg-muted text-[9px] uppercase mb-1">{name}</p>
                    <div className="h-1.5 bg-bloomberg-border rounded-full overflow-hidden mb-1">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${(prob * 100).toFixed(0)}%`,
                          background: name === "low" ? "#22c55e" : name === "normal" ? "#f3a712" : name === "high" ? "#f97316" : "#ef4444",
                        }}
                      />
                    </div>
                    <p className="text-bloomberg-text text-[10px] font-bold">{(prob * 100).toFixed(0)}%</p>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap gap-6 text-[10px]">
                <span className="text-bloomberg-muted">Equity tilt: <span className={`font-bold ${qa.regime.strategic.equity_tilt >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {qa.regime.strategic.equity_tilt >= 0 ? "+" : ""}{(qa.regime.strategic.equity_tilt * 100).toFixed(0)}%
                </span></span>
                <span className="text-bloomberg-muted">Bond tilt: <span className={`font-bold ${qa.regime.strategic.bond_tilt >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {qa.regime.strategic.bond_tilt >= 0 ? "+" : ""}{(qa.regime.strategic.bond_tilt * 100).toFixed(0)}%
                </span></span>
                <span className="text-bloomberg-muted">Tactical active: <span className={qa.regime.tactical.active ? "text-green-400 font-bold" : "text-bloomberg-muted"}>{qa.regime.tactical.active ? "YES" : "NO"}</span></span>
                {qa.regime.recent_flip && <span className="text-bloomberg-gold font-bold">⚠ Recent regime flip</span>}
              </div>
            </div>
          )}

          {/* ── 11. Dynamic Weight Caps ── */}
          {qa.dynamic_caps && Object.keys(qa.dynamic_caps.caps).length > 0 && (
            <div className="bbg-card">
              <p className="bbg-header">11 · Dynamic Weight Caps</p>
              <div className="flex flex-wrap gap-4 text-[10px] mb-2">
                <span className="text-bloomberg-muted">Top-heavy concentration: <span className="text-bloomberg-gold font-bold">{(qa.dynamic_caps.top_n_concentration * 100).toFixed(1)}%</span></span>
                {qa.dynamic_caps.top_heavy_tickers.length > 0 && (
                  <span className="text-bloomberg-muted">Top-heavy: <span className="text-bloomberg-gold">{qa.dynamic_caps.top_heavy_tickers.join(", ")}</span></span>
                )}
              </div>
              <table className="bbg-table text-[10px]">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th className="text-right">Suggested Cap</th>
                    <th className="text-right">Avg Pairwise Corr</th>
                    <th>Note</th>
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
                          {(qa.dynamic_caps!.mean_pairwise_corr[ticker] ?? 0).toFixed(3)}
                        </td>
                        <td className="text-bloomberg-muted">
                          {qa.dynamic_caps!.top_heavy_tickers.includes(ticker) ? "top-heavy" : ""}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── 12. Expected Drawdown Profile ── */}
          {qa.drawdown_profile && Object.keys(qa.drawdown_profile).length > 0 && (
            <div className="bbg-card">
              <p className="bbg-header">12 · Expected Drawdown Profile (Monte Carlo)</p>
              <table className="bbg-table text-[10px]">
                <thead>
                  <tr>
                    <th>Horizon</th>
                    <th className="text-right">Expected Max DD</th>
                    <th className="text-right">Worst (p95)</th>
                    <th className="text-right">Median Recovery</th>
                    <th className="text-right">P90 Recovery</th>
                    <th className="text-right">P(DD &gt; 10%)</th>
                    <th className="text-right">P(DD &gt; 20%)</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(qa.drawdown_profile).map(([yr, h]) => (
                    <tr key={yr}>
                      <td className="text-bloomberg-gold font-bold">{yr}Y</td>
                      <td className="text-right text-red-400">{pct(h.expected_max_dd)}</td>
                      <td className="text-right text-red-400">{pct(h.worst_dd_p95)}</td>
                      <td className="text-right text-bloomberg-muted">{h.median_recovery_months.toFixed(0)} mo</td>
                      <td className="text-right text-bloomberg-muted">{h.p90_recovery_months.toFixed(0)} mo</td>
                      <td className="text-right text-bloomberg-muted">{(h.prob_drawdown_gt_10pct * 100).toFixed(0)}%</td>
                      <td className="text-right text-bloomberg-muted">{(h.prob_drawdown_gt_20pct * 100).toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── 13. Model Drift Score ── */}
          {qa.model_drift && qa.model_drift.per_asset && Object.keys(qa.model_drift.per_asset).length > 0 && (
            <div className="bbg-card">
              <div className="flex items-center justify-between mb-2">
                <p className="bbg-header mb-0">13 · Model Parameter Drift Monitor</p>
                <span className={`text-[10px] font-bold px-2 py-0.5 border ${qa.model_drift.engine_healthy ? "border-green-800 text-green-400 bg-green-900/20" : "border-red-800 text-red-400 bg-red-900/20"}`}>
                  {qa.model_drift.engine_healthy ? "ENGINE STABLE" : `${qa.model_drift.n_alerts} ALERT(S)`}
                </span>
              </div>
              <div className="flex flex-wrap gap-4 text-[10px] mb-2">
                <span className="text-bloomberg-muted">Mean drift score: <span className="text-bloomberg-text">{qa.model_drift.mean_drift_score.toFixed(3)}</span></span>
                <span className="text-bloomberg-muted">Snapshot: <span className="text-bloomberg-muted">{qa.model_drift.snapshot_ts}</span></span>
              </div>
              <table className="bbg-table text-[10px]">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th className="text-right">Return (3mo)</th>
                    <th className="text-right">Return (12mo)</th>
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
                        <td className={`text-right ${d.mu_short >= 0 ? "text-green-400" : "text-red-400"}`}>{pct(d.mu_short)}</td>
                        <td className={`text-right ${d.mu_long >= 0 ? "text-green-400" : "text-red-400"}`}>{pct(d.mu_long)}</td>
                        <td className={`text-right ${d.sharpe_short >= 0 ? "text-green-400" : "text-red-400"}`}>{d.sharpe_short.toFixed(2)}</td>
                        <td className={`text-right ${d.sharpe_long >= 0 ? "text-green-400" : "text-red-400"}`}>{d.sharpe_long.toFixed(2)}</td>
                        <td className={`text-right font-medium ${d.drift_score > 0.5 ? "text-red-400" : d.drift_score > 0.25 ? "text-bloomberg-gold" : "text-bloomberg-muted"}`}>
                          {d.drift_score.toFixed(3)}
                        </td>
                        <td className={d.alert ? "text-red-400 font-bold" : "text-bloomberg-muted"}>
                          {d.alert ? "⚠ ALERT" : "OK"}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── 14. Naive Portfolio Benchmarks ── */}
          {qa.naive_benchmarks && qa.naive_benchmarks.length > 0 && (
            <div className="bbg-card">
              <p className="bbg-header">14 · Naive Portfolio Benchmarks</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <table className="bbg-table text-[10px]">
                  <thead>
                    <tr>
                      <th>Model</th>
                      <th className="text-right">Sharpe</th>
                      <th className="text-right">Ann. Return</th>
                      <th className="text-right">Max DD</th>
                    </tr>
                  </thead>
                  <tbody>
                    {qa.naive_benchmarks.map((row) => (
                      <tr key={row.model} className={row.model === "Your Portfolio" ? "border-t border-bloomberg-gold" : ""}>
                        <td className={row.model === "Your Portfolio" ? "text-bloomberg-gold font-bold" : "text-bloomberg-text"}>
                          {row.model}
                        </td>
                        <td className={`text-right font-medium ${row.sharpe >= 1 ? "text-green-400" : row.sharpe >= 0 ? "text-bloomberg-gold" : "text-red-400"}`}>
                          {row.sharpe.toFixed(3)}
                        </td>
                        <td className={`text-right ${row.ann_return >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {pct(row.ann_return)}
                        </td>
                        <td className="text-right text-red-400">{pct(row.max_dd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div>
                  <p className="text-bloomberg-muted text-[9px] mb-1">Sharpe Ratio Comparison</p>
                  <ResponsiveContainer width="100%" height={160}>
                    <BarChart
                      data={[...qa.naive_benchmarks].sort((a, b) => b.sharpe - a.sharpe)}
                      layout="vertical"
                      margin={{ left: 0, right: 8, top: 0, bottom: 0 }}
                    >
                      <XAxis type="number" tick={{ fontSize: 8 }} tickLine={false} />
                      <YAxis dataKey="model" type="category" tick={{ fontSize: 8 }} width={90} tickLine={false} />
                      <Tooltip formatter={(v: number) => v.toFixed(3)} contentStyle={{ fontSize: 10, background: "#111820", border: "1px solid #1e2535" }} />
                      <Bar dataKey="sharpe" radius={[0, 2, 2, 0]}
                        fill="#f3a712"
                        label={false}
                        isAnimationActive={false}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          )}

          {/* ── 15. Factor Risk Decomposition ── */}
          {qa.factor_risk && qa.factor_risk.per_asset && Object.keys(qa.factor_risk.per_asset).length > 0 && (
            <div className="bbg-card">
              <div className="flex items-center justify-between mb-3">
                <p className="bbg-header mb-0">15 · Factor Risk Decomposition</p>
                <div className="flex gap-4 text-[10px]">
                  <span className="text-bloomberg-muted">Portfolio vol: <span className="text-bloomberg-gold font-bold">{pct(qa.factor_risk.portfolio_vol)}</span></span>
                  {qa.factor_risk.factor_decomposition?.r_squared != null && (
                    <>
                      <span className="text-bloomberg-muted">Systematic: <span className="text-bloomberg-text">{(qa.factor_risk.factor_decomposition.systematic_risk_pct as number).toFixed(1)}%</span></span>
                      <span className="text-bloomberg-muted">Idiosyncratic: <span className="text-bloomberg-text">{(qa.factor_risk.factor_decomposition.idiosyncratic_risk_pct as number).toFixed(1)}%</span></span>
                    </>
                  )}
                </div>
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
        </>
        );
      })()}
      </>}
    </div>
  );
}
