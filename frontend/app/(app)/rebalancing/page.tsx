"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchRebalancing, fetchRequiredForMaxSharpe } from "@/lib/api/analytics";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { fmtCurrency, fmtPct } from "@/lib/formatters";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, ReferenceLine,
} from "recharts";

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
  const [contribution, setContribution] = useState(0);
  const [tcModel, setTcModel] = useState("broker");
  const [msPeriod, setMsPeriod] = useState("2y");
  const [msMaxSingle, setMsMaxSingle] = useState(0.40);

  const { data: portfolio } = usePortfolio();
  const rows = portfolio?.rows ?? [];
  const totalValue = portfolio?.total_value_base ?? 0;
  const ccy = portfolio?.base_currency ?? "USD";

  const { data, isLoading } = useQuery({
    queryKey: ["rebalancing", contribution, tcModel],
    queryFn: () => fetchRebalancing({ contribution, tc_model: tcModel }),
  });

  const { data: msData, isLoading: msLoading, refetch: refetchMs } = useQuery({
    queryKey: ["rebalancing-max-sharpe", msPeriod, msMaxSingle],
    queryFn: () => fetchRequiredForMaxSharpe({ period: msPeriod, max_single_asset: msMaxSingle }),
    enabled: false,
  });

  const totalTC = data?.reduce((s, r) => s + r.estimated_tc, 0) ?? 0;
  const threshold = 5; // 5% drift threshold for badge (display only)

  // Contribution planner: buy-only allocation from current holdings
  const buyPlan = (() => {
    if (!data || contribution <= 0) return [];
    const newTotal = totalValue + contribution;
    return data
      .map((r) => {
        const targetValue = (r.target_weight / 100) * newTotal;
        const currentValue = r.value_base;
        const gap = targetValue - currentValue;
        return { ticker: r.ticker, name: r.name, gap, currentValue, targetValue };
      })
      .filter((x) => x.gap > 0)
      .map((x) => {
        const totalGap = data
          .map((r) => {
            const tv = (r.target_weight / 100) * newTotal;
            const gap = tv - r.value_base;
            return gap > 0 ? gap : 0;
          })
          .reduce((s, v) => s + v, 0);
        const allocPct = totalGap > 0 ? (x.gap / totalGap) * 100 : 0;
        const allocValue = (allocPct / 100) * contribution;
        return { ...x, allocPct, allocValue };
      })
      .sort((a, b) => b.allocValue - a.allocValue);
  })();

  return (
    <div className="space-y-4">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Rebalancing</h1>

      {/* Parameters */}
      <div className="bbg-card">
        <p className="bbg-header">Parameters</p>
        <div className="flex flex-wrap gap-6 items-end">
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Cash to Deploy ({ccy})</label>
            <input
              type="number"
              value={contribution}
              onChange={(e) => setContribution(parseFloat(e.target.value) || 0)}
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

      {/* Contribution Planner */}
      {contribution > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Contribution Planner — Buy-Only Allocation</p>
          <p className="text-bloomberg-muted text-[10px] mb-3">
            How to deploy{" "}
            <span className="text-bloomberg-gold font-bold">{fmtCurrency(contribution, ccy)}</span>
            {" "}without selling any existing positions (total after: {fmtCurrency(totalValue + contribution, ccy)})
          </p>

          {buyPlan.length === 0 ? (
            <p className="text-bloomberg-muted text-xs">Portfolio is on target — no buys needed.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="bbg-table">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Name</th>
                    <th className="text-right">Current Value</th>
                    <th className="text-right">Target Value</th>
                    <th className="text-right">Buy Amount</th>
                    <th className="text-right">% of Cash</th>
                  </tr>
                </thead>
                <tbody>
                  {buyPlan.map((x) => (
                    <tr key={x.ticker}>
                      <td className="text-bloomberg-gold font-medium">{x.ticker}</td>
                      <td className="text-bloomberg-muted">{x.name}</td>
                      <td className="text-right">{fmtCurrency(x.currentValue, ccy)}</td>
                      <td className="text-right">{fmtCurrency(x.targetValue, ccy)}</td>
                      <td className="text-right text-green-400 font-medium">{fmtCurrency(x.allocValue, ccy)}</td>
                      <td className="text-right">{fmtPct(x.allocPct)}</td>
                    </tr>
                  ))}
                  <tr className="border-t border-bloomberg-border">
                    <td colSpan={4} className="text-bloomberg-muted text-right text-[10px]">Total deployed</td>
                    <td className="text-right text-bloomberg-gold font-bold">
                      {fmtCurrency(buyPlan.reduce((s, x) => s + x.allocValue, 0), ccy)}
                    </td>
                    <td className="text-right text-bloomberg-gold font-bold">100%</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Trade Suggestions */}
      <div className="bbg-card">
        <p className="bbg-header">Trade Suggestions</p>
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

      {/* Required Contribution for Max Sharpe */}
      <div className="bbg-card">
        <p className="bbg-header" style={{ color: "#f3a712" }}>Required Contribution to Reach Max Sharpe (No Selling)</p>
        <p className="text-bloomberg-muted text-[10px] mb-3">
          Minimum cash needed to reach Max Sharpe weights without selling any existing positions.
        </p>

        <div className="flex flex-wrap gap-4 items-end mb-3">
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">History Period</label>
            <select
              value={msPeriod}
              onChange={(e) => setMsPeriod(e.target.value)}
              className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs"
            >
              {["1y", "2y", "3y", "5y"].map((p) => <option key={p}>{p}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">
              Max Single Asset: {fmtPct(msMaxSingle * 100)}
            </label>
            <input
              type="range" min={0.1} max={1} step={0.05} value={msMaxSingle}
              onChange={(e) => setMsMaxSingle(parseFloat(e.target.value))}
              className="w-40 accent-bloomberg-gold"
            />
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
                  {Object.values(msData.buy_plan).filter((x) => x.buy_value > 0).length}
                </p>
              </div>
            </div>

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
