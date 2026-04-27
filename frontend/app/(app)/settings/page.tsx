"use client";
import { useEffect, useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchSettings, updateSettings, fetchAlerts, createAlert, deleteAlert } from "@/lib/api/settings";
import type { Alert } from "@/lib/api/settings";
import { useSettingsStore } from "@/lib/store/settingsStore";
import { useProfileStore, type InvestorProfile } from "@/lib/store/profileStore";
import { Trash2, Bell, BellOff } from "lucide-react";
import type { UserSettings } from "@/lib/types";
import { fetchDCASchedule, upsertDCASchedule, deleteDCASchedule, runDCANow } from "@/lib/api/dca";
import type { DCASchedule } from "@/lib/api/dca";
import { importIBKRCsv, importXTBXlsx } from "@/lib/api/import";

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

const ALERT_INIT = { ticker: "", alert_type: "above" as "above" | "below", threshold: "" };

export default function SettingsPage() {
  const qc = useQueryClient();
  const { data: remote } = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });
  const { data: alerts } = useQuery({ queryKey: ["alerts"], queryFn: fetchAlerts, staleTime: 60 * 1000 });
  const setLocal = useSettingsStore((s) => s.setSettings);
  const setProfile = useProfileStore((s) => s.setProfile);
  const [form, setForm] = useState<UserSettings | null>(null);
  const [saved, setSaved] = useState(false);
  const [alertForm, setAlertForm] = useState(ALERT_INIT);
  const [showAlertForm, setShowAlertForm] = useState(false);

  // DCA
  const [dcaForm, setDcaForm] = useState<{ amount: string; day_of_month: string; profile: string; time_horizon: string; tc_model: string; active: boolean }>({
    amount: "", day_of_month: "1", profile: "base", time_horizon: "long", tc_model: "broker", active: true,
  });
  const [dcaSaved, setDcaSaved] = useState(false);
  const [dcaRunning, setDcaRunning] = useState(false);
  const [ibkrFile, setIbkrFile] = useState<File | null>(null);
  const [ibkrResult, setIbkrResult] = useState<{ imported: number; skipped: number; errors: string[]; tickers: string[] } | null>(null);
  const [ibkrLoading, setIbkrLoading] = useState(false);
  const [xtbFile, setXtbFile] = useState<File | null>(null);
  const [xtbResult, setXtbResult] = useState<{ imported: number; skipped: number; errors: string[]; tickers: string[]; deposits_usd: number } | null>(null);
  const [xtbLoading, setXtbLoading] = useState(false);
  const xtbFileRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data: dcaSchedule } = useQuery({ queryKey: ["dca-schedule"], queryFn: fetchDCASchedule, staleTime: 60_000 });

  const saveDcaMut = useMutation({
    mutationFn: () => upsertDCASchedule({
      amount: Number(dcaForm.amount),
      day_of_month: Number(dcaForm.day_of_month),
      profile: dcaForm.profile,
      time_horizon: dcaForm.time_horizon,
      tc_model: dcaForm.tc_model,
      active: dcaForm.active,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["dca-schedule"] }); setDcaSaved(true); setTimeout(() => setDcaSaved(false), 2500); },
  });

  const deleteDcaMut = useMutation({
    mutationFn: deleteDCASchedule,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dca-schedule"] }),
  });

  const createAlertMut = useMutation({
    mutationFn: (data: { ticker: string; alert_type: string; threshold: number }) => createAlert(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["alerts"] }); setAlertForm(ALERT_INIT); setShowAlertForm(false); },
  });

  const deleteAlertMut = useMutation({
    mutationFn: (id: string) => deleteAlert(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });

  useEffect(() => { if (remote) setForm(remote); }, [remote]);

  useEffect(() => {
    if (dcaSchedule && dcaSchedule.amount) {
      setDcaForm({
        amount: String(dcaSchedule.amount),
        day_of_month: String(dcaSchedule.day_of_month),
        profile: dcaSchedule.profile,
        time_horizon: dcaSchedule.time_horizon,
        tc_model: dcaSchedule.tc_model,
        active: dcaSchedule.active,
      });
    }
  }, [dcaSchedule]);

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
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {field("Preferred Benchmark", "preferred_benchmark", "text", BENCHMARKS)}
          {field("Broker / TC Model", "tc_model", "text", TC_MODELS)}
          {field("Investor Profile", "investor_profile", "text", ["conservative", "base", "aggressive"])}
        </div>
      </div>

      <div className="bbg-card space-y-4">
        <p className="bbg-header">Risk Parameters</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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

      {/* ── Price Alerts ─────────────────────────────────────────────────── */}
      <div className="bbg-card space-y-3">
        <div className="flex items-center justify-between">
          <p className="bbg-header mb-0">Price Alerts</p>
          <button
            onClick={() => setShowAlertForm((v) => !v)}
            className="text-[10px] text-bloomberg-muted border border-bloomberg-border px-3 py-1 hover:text-bloomberg-gold hover:border-bloomberg-gold"
          >
            + New Alert
          </button>
        </div>

        {showAlertForm && (
          <div className="grid grid-cols-3 gap-2 border border-bloomberg-border p-3">
            <div>
              <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Ticker</label>
              <input
                className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold uppercase"
                placeholder="e.g. VOO"
                value={alertForm.ticker}
                onChange={(e) => setAlertForm((f) => ({ ...f, ticker: e.target.value.toUpperCase() }))}
              />
            </div>
            <div>
              <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Type</label>
              <select
                className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold"
                value={alertForm.alert_type}
                onChange={(e) => setAlertForm((f) => ({ ...f, alert_type: e.target.value as "above" | "below" }))}
              >
                <option value="above">Price above</option>
                <option value="below">Price below</option>
              </select>
            </div>
            <div>
              <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Threshold</label>
              <input
                type="number"
                step="any"
                className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold"
                placeholder="e.g. 500"
                value={alertForm.threshold}
                onChange={(e) => setAlertForm((f) => ({ ...f, threshold: e.target.value }))}
              />
            </div>
            <div className="col-span-3 flex gap-2">
              <button
                onClick={() => createAlertMut.mutate({ ticker: alertForm.ticker, alert_type: alertForm.alert_type, threshold: parseFloat(alertForm.threshold) })}
                disabled={!alertForm.ticker || !alertForm.threshold || createAlertMut.isPending}
                className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-4 py-1 disabled:opacity-50"
              >
                {createAlertMut.isPending ? "SAVING…" : "SAVE"}
              </button>
              <button onClick={() => setShowAlertForm(false)} className="text-bloomberg-muted text-xs px-3 py-1 border border-bloomberg-border">
                CANCEL
              </button>
            </div>
          </div>
        )}

        {alerts && alerts.length > 0 ? (
          <div className="space-y-1">
            {alerts.map((alert: Alert) => (
              <div key={alert.id} className={`flex items-center justify-between px-3 py-2 border ${alert.triggered ? "border-bloomberg-gold bg-bloomberg-gold/5" : "border-bloomberg-border"}`}>
                <div className="flex items-center gap-3">
                  {alert.triggered
                    ? <Bell size={12} className="text-bloomberg-gold" />
                    : <BellOff size={12} className="text-bloomberg-muted" />
                  }
                  <span className="text-bloomberg-gold text-xs font-bold">{alert.ticker}</span>
                  <span className="text-bloomberg-muted text-[10px]">
                    {alert.alert_type === "above" ? "≥" : "≤"} {alert.threshold.toLocaleString()}
                  </span>
                  {alert.current_price != null && (
                    <span className="text-bloomberg-text text-[10px]">
                      now {alert.current_price.toFixed(2)}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {alert.triggered && (
                    <span className="text-bloomberg-gold text-[9px] font-bold uppercase tracking-widest">TRIGGERED</span>
                  )}
                  <button onClick={() => deleteAlertMut.mutate(alert.id)} className="text-bloomberg-muted hover:text-bloomberg-red">
                    <Trash2 size={11} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-bloomberg-muted text-[10px]">No alerts configured.</p>
        )}
      </div>

      {/* ── Macro Overlay ── */}
      <div className="bbg-card">
        <p className="bbg-header">Macro Overlay (μ Multipliers)</p>
        <p className="text-bloomberg-muted text-[10px] mb-3">
          Per-ticker expected-return multiplier applied in the contribution engine. Range: 0.5×–2.0×.
          Use to express tactical views (e.g., NVDA=1.2 for bullish conviction).
        </p>
        <div className="space-y-2">
          {Object.entries(form?.macro_overlay || {}).map(([ticker, mult]) => (
            <div key={ticker} className="flex items-center gap-2">
              <span className="text-bloomberg-gold text-xs w-24 font-bold">{ticker}</span>
              <input
                type="number" min={0.5} max={2.0} step={0.05}
                value={mult}
                onChange={(e) => set("macro_overlay", { ...((form?.macro_overlay) || {}), [ticker]: parseFloat(e.target.value) || 1.0 })}
                className="w-20 bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
              />
              <span className="text-bloomberg-muted text-[10px]">×</span>
              <button
                onClick={() => {
                  const o = { ...(form?.macro_overlay || {}) };
                  delete o[ticker];
                  set("macro_overlay", o);
                }}
                className="text-red-400 text-[10px] hover:text-red-300"
              >✕</button>
            </div>
          ))}
          <div className="flex items-center gap-2 mt-2">
            <input
              id="macro-ticker-input"
              type="text"
              placeholder="TICKER"
              className="w-24 bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs focus:outline-none focus:border-bloomberg-gold uppercase"
            />
            <button
              onClick={() => {
                const inp = document.getElementById("macro-ticker-input") as HTMLInputElement;
                const t = inp?.value?.toUpperCase().trim();
                if (t) {
                  set("macro_overlay", { ...(form?.macro_overlay || {}), [t]: 1.0 });
                  if (inp) inp.value = "";
                }
              }}
              className="text-bloomberg-gold text-[10px] border border-bloomberg-gold px-2 py-1 hover:bg-bloomberg-gold hover:text-bloomberg-bg"
            >+ Add</button>
          </div>
        </div>
      </div>

      {/* ── Drift Alerts ── */}
      <div className="bbg-card">
        <p className="bbg-header">Drift Alerts (Email)</p>
        <p className="text-bloomberg-muted text-[10px] mb-3">
          Receive an email when any position drifts beyond the alert threshold vs optimal weights. Runs daily at 17:00 Bogota.
        </p>
        <div className="space-y-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={form?.drift_alerts_enabled ?? false}
              onChange={(e) => set("drift_alerts_enabled", e.target.checked)}
              className="accent-bloomberg-gold"
            />
            <span className="text-bloomberg-text text-xs">Enable drift alerts</span>
          </label>
          {form?.drift_alerts_enabled && (
            <>
              <div>
                <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">Alert Email</label>
                <input
                  type="email"
                  value={form?.drift_alert_email ?? ""}
                  onChange={(e) => set("drift_alert_email", e.target.value)}
                  placeholder="your@email.com"
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold"
                />
              </div>
              <div>
                <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">Alert Threshold (%)</label>
                <input
                  type="number" min={1} max={50} step={1}
                  value={((form?.drift_alert_threshold ?? 0.08) * 100).toFixed(0)}
                  onChange={(e) => set("drift_alert_threshold", parseFloat(e.target.value) / 100)}
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold"
                />
                <p className="text-bloomberg-muted text-[9px] mt-1">Alert fires when drift exceeds this % (recommended: 8%)</p>
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── DCA Scheduler ── */}
      <div className="bbg-card">
        <div className="flex items-center justify-between mb-3">
          <p className="bbg-header">DCA Scheduler</p>
          {dcaSchedule?.last_run_at && (
            <span className="text-bloomberg-muted text-[9px]">Last run: {dcaSchedule.last_run_at.slice(0, 16).replace("T", " ")}</span>
          )}
        </div>
        <p className="text-bloomberg-muted text-[10px] mb-3">
          Automatically runs the Contribution Planner on a set day each month using your saved profile and settings.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">Amount (USD)</label>
            <input type="number" min={1} value={dcaForm.amount} onChange={(e) => setDcaForm((f) => ({ ...f, amount: e.target.value }))}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold" />
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">Day of Month</label>
            <input type="number" min={1} max={28} value={dcaForm.day_of_month} onChange={(e) => setDcaForm((f) => ({ ...f, day_of_month: e.target.value }))}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold" />
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">Profile</label>
            <select value={dcaForm.profile} onChange={(e) => setDcaForm((f) => ({ ...f, profile: e.target.value }))}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold">
              {["conservative", "base", "aggressive"].map((p) => <option key={p}>{p}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">Horizon</label>
            <select value={dcaForm.time_horizon} onChange={(e) => setDcaForm((f) => ({ ...f, time_horizon: e.target.value }))}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold">
              {["short", "medium", "long"].map((h) => <option key={h}>{h}</option>)}
            </select>
          </div>
        </div>
        <label className="flex items-center gap-2 mt-3 cursor-pointer">
          <input type="checkbox" checked={dcaForm.active} onChange={(e) => setDcaForm((f) => ({ ...f, active: e.target.checked }))} className="accent-bloomberg-gold" />
          <span className="text-bloomberg-text text-xs">Active</span>
        </label>
        <div className="flex gap-2 mt-3 flex-wrap">
          <button
            onClick={() => saveDcaMut.mutate()}
            disabled={saveDcaMut.isPending || !dcaForm.amount}
            className="bg-bloomberg-gold text-bloomberg-bg text-[10px] font-bold px-3 py-1.5 hover:opacity-90 disabled:opacity-50 uppercase tracking-wider"
          >
            {saveDcaMut.isPending ? "Saving…" : dcaSaved ? "Saved ✓" : "Save DCA Schedule"}
          </button>
          {dcaSchedule?.id && (
            <>
              <button
                onClick={async () => {
                  setDcaRunning(true);
                  try { await runDCANow(); alert("DCA run complete!"); } catch (e) { alert("DCA run failed: " + String(e)); }
                  setDcaRunning(false);
                }}
                disabled={dcaRunning}
                className="border border-bloomberg-gold text-bloomberg-gold text-[10px] font-bold px-3 py-1.5 hover:bg-bloomberg-gold hover:text-bloomberg-bg disabled:opacity-50 uppercase tracking-wider"
              >
                {dcaRunning ? "Running…" : "Run Now"}
              </button>
              <button
                onClick={() => { if (confirm("Delete DCA schedule?")) deleteDcaMut.mutate(); }}
                className="border border-red-500 text-red-400 text-[10px] font-bold px-3 py-1.5 hover:bg-red-500 hover:text-white uppercase tracking-wider"
              >Delete</button>
            </>
          )}
        </div>
      </div>

      {/* ── XTB Import ── */}
      <div className="bbg-card">
        <p className="bbg-header">Import Transactions (XTB)</p>
        <p className="text-bloomberg-muted text-[10px] mb-3">
          Sube tu reporte de XTB (Cash Operations .xlsx) para importar compras y ventas automáticamente.
          En XTB: Mi Cuenta → Historial → Cash Operations → Exportar Excel.
        </p>
        <div className="flex items-center gap-3 flex-wrap">
          <input
            ref={xtbFileRef}
            type="file"
            accept=".xlsx"
            onChange={(e) => setXtbFile(e.target.files?.[0] || null)}
            className="text-bloomberg-muted text-[10px] file:bg-bloomberg-border file:text-bloomberg-text file:border-0 file:px-2 file:py-1 file:text-[10px] file:mr-2 file:cursor-pointer"
          />
          <button
            onClick={async () => {
              if (!xtbFile) return;
              setXtbLoading(true);
              setXtbResult(null);
              try {
                const result = await importXTBXlsx(xtbFile);
                setXtbResult(result);
                qc.invalidateQueries({ queryKey: ["portfolio"] });
                qc.invalidateQueries({ queryKey: ["transactions"] });
                qc.invalidateQueries({ queryKey: ["portfolio-history"] });
              } catch (e) {
                setXtbResult({ imported: 0, skipped: 0, errors: [String(e)], tickers: [], deposits_usd: 0 });
              }
              setXtbLoading(false);
            }}
            disabled={!xtbFile || xtbLoading}
            className="bg-bloomberg-gold text-bloomberg-bg text-[10px] font-bold px-3 py-1.5 hover:opacity-90 disabled:opacity-50 uppercase tracking-wider"
          >
            {xtbLoading ? "Importando…" : "Import XTB"}
          </button>
        </div>
        {xtbResult && (
          <div className={`mt-3 p-2 text-[10px] border ${xtbResult.imported > 0 ? "border-green-500/30 bg-green-500/5" : "border-red-500/30 bg-red-500/5"}`}>
            <p className="font-bold text-bloomberg-text">
              {xtbResult.imported} transacciones importadas · {xtbResult.skipped} omitidas
              {xtbResult.deposits_usd > 0 && ` · Depósitos detectados: $${xtbResult.deposits_usd.toFixed(2)}`}
            </p>
            {xtbResult.tickers.length > 0 && (
              <p className="text-bloomberg-muted mt-0.5">Tickers: {xtbResult.tickers.join(", ")}</p>
            )}
            {xtbResult.errors.length > 0 && (
              <ul className="mt-1 text-red-400">
                {xtbResult.errors.map((e, i) => <li key={i}>⚠ {e}</li>)}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* ── IBKR Import ── */}
      <div className="bbg-card">
        <p className="bbg-header">Import Transactions (IBKR Flex Query)</p>
        <p className="text-bloomberg-muted text-[10px] mb-3">
          Upload an Interactive Brokers Flex Query CSV export to import trades automatically.
          Export from IBKR: Reports → Flex Queries → Trade Confirmation (CSV format).
        </p>
        <div className="flex items-center gap-3 flex-wrap">
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.txt"
            onChange={(e) => setIbkrFile(e.target.files?.[0] || null)}
            className="text-bloomberg-muted text-[10px] file:bg-bloomberg-border file:text-bloomberg-text file:border-0 file:px-2 file:py-1 file:text-[10px] file:mr-2 file:cursor-pointer"
          />
          <button
            onClick={async () => {
              if (!ibkrFile) return;
              setIbkrLoading(true);
              setIbkrResult(null);
              try {
                const result = await importIBKRCsv(ibkrFile);
                setIbkrResult(result);
                qc.invalidateQueries({ queryKey: ["portfolio"] });
                qc.invalidateQueries({ queryKey: ["transactions"] });
              } catch (e) {
                setIbkrResult({ imported: 0, skipped: 0, errors: [String(e)], tickers: [] });
              }
              setIbkrLoading(false);
            }}
            disabled={!ibkrFile || ibkrLoading}
            className="bg-bloomberg-gold text-bloomberg-bg text-[10px] font-bold px-3 py-1.5 hover:opacity-90 disabled:opacity-50 uppercase tracking-wider"
          >
            {ibkrLoading ? "Importing…" : "Import CSV"}
          </button>
        </div>
        {ibkrResult && (
          <div className={`mt-3 p-2 text-[10px] border ${ibkrResult.imported > 0 ? "border-green-500/30 bg-green-500/5" : "border-red-500/30 bg-red-500/5"}`}>
            <p className="font-bold text-bloomberg-text">
              {ibkrResult.imported} trades imported · {ibkrResult.skipped} skipped
              {ibkrResult.tickers.length > 0 && ` · Tickers: ${ibkrResult.tickers.join(", ")}`}
            </p>
            {ibkrResult.errors.length > 0 && (
              <ul className="mt-1 text-red-400">
                {ibkrResult.errors.map((e, i) => <li key={i}>⚠ {e}</li>)}
              </ul>
            )}
          </div>
        )}
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
