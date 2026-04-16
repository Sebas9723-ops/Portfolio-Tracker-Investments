"use client";
import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchSettings, updateSettings } from "@/lib/api/settings";
import { useSettingsStore } from "@/lib/store/settingsStore";
import { useProfileStore, type InvestorProfile } from "@/lib/store/profileStore";
import type { UserSettings } from "@/lib/types";

const PROFILES_LABELS: Record<string, string> = { conservative: "Conservative", base: "Base", aggressive: "Aggressive" };
const PROFILE_COLORS: Record<string, string> = { conservative: "#2563eb", base: "#16a34a", aggressive: "#dc2626" };
const OPT_PERIODS = ["1y", "2y", "3y", "5y", "10y", "15y"];

const CURRENCIES = [
  { code: "USD", label: "US Dollar" },
  { code: "EUR", label: "Euro" },
  { code: "CHF", label: "Swiss Franc" },
  { code: "AUD", label: "Australian Dollar" },
  { code: "COP", label: "Colombian Peso" },
];
const BENCHMARKS = ["VOO", "VWCE.DE", "IWDA.AS", "SPY", "QQQ", "IWM", "VTI"];
const TC_MODELS = ["broker", "etoro", "degiro", "ib"];

export default function SettingsPage() {
  const qc = useQueryClient();
  const { data: remote } = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });
  const setLocal = useSettingsStore((s) => s.setSettings);
  const setProfile = useProfileStore((s) => s.setProfile);
  const [form, setForm] = useState<UserSettings | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => { if (remote) setForm(remote); }, [remote]);

  const VALID_PROFILES = new Set(["conservative", "base", "aggressive"]);

  const { mutate, isPending } = useMutation({
    mutationFn: (data: UserSettings) => updateSettings(data),
    onSuccess: (data) => {
      setLocal(data);
      // Sync profileStore so all pages reflect the new profile immediately
      if (data.investor_profile && VALID_PROFILES.has(data.investor_profile)) {
        setProfile(data.investor_profile as InvestorProfile);
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
      // Invalidate all queries so every page re-fetches with the new settings
      qc.invalidateQueries();
    },
  });

  if (!form) return <div className="text-bloomberg-muted text-xs p-4">Loading…</div>;

  const set = (key: keyof UserSettings, val: unknown) =>
    setForm((f) => f ? { ...f, [key]: val } : f);

  const field = (label: string, key: keyof UserSettings, type: "text" | "number" = "text", options?: string[]) => (
    <div key={key}>
      <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">{label}</label>
      {options ? (
        <select value={String(form[key])} onChange={(e) => set(key, e.target.value)}
          className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold">
          {options.map((o) => <option key={o}>{o}</option>)}
        </select>
      ) : (
        <input type={type} value={String(form[key])}
          onChange={(e) => set(key, type === "number" ? parseFloat(e.target.value) : e.target.value)}
          className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold"
          step="any"
        />
      )}
    </div>
  );

  return (
    <div className="space-y-4 max-w-2xl">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Settings</h1>

      {/* ── Currency selector ─────────────────────────────────────────────── */}
      <div className="bbg-card">
        <p className="bbg-header">Portfolio Base Currency</p>
        <p className="text-bloomberg-muted text-[10px] mb-3">
          All portfolio values, analytics and rebalancing are displayed in this currency.
          Changes take effect immediately after saving.
        </p>
        <div className="flex flex-wrap gap-2">
          {CURRENCIES.map(({ code, label }) => (
            <button
              key={code}
              onClick={() => set("base_currency", code)}
              className="flex flex-col items-center px-4 py-2 border transition-all text-xs"
              style={
                form.base_currency === code
                  ? { borderColor: "#f3a712", color: "#f3a712", background: "rgba(243,167,18,0.08)" }
                  : { borderColor: "#334155", color: "#64748b" }
              }
            >
              <span className="font-bold text-sm">{code}</span>
              <span className="text-[9px] mt-0.5 opacity-70">{label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* ── General settings ──────────────────────────────────────────────── */}
      <div className="bbg-card space-y-4">
        <p className="bbg-header">Portfolio Settings</p>
        <div className="grid grid-cols-2 gap-4">
          {field("Preferred Benchmark", "preferred_benchmark", "text", BENCHMARKS)}
          {field("Broker / TC Model", "tc_model", "text", TC_MODELS)}
          {field("Investor Profile", "investor_profile", "text", ["conservative", "base", "aggressive"])}
        </div>
      </div>

      <div className="bbg-card space-y-4">
        <p className="bbg-header">Risk Parameters</p>
        <div className="grid grid-cols-2 gap-4">
          {field("Risk-Free Rate (decimal)", "risk_free_rate", "number")}
          {field("Rolling Window (days)", "rolling_window", "number")}
          {field("Rebalancing Threshold", "rebalancing_threshold", "number")}
          {field("Max Single Asset Weight", "max_single_asset", "number")}
          {field("Min Bonds Weight", "min_bonds", "number")}
          {field("Min Gold Weight", "min_gold", "number")}
        </div>
      </div>

      {/* ── Optimization Period per Profile ──────────────────────────────── */}
      <div className="bbg-card space-y-4">
        <p className="bbg-header">Optimization Period</p>
        <p className="text-bloomberg-muted text-[10px]">
          Historical data window used to compute the efficient frontier. Saved per profile.
        </p>
        {(["conservative", "base", "aggressive"] as const).map((p) => {
          const current = (form.optimization_periods ?? {})[p] ?? "2y";
          return (
            <div key={p}>
              <label className="block text-[10px] uppercase tracking-widest mb-2" style={{ color: PROFILE_COLORS[p] }}>
                {PROFILES_LABELS[p]}
              </label>
              <div className="flex flex-wrap gap-1.5">
                {OPT_PERIODS.map((opt) => (
                  <button
                    key={opt}
                    onClick={() => set("optimization_periods", { ...(form.optimization_periods ?? {}), [p]: opt })}
                    className="px-3 py-1 text-[10px] border transition-colors"
                    style={
                      current === opt
                        ? { borderColor: PROFILE_COLORS[p], color: PROFILE_COLORS[p], background: `${PROFILE_COLORS[p]}18` }
                        : { borderColor: "#334155", color: "#64748b" }
                    }
                  >
                    {opt}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-4">
        <button
          onClick={() => mutate(form)}
          disabled={isPending}
          className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-6 py-2 hover:opacity-90 disabled:opacity-50"
        >
          {isPending ? "SAVING…" : "SAVE SETTINGS"}
        </button>
        {saved && (
          <span className="text-green-600 text-xs">
            ✓ Saved — settings updated successfully
          </span>
        )}
      </div>
    </div>
  );
}
