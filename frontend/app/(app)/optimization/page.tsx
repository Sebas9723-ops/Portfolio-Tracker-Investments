"use client";
import { useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchFrontier, fetchBlackLitterman } from "@/lib/api/analytics";
import { fetchProfileOptimal } from "@/lib/api/profile";
import { fetchSettings, saveTickerWeightRules, saveCombinationRanges } from "@/lib/api/settings";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { useProfileStore } from "@/lib/store/profileStore";
import { useSettingsStore } from "@/lib/store/settingsStore";
import { fmtPct, fmtCurrency } from "@/lib/formatters";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceDot,
} from "recharts";
import type { OptimizationResult, FrontierPoint, TickerFloorCap, CombinationRange } from "@/lib/types";
import { Plus, Trash2, Save } from "lucide-react";

const PROFILES = ["conservative", "base", "aggressive"] as const;
type ProfileKey = typeof PROFILES[number];

const PROFILE_COLORS: Record<ProfileKey, string> = {
  conservative: "#2563eb",
  base: "#16a34a",
  aggressive: "#dc2626",
};
const PROFILE_LABELS: Record<ProfileKey, string> = {
  conservative: "Conservative",
  base: "Base",
  aggressive: "Aggressive",
};

const COLORS = { maxSharpe: "#f3a712", minVol: "#38b2ff", maxReturn: "#ff4b6e", riskParity: "#4dff4d", bl: "#c084fc", current: "#8a9bb5" }

function sharpeToColor(sharpe: number, min: number, max: number): string {
  const t = max === min ? 0.5 : Math.max(0, Math.min(1, (sharpe - min) / (max - min)));
  const r = Math.round(220 * (1 - t) + 22 * t);
  const g = Math.round(38 * (1 - t) + 163 * t);
  const b = Math.round(38 * (1 - t) + 74 * t);
  return `rgb(${r},${g},${b})`;
};

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
  label, color, weights, shares,
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
  const qc = useQueryClient();
  const { data: portfolio } = usePortfolio();
  const { profile } = useProfileStore();
  const { bl_views: savedBlViews, setSettings, max_single_asset, optimization_periods } = useSettingsStore();
  const maxSingle = max_single_asset ?? 0.40;
  const period = optimization_periods?.[profile] ?? "2y";
  const N_SIM = 12000;

  // ── Motor 1 state ─────────────────────────────────────────────────────────
  // {profile: {ticker: {floor, cap}}} — local edit state
  const [allFloorCap, setAllFloorCap] = useState<Record<string, Record<string, TickerFloorCap>>>({});
  const [m1Saved, setM1Saved] = useState(false);
  const [m1Error, setM1Error] = useState<string | null>(null);

  // ── Motor 2 state ─────────────────────────────────────────────────────────
  const [allCombos, setAllCombos] = useState<Record<string, CombinationRange[]>>({});
  const [newComboTickers, setNewComboTickers] = useState<string[]>([]);
  const [newComboMinEnabled, setNewComboMinEnabled] = useState(true);
  const [newComboMaxEnabled, setNewComboMaxEnabled] = useState(true);
  const [newComboMin, setNewComboMin] = useState("40");
  const [newComboMax, setNewComboMax] = useState("60");
  const [m2Saved, setM2Saved] = useState(false);

  // Load saved settings to pre-populate Motor 1 & 2
  const { data: savedSettings } = useQuery({
    queryKey: ["settings"],
    queryFn: fetchSettings,
    staleTime: 60 * 1000,
  });

  useEffect(() => {
    if (!savedSettings) return;
    if (savedSettings.ticker_weight_rules && Object.keys(savedSettings.ticker_weight_rules).length > 0) {
      setAllFloorCap(savedSettings.ticker_weight_rules as Record<string, Record<string, TickerFloorCap>>);
    }
    if (savedSettings.combination_ranges && Object.keys(savedSettings.combination_ranges).length > 0) {
      setAllCombos(savedSettings.combination_ranges as Record<string, CombinationRange[]>);
    }
  }, [savedSettings]);

  const { data: profileData } = useQuery({
    queryKey: ["profile-optimal"],
    queryFn: () => fetchProfileOptimal(period),
    staleTime: 5 * 60 * 1000,
  });

  // Black-Litterman state — pre-populated from localStorage if available
  const [blViews, setBlViews] = useState<{ ticker: string; ret: string }[]>(
    () => savedBlViews?.[profile] ?? []
  );
  const [blResult, setBlResult] = useState<Record<string, number> | null>(null);
  const [tau, setTau] = useState(0.05);
  const [riskAversion, setRiskAversion] = useState(3.0);
  const [blViewsSaved, setBlViewsSaved] = useState(false);

  const { data: result, isFetching: pendingFrontier } = useQuery({
    queryKey: ["frontier", maxSingle, N_SIM, period, profile],
    queryFn: () => fetchFrontier({ max_single_asset: maxSingle, n_simulations: N_SIM, period, profile }),
    staleTime: 10 * 60 * 1000,
  });

  // Persist all three frontier reference points so Contribution Planner can
  // pick the right one based on the active profile (aggressive→max_return, etc.)
  useEffect(() => {
    if (!result) return;
    setSettings({
      frontier_result: {
        max_sharpe: { ret: result.max_sharpe.ret, vol: result.max_sharpe.vol, sharpe: result.max_sharpe.sharpe },
        min_vol:    { ret: result.min_vol.ret,    vol: result.min_vol.vol,    sharpe: result.min_vol.sharpe },
        max_return: { ret: result.max_return.ret, vol: result.max_return.vol, sharpe: result.max_return.sharpe },
      },
    });
  }, [result, setSettings]);

  const { mutate: runBL, isPending: pendingBL } = useMutation({
    mutationFn: () => {
      const views: Record<string, number> = {};
      blViews.forEach(({ ticker, ret }) => {
        if (ticker && ret) views[ticker.toUpperCase()] = parseFloat(ret) / 100;
      });
      return fetchBlackLitterman({ views, tau, risk_aversion: riskAversion, max_single_asset: maxSingle, period, profile });
    },
    onSuccess: (data) => setBlResult(data.weights),
  });

  function saveBlViews() {
    const existing = savedBlViews ?? {};
    setSettings({ bl_views: { ...existing, [profile]: blViews } });
    setBlViewsSaved(true);
    setTimeout(() => setBlViewsSaved(false), 2000);
  }

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

  const activeProfile = (profile as ProfileKey) || "base";

  // Reload BL views when active profile changes
  useEffect(() => {
    setBlViews(savedBlViews?.[profile] ?? []);
    setBlViewsSaved(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile]);

  // ── Motor 1 helpers ───────────────────────────────────────────────────────
  const getFloorCap = (ticker: string): TickerFloorCap =>
    allFloorCap[activeProfile]?.[ticker] ?? { floor: 0, cap: 1 };

  const setFloorCap = (ticker: string, field: "floor" | "cap", val: string) => {
    const num = parseFloat(val);
    if (isNaN(num)) return;
    setAllFloorCap((prev) => {
      const existing = prev[activeProfile]?.[ticker] ?? { floor: 0, cap: 1 };
      return {
        ...prev,
        [activeProfile]: {
          ...(prev[activeProfile] ?? {}),
          [ticker]: { ...existing, [field]: num / 100 },
        },
      };
    });
    setM1Saved(false);
    setM1Error(null);
  };

  const { mutate: saveM1, isPending: savingM1 } = useMutation({
    mutationFn: () => {
      const profileRules = allFloorCap[activeProfile] ?? {};
      // Sanitize: only send valid {floor, cap} entries
      const cleanRules: Record<string, { floor: number; cap: number }> = {};
      for (const [ticker, rule] of Object.entries(profileRules)) {
        if (rule && typeof rule === "object" && "floor" in rule && "cap" in rule) {
          cleanRules[ticker] = { floor: Number(rule.floor), cap: Number(rule.cap) };
        }
      }
      return saveTickerWeightRules(activeProfile, cleanRules);
    },
    onSuccess: () => {
      setM1Saved(true);
      setM1Error(null);
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (err: unknown) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const detail = (err as any)?.response?.data?.detail ?? (err instanceof Error ? err.message : String(err));
      setM1Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      setM1Saved(false);
    },
  });

  // ── Motor 2 helpers ───────────────────────────────────────────────────────
  const combosForProfile = allCombos[activeProfile] ?? [];

  const addCombo = () => {
    if (newComboTickers.length < 2) return;
    if (!newComboMinEnabled && !newComboMaxEnabled) return;
    const minVal = newComboMinEnabled ? parseFloat(newComboMin) / 100 : null;
    const maxVal = newComboMaxEnabled ? parseFloat(newComboMax) / 100 : null;
    if (minVal !== null && isNaN(minVal)) return;
    if (maxVal !== null && isNaN(maxVal)) return;
    if (minVal !== null && maxVal !== null && minVal > maxVal) return;
    const newRule: CombinationRange = {
      id: crypto.randomUUID(),
      tickers: [...newComboTickers],
      min: minVal,
      max: maxVal,
    };
    setAllCombos((prev) => ({
      ...prev,
      [activeProfile]: [...(prev[activeProfile] ?? []), newRule],
    }));
    setNewComboTickers([]);
    setNewComboMinEnabled(true);
    setNewComboMaxEnabled(true);
    setNewComboMin("40");
    setNewComboMax("60");
    setM2Saved(false);
  };

  const removeCombo = (id: string) => {
    setAllCombos((prev) => ({
      ...prev,
      [activeProfile]: (prev[activeProfile] ?? []).filter((r) => r.id !== id),
    }));
    setM2Saved(false);
  };

  const toggleNewComboTicker = (ticker: string) => {
    setNewComboTickers((prev) =>
      prev.includes(ticker) ? prev.filter((t) => t !== ticker) : [...prev, ticker]
    );
  };

  const { mutate: saveM2, isPending: savingM2 } = useMutation({
    mutationFn: () => saveCombinationRanges(activeProfile, combosForProfile),
    onSuccess: () => setM2Saved(true),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Optimization</h1>
        {profile && (
          <span
            className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold"
            style={{ color: PROFILE_COLORS[profile as ProfileKey], background: profile === "conservative" ? "#eff6ff" : profile === "base" ? "#f0fdf4" : "#fef2f2" }}
          >
            Profile: {PROFILE_LABELS[profile as ProfileKey]}
          </span>
        )}
        <span className="text-bloomberg-muted text-[10px]">{period}</span>
        {pendingFrontier && (
          <span className="ml-auto text-bloomberg-muted text-[10px] animate-pulse">Computing optimal weights…</span>
        )}
      </div>

      {/* ── Motor 1 — Floor & Cap por Ticker ─────────────────────────────── */}
      <div className="bbg-card">
        <p className="bbg-header" style={{ color: "#f3a712" }}>
          Engine 1 — Floor &amp; Cap per Ticker
        </p>
        <p className="text-bloomberg-muted text-[10px] mb-3">
          Define the minimum (floor) and maximum (cap) weight for each asset. Applied to the active profile.
        </p>

        <div className="mb-3">
          <span className="text-[10px] px-3 py-1 border" style={{ borderColor: PROFILE_COLORS[activeProfile], color: PROFILE_COLORS[activeProfile] }}>
            Active profile: {PROFILE_LABELS[activeProfile]}
          </span>
        </div>

        {rows.length === 0 ? (
          <p className="text-bloomberg-muted text-[10px]">No positions loaded.</p>
        ) : (
          <table className="bbg-table mb-3">
            <thead>
              <tr>
                <th>Ticker</th>
                <th className="text-right">Floor %</th>
                <th className="text-right">Cap %</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const fc = getFloorCap(r.ticker);
                return (
                  <tr key={r.ticker}>
                    <td className="text-bloomberg-gold">{r.ticker}</td>
                    <td className="text-right">
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={1}
                        value={Math.round((fc.floor ?? 0) * 100)}
                        onChange={(e) => setFloorCap(r.ticker, "floor", e.target.value)}
                        className="w-20 bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-0.5 text-xs text-right focus:outline-none focus:border-bloomberg-gold"
                      />
                    </td>
                    <td className="text-right">
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={1}
                        value={Math.round((fc.cap ?? 1) * 100)}
                        onChange={(e) => setFloorCap(r.ticker, "cap", e.target.value)}
                        className="w-20 bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-0.5 text-xs text-right focus:outline-none focus:border-bloomberg-gold"
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        <div className="flex items-center gap-3">
          <button
            onClick={() => saveM1()}
            disabled={savingM1}
            className="flex items-center gap-1 bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-5 py-1.5 hover:opacity-90 disabled:opacity-50"
          >
            <Save size={11} />
            {savingM1 ? "SAVING…" : "SAVE ENGINE 1"}
          </button>
          {m1Saved && <span className="text-green-600 text-[10px]">✓ Saved</span>}
          {m1Error && <span className="text-red-400 text-[10px]">✗ {m1Error}</span>}
        </div>
      </div>

      {/* ── Motor 2 — Rangos de Combinaciones ────────────────────────────── */}
      <div className="bbg-card">
        <p className="bbg-header" style={{ color: "#38b2ff" }}>
          Engine 2 — Combination Ranges
        </p>
        <p className="text-bloomberg-muted text-[10px] mb-3">
          Define weight-sum ranges for asset groups (e.g. VOO + VWCE between 40% and 58%). Applied to the active profile.
        </p>

        <div className="mb-3">
          <span className="text-[10px] px-3 py-1 border" style={{ borderColor: PROFILE_COLORS[activeProfile], color: PROFILE_COLORS[activeProfile] }}>
            Active profile: {PROFILE_LABELS[activeProfile]}
          </span>
        </div>

        {/* Existing rules */}
        {combosForProfile.length > 0 && (
          <div className="space-y-2 mb-3">
            {combosForProfile.map((rule) => (
              <div
                key={rule.id}
                className="flex items-center gap-3 px-3 py-2 border border-bloomberg-border text-xs"
              >
                <span className="text-bloomberg-gold font-mono">
                  {rule.tickers.join(" + ")}
                </span>
                <span className="text-bloomberg-muted text-[10px]">
                  {rule.min !== null && rule.max !== null
                    ? `≥ ${Math.round(rule.min * 100)}%  y  ≤ ${Math.round(rule.max * 100)}%`
                    : rule.min !== null
                    ? `≥ ${Math.round(rule.min * 100)}%`
                    : `≤ ${Math.round((rule.max ?? 1) * 100)}%`}
                </span>
                <button
                  onClick={() => removeCombo(rule.id)}
                  className="ml-auto text-bloomberg-muted hover:text-bloomberg-red"
                >
                  <Trash2 size={11} />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Add new rule */}
        <div className="border border-bloomberg-border p-3 mb-3 space-y-3">
          <p className="text-bloomberg-muted text-[10px] uppercase">New rule</p>

          {/* Ticker selector */}
          <div>
            <p className="text-bloomberg-muted text-[10px] mb-1">Assets (select ≥ 2):</p>
            <div className="flex flex-wrap gap-1">
              {rows.map((r) => (
                <button
                  key={r.ticker}
                  onClick={() => toggleNewComboTicker(r.ticker)}
                  className="text-[10px] px-2 py-0.5 border transition-colors"
                  style={
                    newComboTickers.includes(r.ticker)
                      ? { borderColor: "#38b2ff", color: "#38b2ff" }
                      : { borderColor: "#334155", color: "#64748b" }
                  }
                >
                  {r.ticker}
                </button>
              ))}
            </div>
            {newComboTickers.length >= 2 && (
              <p className="text-[#38b2ff] text-[10px] mt-1">
                {newComboTickers.join(" + ")}
              </p>
            )}
          </div>

          {/* Bounds */}
          <div className="flex flex-wrap items-end gap-4">
            {/* Min (≥) */}
            <div className="space-y-1">
              <label className="flex items-center gap-1.5 text-bloomberg-muted text-[10px] cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={newComboMinEnabled}
                  onChange={(e) => setNewComboMinEnabled(e.target.checked)}
                  className="accent-[#38b2ff]"
                />
                <span className="text-[#38b2ff] font-bold">≥</span> Minimum %
              </label>
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={newComboMin}
                disabled={!newComboMinEnabled}
                onChange={(e) => setNewComboMin(e.target.value)}
                className="w-20 bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs focus:outline-none focus:border-bloomberg-gold disabled:opacity-30"
              />
            </div>

            {/* Max (≤) */}
            <div className="space-y-1">
              <label className="flex items-center gap-1.5 text-bloomberg-muted text-[10px] cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={newComboMaxEnabled}
                  onChange={(e) => setNewComboMaxEnabled(e.target.checked)}
                  className="accent-[#38b2ff]"
                />
                <span className="text-[#38b2ff] font-bold">≤</span> Maximum %
              </label>
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={newComboMax}
                disabled={!newComboMaxEnabled}
                onChange={(e) => setNewComboMax(e.target.value)}
                className="w-20 bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs focus:outline-none focus:border-bloomberg-gold disabled:opacity-30"
              />
            </div>

            <button
              onClick={addCombo}
              disabled={newComboTickers.length < 2 || (!newComboMinEnabled && !newComboMaxEnabled)}
              className="flex items-center gap-1 border border-[#38b2ff] text-[#38b2ff] text-[10px] px-3 py-1.5 hover:bg-[#38b2ff] hover:text-bloomberg-bg disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Plus size={11} /> Add
            </button>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => saveM2()}
            disabled={savingM2}
            className="flex items-center gap-1 bg-[#38b2ff] text-bloomberg-bg text-xs font-bold px-5 py-1.5 hover:opacity-90 disabled:opacity-50"
          >
            <Save size={11} />
            {savingM2 ? "SAVING…" : "SAVE ENGINE 2"}
          </button>
          {m2Saved && <span className="text-green-600 text-[10px]">✓ Saved</span>}
        </div>
      </div>

      {pendingFrontier && !result && (
        <div className="bbg-card text-center text-bloomberg-muted text-xs py-8">Computing efficient frontier…</div>
      )}

      {result && (
        <>
          {/* Efficient Frontier */}
          <div className="bbg-card">
            <p className="bbg-header">Efficient Frontier ({result.frontier.length.toLocaleString()} portfolios)</p>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-3">
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
                <p className="text-bloomberg-muted text-[10px]">Max Return</p>
                <p className="text-[#ff4b6e] text-xs font-bold">
                  Sharpe {result.max_return.sharpe.toFixed(3)} · Ret {fmtPct(result.max_return.ret)} · Vol {fmtPct(result.max_return.vol)}
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
              {profileData?.profiles?.[profile]?.metrics && (
                <div>
                  <p className="text-[10px]" style={{ color: PROFILE_COLORS[profile as ProfileKey] }}>
                    {PROFILE_LABELS[profile as ProfileKey]}
                  </p>
                  <p className="text-xs font-bold" style={{ color: PROFILE_COLORS[profile as ProfileKey] }}>
                    Sharpe {profileData.profiles[profile].metrics.sharpe?.toFixed(3) ?? "—"} · Ret {fmtPct(profileData.profiles[profile].metrics.ann_return)} · Vol {fmtPct(profileData.profiles[profile].metrics.ann_vol)}
                  </p>
                </div>
              )}
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
                <ReferenceDot x={result.max_return.vol} y={result.max_return.ret} r={7}
                  fill={COLORS.maxReturn} stroke="#fff"
                  label={{ value: "★ Max Return", position: "top", fontSize: 9, fill: COLORS.maxReturn }} />
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
                    fill={PROFILE_COLORS[profile as ProfileKey] ?? "#888"}
                    stroke="#fff"
                    strokeWidth={2}
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
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
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
              label="Max Return"
              color={COLORS.maxReturn}
              weights={result.max_return.weights}
              shares={computeShares(result.max_return.weights, rows, totalValue)}
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

        <div className="flex items-center gap-3">
          <button onClick={() => runBL()} disabled={pendingBL}
            className="bg-[#c084fc] text-bloomberg-bg text-xs font-bold px-6 py-1.5 hover:opacity-90 disabled:opacity-50">
            {pendingBL ? "COMPUTING…" : "RUN BLACK-LITTERMAN"}
          </button>
          <button
            onClick={saveBlViews}
            disabled={blViews.length === 0}
            className="flex items-center gap-1 border border-[#c084fc] text-[#c084fc] text-[10px] px-4 py-1.5 hover:bg-[#c084fc] hover:text-bloomberg-bg disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Save size={11} /> SAVE VIEWS
          </button>
          {blViewsSaved && <span className="text-green-600 text-[10px]">✓ Views saved</span>}
        </div>

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
