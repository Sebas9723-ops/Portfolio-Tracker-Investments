"use client";
import { useEffect, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { fetchSettings, updateSettings } from "@/lib/api/settings";
import { useSettingsStore } from "@/lib/store/settingsStore";
import type { UserSettings } from "@/lib/types";

const CCY = ["USD", "EUR", "GBP", "COP", "CHF", "AUD"];
const BENCHMARKS = ["VOO", "IWDA.AS", "SPY", "QQQ", "IWM", "VTI"];
const TC_MODELS = ["broker", "etoro", "degiro", "ib"];

export default function SettingsPage() {
  const { data: remote } = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });
  const setLocal = useSettingsStore((s) => s.setSettings);
  const [form, setForm] = useState<UserSettings | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => { if (remote) setForm(remote); }, [remote]);

  const { mutate, isPending } = useMutation({
    mutationFn: (data: UserSettings) => updateSettings(data),
    onSuccess: (data) => { setLocal(data); setSaved(true); setTimeout(() => setSaved(false), 2000); },
  });

  if (!form) return <div className="text-bloomberg-muted text-xs p-4">Loading…</div>;

  const field = (label: string, key: keyof UserSettings, type: "text" | "number" = "text", options?: string[]) => (
    <div key={key}>
      <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">{label}</label>
      {options ? (
        <select value={String(form[key])} onChange={(e) => setForm((f) => f ? { ...f, [key]: e.target.value } : f)}
          className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold">
          {options.map((o) => <option key={o}>{o}</option>)}
        </select>
      ) : (
        <input type={type} value={String(form[key])}
          onChange={(e) => setForm((f) => f ? { ...f, [key]: type === "number" ? parseFloat(e.target.value) : e.target.value } : f)}
          className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold"
          step="any"
        />
      )}
    </div>
  );

  return (
    <div className="space-y-4 max-w-2xl">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Settings</h1>

      <div className="bbg-card space-y-4">
        <p className="bbg-header">Portfolio Settings</p>
        <div className="grid grid-cols-2 gap-4">
          {field("Base Currency", "base_currency", "text", CCY)}
          {field("Preferred Benchmark", "preferred_benchmark", "text", BENCHMARKS)}
          {field("Broker / TC Model", "tc_model", "text", TC_MODELS)}
          {field("Investor Profile", "investor_profile", "text", ["conservative", "balanced", "growth", "aggressive"])}
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

      <div className="flex items-center gap-4">
        <button
          onClick={() => mutate(form)}
          disabled={isPending}
          className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-6 py-2 hover:opacity-90 disabled:opacity-50"
        >
          {isPending ? "SAVING…" : "SAVE SETTINGS"}
        </button>
        {saved && <span className="text-bloomberg-green text-xs">✓ Saved</span>}
      </div>
    </div>
  );
}
