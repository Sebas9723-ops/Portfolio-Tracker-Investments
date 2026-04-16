"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchProfileOptimal, updateProfile } from "@/lib/api/profile";
import { useProfileStore, type InvestorProfile } from "@/lib/store/profileStore";
import { useSettingsStore } from "@/lib/store/settingsStore";
import { Shield, Target, TrendingUp, Check } from "lucide-react";

const PROFILES: {
  key: InvestorProfile;
  label: string;
  subtitle: string;
  icon: React.ElementType;
  color: string;
  bg: string;
}[] = [
  {
    key: "conservative",
    label: "Conservador",
    subtitle: "Máximo Sharpe Ratio",
    icon: Shield,
    color: "#2563eb",
    bg: "#eff6ff",
  },
  {
    key: "base",
    label: "Base",
    subtitle: "Retorno objetivo ajustable",
    icon: Target,
    color: "#16a34a",
    bg: "#f0fdf4",
  },
  {
    key: "aggressive",
    label: "Agresivo",
    subtitle: "Máximo Retorno",
    icon: TrendingUp,
    color: "#dc2626",
    bg: "#fef2f2",
  },
];

const LABELS: Record<InvestorProfile, string> = {
  conservative: "Conservador",
  base: "Base",
  aggressive: "Agresivo",
};

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bbg-card text-center">
      <div className="text-[11px] text-bloomberg-muted mb-1">{label}</div>
      <div className="text-xl font-bold text-bloomberg-text">{value}</div>
      {sub && <div className="text-[11px] text-bloomberg-muted mt-0.5">{sub}</div>}
    </div>
  );
}

function WeightBar({
  ticker,
  current,
  target,
}: {
  ticker: string;
  current: number;
  target: number;
}) {
  const diff = target - current;
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="w-14 text-bloomberg-muted shrink-0">{ticker}</span>
      <div className="flex-1 relative h-4 bg-bloomberg-bg rounded-full overflow-hidden">
        <div
          className="absolute left-0 top-0 h-full rounded-full bg-bloomberg-gold opacity-30"
          style={{ width: `${Math.min(current * 100, 100)}%` }}
        />
        <div
          className="absolute left-0 top-0 h-full rounded-full bg-bloomberg-gold"
          style={{ width: `${Math.min(target * 100, 100)}%`, opacity: 0.85 }}
        />
      </div>
      <span className="w-12 text-right text-bloomberg-text font-medium">
        {(target * 100).toFixed(1)}%
      </span>
      <span
        className={`w-14 text-right font-medium ${
          diff > 0.005 ? "text-green-600" : diff < -0.005 ? "text-red-500" : "text-bloomberg-muted"
        }`}
      >
        {diff >= 0 ? "+" : ""}
        {(diff * 100).toFixed(1)}%
      </span>
    </div>
  );
}

export default function ProfilePage() {
  const qc = useQueryClient();
  const { profile: localProfile, targetReturn, setProfile, setTargetReturn } = useProfileStore();
  const setSettings = useSettingsStore((s) => s.setSettings);
  const [targetReturnInput, setTargetReturnInput] = useState(String(Math.round(targetReturn * 100)));

  const { data, isLoading } = useQuery({
    queryKey: ["profile-optimal"],
    queryFn: () => fetchProfileOptimal("2y"),
    staleTime: 5 * 60 * 1000,
  });

  const mutation = useMutation({
    mutationFn: ({ profile, tr }: { profile: InvestorProfile; tr?: number }) =>
      updateProfile(profile, tr),
    onSuccess: (_, vars) => {
      setProfile(vars.profile);
      setSettings({ investor_profile: vars.profile });
      if (vars.tr !== undefined) setTargetReturn(vars.tr);
      qc.invalidateQueries();
    },
  });

  function handleProfileSelect(p: InvestorProfile) {
    const tr = p === "base" ? parseFloat(targetReturnInput) / 100 : undefined;
    mutation.mutate({ profile: p, tr });
  }

  function handleTargetReturnSave() {
    const tr = parseFloat(targetReturnInput) / 100;
    if (isNaN(tr) || tr <= 0 || tr > 1) return;
    setTargetReturn(tr);
    mutation.mutate({ profile: activeProfile as InvestorProfile, tr });
  }

  const activeProfile = data?.active_profile || localProfile;
  const activeData = data?.profiles?.[activeProfile as InvestorProfile];
  const currentData = data?.current;

  return (
    <div className="p-6 space-y-6 max-w-4xl">
      <div>
        <h1 className="text-lg font-bold text-bloomberg-text">Perfil de Inversionista</h1>
        <p className="text-xs text-bloomberg-muted mt-1">
          El perfil seleccionado define los pesos objetivo para rebalanceos y optimización.
        </p>
      </div>

      {/* Profile selector */}
      <div className="grid grid-cols-3 gap-4">
        {PROFILES.map((p) => {
          const isActive = activeProfile === p.key;
          const pd = data?.profiles?.[p.key];
          const Icon = p.icon;
          return (
            <button
              key={p.key}
              onClick={() => handleProfileSelect(p.key)}
              disabled={mutation.isPending}
              className={`bbg-card text-left transition-all border-2 ${
                isActive ? "border-[color:var(--accent)]" : "border-transparent hover:border-bloomberg-border"
              }`}
            >
              <div className="flex items-center justify-between mb-3">
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center"
                  style={{ background: p.bg }}
                >
                  <Icon size={16} style={{ color: p.color }} />
                </div>
                {isActive && (
                  <div className="w-5 h-5 rounded-full bg-bloomberg-text flex items-center justify-center">
                    <Check size={11} className="text-white" />
                  </div>
                )}
              </div>
              <div className="font-semibold text-bloomberg-text text-sm">{p.label}</div>
              <div className="text-[11px] text-bloomberg-muted">{p.subtitle}</div>
              {pd && (
                <div className="mt-3 pt-3 border-t border-bloomberg-border grid grid-cols-2 gap-1">
                  <div>
                    <div className="text-[10px] text-bloomberg-muted">Retorno</div>
                    <div className="text-xs font-semibold text-bloomberg-text">
                      {pd.metrics.ann_return?.toFixed(1)}%
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-bloomberg-muted">Sharpe</div>
                    <div className="text-xs font-semibold text-bloomberg-text">
                      {pd.metrics.sharpe?.toFixed(2)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-bloomberg-muted">Vol.</div>
                    <div className="text-xs font-semibold text-bloomberg-text">
                      {pd.metrics.ann_vol?.toFixed(1)}%
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-bloomberg-muted">Max DD</div>
                    <div className="text-xs font-semibold text-red-500">
                      {pd.metrics.max_drawdown?.toFixed(1)}%
                    </div>
                  </div>
                </div>
              )}
            </button>
          );
        })}
      </div>

      {/* Target return input (all profiles — used by Horizon projections) */}
      <div className="bbg-card flex items-center gap-4">
        <div>
          <div className="text-xs font-semibold text-bloomberg-text mb-0.5">Retorno Objetivo Anual</div>
          <div className="text-[11px] text-bloomberg-muted">
            {activeProfile === "base"
              ? "El optimizador minimiza la volatilidad alcanzando este retorno mínimo."
              : "Usado por el planificador de Horizon para proyecciones Monte Carlo."}
          </div>
        </div>
        <div className="flex items-center gap-2 ml-auto">
          <input
            type="number"
            min={1}
            max={100}
            step={1}
            value={targetReturnInput}
            onChange={(e) => setTargetReturnInput(e.target.value)}
            className="w-20 border border-bloomberg-border rounded-lg px-3 py-1.5 text-sm text-bloomberg-text text-right outline-none focus:border-bloomberg-gold"
          />
          <span className="text-sm text-bloomberg-muted">%</span>
          <button
            onClick={handleTargetReturnSave}
            disabled={mutation.isPending}
            className="px-3 py-1.5 text-xs font-semibold bg-bloomberg-text text-white rounded-lg hover:opacity-80 transition-opacity disabled:opacity-40"
          >
            Guardar
          </button>
        </div>
      </div>

      {/* Active profile detail */}
      {isLoading && (
        <div className="bbg-card text-center text-bloomberg-muted text-sm py-8">Calculando pesos óptimos…</div>
      )}

      {!isLoading && activeData && currentData && (
        <div className="grid grid-cols-4 gap-4">
          <MetricCard
            label="Retorno Anual"
            value={`${activeData.metrics.ann_return?.toFixed(1)}%`}
            sub={`Actual: ${currentData.metrics.ann_return?.toFixed(1)}%`}
          />
          <MetricCard
            label="Volatilidad"
            value={`${activeData.metrics.ann_vol?.toFixed(1)}%`}
            sub={`Actual: ${currentData.metrics.ann_vol?.toFixed(1)}%`}
          />
          <MetricCard
            label="Sharpe Ratio"
            value={activeData.metrics.sharpe?.toFixed(2) ?? "—"}
            sub={`Actual: ${currentData.metrics.sharpe?.toFixed(2)}`}
          />
          <MetricCard
            label="Max Drawdown"
            value={`${activeData.metrics.max_drawdown?.toFixed(1)}%`}
            sub={`Actual: ${currentData.metrics.max_drawdown?.toFixed(1)}%`}
          />
        </div>
      )}

      {/* Weight comparison table */}
      {!isLoading && activeData && currentData && (
        <div className="bbg-card">
          <div className="bbg-header">
            Pesos — {LABELS[activeProfile as InvestorProfile] ?? activeProfile} vs Actual
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-3 text-[10px] text-bloomberg-muted mb-3">
              <span className="w-14 shrink-0" />
              <span className="flex-1">
                <span className="inline-block w-3 h-3 rounded-full bg-bloomberg-gold opacity-30 mr-1" />
                Actual
                <span className="inline-block w-3 h-3 rounded-full bg-bloomberg-gold ml-3 mr-1 opacity-85" />
                Óptimo
              </span>
              <span className="w-12 text-right">Óptimo</span>
              <span className="w-14 text-right">Diferencia</span>
            </div>
            {Object.entries(activeData.weights)
              .sort((a, b) => b[1] - a[1])
              .map(([ticker, targetW]) => (
                <WeightBar
                  key={ticker}
                  ticker={ticker}
                  current={currentData.weights[ticker] ?? 0}
                  target={targetW}
                />
              ))}
          </div>
        </div>
      )}

      {/* Profile comparison table */}
      {!isLoading && data?.profiles && (
        <div className="bbg-card">
          <div className="bbg-header">Comparación de Perfiles</div>
          <table className="bbg-table">
            <thead>
              <tr>
                <th>Perfil</th>
                <th className="text-right">Retorno</th>
                <th className="text-right">Volatilidad</th>
                <th className="text-right">Sharpe</th>
                <th className="text-right">Max DD</th>
              </tr>
            </thead>
            <tbody>
              {(["conservative", "base", "aggressive"] as InvestorProfile[]).map((key) => {
                const pd = data.profiles[key];
                const isA = key === activeProfile;
                return (
                  <tr key={key} className={isA ? "bg-bloomberg-bg" : ""}>
                    <td className="font-medium">
                      {LABELS[key]}
                      {isA && (
                        <span className="ml-2 text-[10px] bg-bloomberg-text text-white px-1.5 py-0.5 rounded-full">
                          Activo
                        </span>
                      )}
                    </td>
                    <td className="text-right text-green-600 font-medium">
                      {pd?.metrics.ann_return?.toFixed(1)}%
                    </td>
                    <td className="text-right">{pd?.metrics.ann_vol?.toFixed(1)}%</td>
                    <td className="text-right font-medium">{pd?.metrics.sharpe?.toFixed(2)}</td>
                    <td className="text-right text-red-500">{pd?.metrics.max_drawdown?.toFixed(1)}%</td>
                  </tr>
                );
              })}
              {/* Current portfolio row */}
              {currentData && (
                <tr className="border-t-2 border-bloomberg-border">
                  <td className="font-medium text-bloomberg-muted">Portafolio Actual</td>
                  <td className="text-right text-green-600 font-medium">
                    {currentData.metrics.ann_return?.toFixed(1)}%
                  </td>
                  <td className="text-right">{currentData.metrics.ann_vol?.toFixed(1)}%</td>
                  <td className="text-right font-medium">{currentData.metrics.sharpe?.toFixed(2)}</td>
                  <td className="text-right text-red-500">
                    {currentData.metrics.max_drawdown?.toFixed(1)}%
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
