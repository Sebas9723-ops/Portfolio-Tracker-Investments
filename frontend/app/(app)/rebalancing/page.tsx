"use client";
import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { fetchRebalancing, fetchRequiredForMaxSharpe } from "@/lib/api/analytics";
import { fetchContributionPlan } from "@/lib/api/contribution";
import type { ContributionPlanResponse } from "@/lib/api/contribution";
import { useAIChat } from "@/lib/context/aiChatContext";
import { fetchSettings } from "@/lib/api/settings";
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

  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });

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
                quantMutation.mutate({ available_cash: contribution, profile })
              }
              disabled={quantMutation.isPending}
              className="bg-bloomberg-gold text-bloomberg-bg text-[10px] font-bold px-5 py-1.5 hover:opacity-90 disabled:opacity-50 uppercase tracking-wider"
            >
              {quantMutation.isPending ? "OPTIMIZING…" : "RUN OPTIMIZATION"}
            </button>
          </div>

          <p className="text-bloomberg-muted text-[10px] mb-3">
            Deploy{" "}
            <span className="text-bloomberg-gold font-bold">
              {fmtCurrency(contribution, ccy)}
            </span>{" "}
            using CVaR-constrained optimization with Ledoit-Wolf covariance,
            HMM regime detection, and Black-Litterman expected returns.
          </p>

          {quantMutation.isPending && (
            <div className="flex items-center gap-2 text-bloomberg-muted text-xs py-4">
              <span className="animate-pulse">Running 500-sample resampling optimization…</span>
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
                expectedReturn={quantData.quant_result.expected_return}
                expectedSharpe={quantData.quant_result.expected_sharpe}
                cvar95={quantData.quant_result.cvar_95}
                optimizationTimestamp={quantData.optimization_timestamp}
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
