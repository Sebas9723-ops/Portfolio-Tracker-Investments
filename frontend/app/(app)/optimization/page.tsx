"use client";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { fetchFrontier, fetchBlackLitterman } from "@/lib/api/analytics";
import { fetchProfileOptimal } from "@/lib/api/profile";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { useProfileStore } from "@/lib/store/profileStore";
import { fmtPct, fmtCurrency } from "@/lib/formatters";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceDot,
} from "recharts";
import type { OptimizationResult, FrontierPoint } from "@/lib/types";
import { Plus, Trash2 } from "lucide-react";

const PROFILE_COLORS: Record<string, string> = {
  conservative: "#2563eb",
  base: "#16a34a",
  aggressive: "#dc2626",
};
const PROFILE_LABELS: Record<string, string> = {
  conservative: "Conservador",
  base: "Base",
  aggressive: "Agresivo",
};

const COLORS = { maxSharpe: "#f3a712", minVol: "#38b2ff", riskParity: "#4dff4d", bl: "#c084fc", current: "#8a9bb5" }

function sharpeToColor(sharpe: number, min: number, max: number): string {
  const t = max === min ? 0.5 : Math.max(0, Math.min(1, (sharpe - min) / (max - min)));
  const r = Math.round(220 * (1 - t) + 22 * t);
  const g = Math.round(38 * (1 - t) + 163 * t);
  const b = Math.round(38 * (1 - t) + 74 * t);
  return `rgb(${r},${g},${b})`;
};

// Compute recommended shares from weights + portfolio value + prices
function computeShares(
  weights: Record<string, number>,
  rows: { ticker: string; price_base: number }[],
  totalValue: number,
): Record<string, number> {
  const result: Record<string, number> = {};
  for (const [ticker, w] of Object.entries(weights)) {
    const row = rows.find((r) => r.ticker === ticker);
    if (row && row.price_base > 0) {
      result[ticker] = parseFloat(((w * totalValue) / row.price_base).toFixed(4));
    } else {
      result[ticker] = 0;
    }
  }
  return result;
}

function WeightsSharesTable({
  label, color, weights, shares, currency,
}: {
  label: string;
  color: string;
  weights: Record<string, number>;
  shares: Record<string, number>;
  currency: string;
}) {
  return (
    <div className="bbg-card">
      <p className="bbg-header" style={{ color }}>{label}</p>
      <table className="bbg-table">
        <thead>
          <tr>
            <th>Ticker</th>
            <th className="text-right">Weight</th>
            <th className="text-right">Shares</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(weights)
            .sort(([, a], [, b]) => b - a)
            .map(([t, w]) => (
              <tr key={t}>
                <td className="text-bloomberg-gold">{t}</td>
                <td className="text-right">{fmtPct((w as number) * 100)}</td>
                <td className="text-right text-bloomberg-muted">{(shares[t] ?? 0).toFixed(4)}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

export default function OptimizationPage() {
  const { data: portfolio } = usePortfolio();
  const { profile } = useProfileStore();
  const [maxSingle, setMaxSingle] = useState(0.40);
  const [nSim, setNSim] = useState(3000);
  const [period, setPeriod] = useState("2y");

  const { data: profileData } = useQuery({
    queryKey: ["profile-optimal"],
    queryFn: () => fetchProfileOptimal(period),
    staleTime: 5 * 60 * 1000,
  });

  // Black-Litterman state
  const [blViews, setBlViews] = useState<{ ticker: string; ret: string }[]>([]);
  const [blResult, setBlResult] = useState<Record<string, number> | null>(null);
  const [tau, setTau] = useState(0.05);
  const [riskAversion, setRiskAversion] = useState(3.0);

  const { data: result, isFetching: pendingFrontier, refetch: runFrontier } = useQuery({
    queryKey: ["frontier", maxSingle, nSim, period],
    queryFn: () => fetchFrontier({ max_single_asset: maxSingle, n_simulations: nSim, period }),
    staleTime: 10 * 60 * 1000,
  });

  const { mutate: runBL, isPending: pendingBL } = useMutation({
    mutationFn: () => {
      const views: Record<string, number> = {};
      blViews.forEach(({ ticker, ret }) => {
        if (ticker && ret) views[ticker.toUpperCase()] = parseFloat(ret) / 100;
      });
      return fetchBlackLitterman({ views, tau, risk_aversion: riskAversion, max_single_asset: maxSingle, period });
    },
    onSuccess: (data) => setBlResult(data.weights),
  });

  const rows = portfolio?.rows ?? [];
  const totalValue = portfolio?.total_value_base ?? 0;
  const ccy = portfolio?.base_currency ?? "USD";

  const minSharpe = result ? Math.min(...result.frontier.map((p) => p.sharpe)) : 0;
  const maxSharpe = result ? Math.max(...result.frontier.map((p) => p.sharpe)) : 1;

  const CustomDot = (props: { payload?: FrontierPoint; cx?: number; cy?: number }) => {
    const { cx, cy, payload } = props;
    if (!payload || !cx || !cy) return null;
    return <circle cx={cx} cy={cy} r={2.5} fill={sharpeToColor(payload.sharpe, minSharpe, maxSharpe)} opacity={0.75} />;
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Optimization</h1>
        {profile && (
          <span
            className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold"
            style={{ color: PROFILE_COLORS[profile], background: profile === "conservative" ? "#eff6ff" : profile === "base" ? "#f0fdf4" : "#fef2f2" }}
          >
            Perfil: {PROFILE_LABELS[profile]}
          </span>
        )}
      </div>

      {/* Controls */}
      <div className="bbg-card">
        <p className="bbg-header">Constraints</p>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-3">
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">
              Max Single Asset: {fmtPct(maxSingle * 100)}
            </label>
            <input type="range" min={0.1} max={1} step={0.05} value={maxSingle}
              onChange={(e) => setMaxSingle(parseFloat(e.target.value))}
              className="w-full accent-bloomberg-gold" />
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">
              Simulations: {nSim.toLocaleString()}
            </label>
            <input type="range" min={500} max={8000} step={500} value={nSim}
              onChange={(e) => setNSim(parseInt(e.target.value))}
              className="w-full accent-bloomberg-gold" />
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Period</label>
            <select value={period} onChange={(e) => setPeriod(e.target.value)}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs">
              {["1y", "2y", "3y", "5y"].map((p) => <option key={p}>{p}</option>)}
            </select>
          </div>
        </div>
        <button onClick={() => runFrontier()} disabled={pendingFrontier}
          className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-6 py-1.5 hover:opacity-90 disabled:opacity-50">
          {pendingFrontier ? "COMPUTING…" : "RUN OPTIMIZATION"}
        </button>
      </div>

      {pendingFrontier && !result && (
        <div className="bbg-card text-center text-bloomberg-muted text-xs py-8">Computing efficient frontier…</div>
      )}

      {result && (
        <>
          {/* Efficient Frontier */}
          <div className="bbg-card">
            <p className="bbg-header">Efficient Frontier ({result.frontier.length.toLocaleString()} portfolios)</p>
            <div className="grid grid-cols-3 gap-3 mb-3">
              <div>
                <p className="text-bloomberg-muted text-[10px]">Max Sharpe</p>
                <p className="text-bloomberg-gold text-xs font-bold">
                  Sharpe {result.max_sharpe.sharpe.toFixed(3)} · Ret {fmtPct(result.max_sharpe.ret)} · Vol {fmtPct(result.max_sharpe.vol)}
                </p>
              </div>
              <div>
                <p className="text-bloomberg-muted text-[10px]">Min Volatility</p>
                <p className="text-[#38b2ff] text-xs font-bold">
                  Sharpe {result.min_vol.sharpe.toFixed(3)} · Ret {fmtPct(result.min_vol.ret)} · Vol {fmtPct(result.min_vol.vol)}
                </p>
              </div>
              <div>
                <p className="text-bloomberg-muted text-[10px]">Current Portfolio</p>
                <p className="text-bloomberg-muted text-xs font-bold">
                  {result.current_metrics.sharpe != null
                    ? `Sharpe ${result.current_metrics.sharpe.toFixed(3)} · Ret ${fmtPct(result.current_metrics.return)} · Vol ${fmtPct(result.current_metrics.volatility)}`
                    : "—"}
                </p>
              </div>
            </div>
            <ResponsiveContainer width="100%" height={300}>
              <ScatterChart margin={{ top: 10, right: 20, bottom: 20, left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="vol" name="Volatility %" type="number" domain={["auto", "auto"]}
                  tick={{ fontSize: 10, fill: "#94a3b8" }} tickLine={false}
                  label={{ value: "Volatility (%)", position: "insideBottom", offset: -10, fontSize: 10, fill: "#64748b" }} />
                <YAxis dataKey="ret" name="Return %" type="number" domain={["auto", "auto"]}
                  tick={{ fontSize: 10, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={40}
                  label={{ value: "Return (%)", angle: -90, position: "insideLeft", fontSize: 10, fill: "#64748b" }} />
                <Tooltip cursor={false}
                  contentStyle={{ background: "#fff", border: "1px solid #e2e8f0", fontSize: 11 }}
                  formatter={(v: number) => `${v.toFixed(2)}%`} />
                <Scatter data={result.frontier} shape={<CustomDot />} />
                <ReferenceDot x={result.max_sharpe.vol} y={result.max_sharpe.ret} r={7}
                  fill={COLORS.maxSharpe} stroke="#fff"
                  label={{ value: "★ Max Sharpe", position: "top", fontSize: 9, fill: COLORS.maxSharpe }} />
                <ReferenceDot x={result.min_vol.vol} y={result.min_vol.ret} r={7}
                  fill={COLORS.minVol} stroke="#fff"
                  label={{ value: "★ Min Vol", position: "top", fontSize: 9, fill: COLORS.minVol }} />
                {result.current_metrics.volatility != null && (
                  <ReferenceDot x={result.current_metrics.volatility} y={result.current_metrics.return} r={7}
                    fill={COLORS.current} stroke="#fff"
                    label={{ value: "● Current", position: "top", fontSize: 9, fill: COLORS.current }} />
                )}
                {profileData?.profiles?.[profile]?.metrics && (
                  <ReferenceDot
                    x={profileData.profiles[profile].metrics.ann_vol}
                    y={profileData.profiles[profile].metrics.ann_return}
                    r={8}
                    fill={PROFILE_COLORS[profile] ?? "#888"}
                    stroke="#fff"
                    strokeWidth={2}
                    label={{
                      value: `◆ ${PROFILE_LABELS[profile] ?? profile}`,
                      position: "bottom",
                      fontSize: 9,
                      fill: PROFILE_COLORS[profile] ?? "#888",
                    }}
                  />
                )}
              </ScatterChart>
            </ResponsiveContainer>
            <div className="flex items-center gap-2 mt-2 justify-end text-[10px] text-bloomberg-muted">
              <span>Low Sharpe</span>
              <div className="w-24 h-2 rounded" style={{ background: "linear-gradient(to right, rgb(220,38,38), rgb(22,163,74))" }} />
              <span>High Sharpe</span>
            </div>
          </div>

          {/* Weights + Shares tables */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <WeightsSharesTable
              label="Max Sharpe"
              color={COLORS.maxSharpe}
              weights={result.max_sharpe.weights}
              shares={computeShares(result.max_sharpe.weights, rows, totalValue)}
              currency={ccy}
            />
            <WeightsSharesTable
              label="Min Volatility"
              color={COLORS.minVol}
              weights={result.min_vol.weights}
              shares={computeShares(result.min_vol.weights, rows, totalValue)}
              currency={ccy}
            />
            <WeightsSharesTable
              label="Risk Parity"
              color={COLORS.riskParity}
              weights={result.risk_parity}
              shares={computeShares(result.risk_parity, rows, totalValue)}
              currency={ccy}
            />
          </div>
        </>
      )}

      {/* Black-Litterman */}
      <div className="bbg-card">
        <p className="bbg-header" style={{ color: COLORS.bl }}>Black-Litterman Optimization</p>
        <p className="text-bloomberg-muted text-[10px] mb-3">
          Express your views on expected annual returns for specific tickers. The model combines your views with the market equilibrium prior.
        </p>

        {/* BL parameters */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Tau (uncertainty): {tau}</label>
            <input type="range" min={0.01} max={0.25} step={0.01} value={tau}
              onChange={(e) => setTau(parseFloat(e.target.value))}
              className="w-full accent-bloomberg-gold" />
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Risk Aversion: {riskAversion}</label>
            <input type="range" min={1} max={10} step={0.5} value={riskAversion}
              onChange={(e) => setRiskAversion(parseFloat(e.target.value))}
              className="w-full accent-bloomberg-gold" />
          </div>
        </div>

        {/* Views input */}
        <div className="space-y-2 mb-3">
          <p className="text-bloomberg-muted text-[10px] uppercase">Views (expected annual return %)</p>
          {blViews.map((v, i) => (
            <div key={i} className="flex gap-2 items-center">
              <input
                value={v.ticker}
                onChange={(e) => setBlViews((prev) => prev.map((x, j) => j === i ? { ...x, ticker: e.target.value.toUpperCase() } : x))}
                placeholder="Ticker"
                className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-gold px-2 py-1 text-xs w-24 focus:outline-none focus:border-bloomberg-gold"
              />
              <span className="text-bloomberg-muted text-xs">→</span>
              <input
                value={v.ret}
                onChange={(e) => setBlViews((prev) => prev.map((x, j) => j === i ? { ...x, ret: e.target.value } : x))}
                placeholder="Return %"
                type="number"
                step="0.5"
                className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs w-28 focus:outline-none focus:border-bloomberg-gold"
              />
              <span className="text-bloomberg-muted text-xs">% per year</span>
              <button onClick={() => setBlViews((prev) => prev.filter((_, j) => j !== i))}
                className="text-bloomberg-muted hover:text-bloomberg-red">
                <Trash2 size={11} />
              </button>
            </div>
          ))}
          <button
            onClick={() => setBlViews((prev) => [...prev, { ticker: "", ret: "" }])}
            className="flex items-center gap-1 text-bloomberg-muted hover:text-bloomberg-gold text-[10px]">
            <Plus size={11} /> Add view
          </button>
        </div>

        {/* Portfolio tickers as quick-add hints */}
        {rows.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-3">
            <span className="text-bloomberg-muted text-[10px] self-center">Quick add:</span>
            {rows.map((r) => (
              <button key={r.ticker}
                onClick={() => {
                  if (!blViews.find((v) => v.ticker === r.ticker)) {
                    setBlViews((prev) => [...prev, { ticker: r.ticker, ret: "" }]);
                  }
                }}
                className="text-[10px] px-1.5 py-0.5 border border-bloomberg-border text-bloomberg-muted hover:text-bloomberg-gold hover:border-bloomberg-gold">
                {r.ticker}
              </button>
            ))}
          </div>
        )}

        <button onClick={() => runBL()} disabled={pendingBL}
          className="bg-[#c084fc] text-bloomberg-bg text-xs font-bold px-6 py-1.5 hover:opacity-90 disabled:opacity-50">
          {pendingBL ? "COMPUTING…" : "RUN BLACK-LITTERMAN"}
        </button>

        {blResult && Object.keys(blResult).length > 0 && (
          <div className="mt-4">
            <WeightsSharesTable
              label="Black-Litterman Optimal Portfolio"
              color={COLORS.bl}
              weights={blResult}
              shares={computeShares(blResult, rows, totalValue)}
              currency={ccy}
            />
          </div>
        )}
      </div>
    </div>
  );
}
