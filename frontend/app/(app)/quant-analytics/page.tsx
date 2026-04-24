"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchQuantAdvanced } from "@/lib/api/analytics";
import { fmtCurrency } from "@/lib/formatters";
import type { BLExplanationRow } from "@/lib/api/contribution";

const pct = (v: number | null | undefined, d = 1) =>
  v == null ? "—" : `${(v * 100).toFixed(d)}%`;

const MODULES = [
  "Band Rebalancing", "Net Alpha", "Tax Drag", "Liquidity", "Model Agreement",
  "Return Bands", "BL Explainability", "TE Budget", "Walk-Forward", "Regime Probs",
  "Dynamic Caps", "Drawdown Profile", "Model Drift", "Naive Benchmarks", "Factor Risk",
];

export default function QuantAnalyticsPage() {
  const [period, setPeriod] = useState("2y");
  const [enabled, setEnabled] = useState(false);

  const { data: qa, isFetching, refetch } = useQuery({
    queryKey: ["quant-advanced-full", period],
    queryFn: () =>
      fetchQuantAdvanced({ period, benchmark_ticker: "VOO", n_bootstrap: 500, n_dd_sims: 1000 }),
    enabled,
    staleTime: 10 * 60 * 1000,
  });

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Quant Analytics Engine</h1>
          <p className="text-bloomberg-muted text-[10px] mt-0.5">
            15 modules — execution · return attribution · risk · validation
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs"
          >
            {["1y", "2y", "3y", "5y"].map((p) => <option key={p}>{p}</option>)}
          </select>
          <button
            onClick={() => { setEnabled(true); refetch(); }}
            disabled={isFetching}
            className="bg-bloomberg-gold text-bloomberg-bg text-[10px] font-bold px-5 py-1.5 hover:opacity-90 disabled:opacity-50 uppercase tracking-wider"
          >
            {isFetching ? "COMPUTING…" : "RUN ALL 15 MODULES"}
          </button>
        </div>
      </div>

      {/* Idle state — module list */}
      {!qa && !isFetching && (
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

      {qa && (
        <>
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
      )}
    </div>
  );
}
