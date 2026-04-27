"use client";
import { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchPositions, upsertPosition, updatePosition, deletePosition, saveCapitalSnapshot, exportPositionsCsv, importPositionsCsv } from "@/lib/api/portfolio";
import { fetchTransactions, createTransaction, fetchCash, upsertCash, deleteCash } from "@/lib/api/transactions";
import { fmtCurrency, fmtDate } from "@/lib/formatters";
import { Pencil, Trash2, Plus, Check, X, AlertCircle } from "lucide-react";
import type { Position, TransactionAction, PortfolioSummary } from "@/lib/types";
import { useSettingsStore } from "@/lib/store/settingsStore";
import { updateSettings } from "@/lib/api/settings";
import { brokerReconcile } from "@/lib/api/import";
import type { BrokerReconcileResult } from "@/lib/api/import";

const CURRENCIES = ["USD", "EUR", "GBP", "COP", "CHF", "AUD"];
const MARKETS = ["US", "LSE", "XETRA", "EURONEXT", "TSX", "ASX"];

const today = () => new Date().toISOString().split("T")[0];
const initPositionForm = { ticker: "", name: "", shares: "", avg_cost_native: "", currency: "USD", date: today() };
const initCashForm = { currency: "USD", amount: "", account_name: "" };

type EditRow = { shares: string; avg_cost_native: string; name: string; currency: string };

export default function ManagePage() {
  const qc = useQueryClient();
  const cost_basis_usd = useSettingsStore((s) => s.cost_basis_usd);
  const setSettings = useSettingsStore((s) => s.setSettings);

  const { data: positions, isLoading: posLoading } = useQuery({
    queryKey: ["positions"],
    queryFn: fetchPositions,
  });

  const { data: transactions, isLoading: txLoading } = useQuery({
    queryKey: ["transactions"],
    queryFn: fetchTransactions,
  });

  const { data: cash, isLoading: cashLoading } = useQuery({
    queryKey: ["cash"],
    queryFn: fetchCash,
  });

  // Per-row edit state: ticker → { shares, avg_cost_native, name }
  const [editing, setEditing] = useState<Record<string, EditRow>>({});
  const [showPosForm, setShowPosForm] = useState(false);
  const [posForm, setPosForm] = useState(initPositionForm);

  // Cash form state
  const [showBrokerForm, setShowBrokerForm] = useState(false);
  const [showYieldForm, setShowYieldForm] = useState(false);
  const [brokerForm, setBrokerForm] = useState({ currency: "USD", amount: "" });
  const [yieldForm, setYieldForm] = useState(initCashForm);

  const [saveStatus, setSaveStatus] = useState<Record<string, "ok" | "err">>({});

  // Broker reconcile state (XTB)
  const [xtbFile, setXtbFile] = useState<File | null>(null);
  const [xtbResult, setXtbResult] = useState<BrokerReconcileResult | null>(null);
  const [xtbLoading, setXtbLoading] = useState(false);
  const xtbFileRef = useRef<HTMLInputElement>(null);

  // CSV import state
  const [csvImporting, setCsvImporting] = useState(false);
  const [csvResult, setCsvResult] = useState<{ imported: number; skipped: number; errors: { row: number; ticker?: string; error: string }[] } | null>(null);

  async function handleCsvImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setCsvImporting(true);
    setCsvResult(null);
    try {
      const result = await importPositionsCsv(file, "upsert");
      setCsvResult(result);
      if (result.imported > 0) {
        await saveCapitalSnapshot().catch(() => {});
        qc.invalidateQueries({ queryKey: ["positions"] });
        qc.invalidateQueries({ queryKey: ["portfolio"] });
      }
    } catch (err: any) {
      setCsvResult({ imported: 0, skipped: 0, errors: [{ row: 0, error: err?.response?.data?.detail || "Upload failed" }] });
    } finally {
      setCsvImporting(false);
      e.target.value = "";
    }
  }

  const updateMut = useMutation({
    mutationFn: ({ ticker, data }: { ticker: string; data: { shares?: number; avg_cost_native?: number; name?: string; currency?: string } }) =>
      updatePosition(ticker, data),
    onSuccess: (_, vars) => {
      saveCapitalSnapshot().catch(() => {});
      qc.invalidateQueries({ queryKey: ["positions"] });
      qc.invalidateQueries({ queryKey: ["portfolio"] });
      qc.invalidateQueries({ queryKey: ["rebalancing"] });
      qc.invalidateQueries({ queryKey: ["frontier"] });
      setEditing((e) => { const n = { ...e }; delete n[vars.ticker]; return n; });
      setSaveStatus((s) => ({ ...s, [vars.ticker]: "ok" }));
      setTimeout(() => setSaveStatus((s) => { const n = { ...s }; delete n[vars.ticker]; return n; }), 2000);
    },
    onError: (_, vars) => setSaveStatus((s) => ({ ...s, [vars.ticker]: "err" })),
  });

  const auditMut = useMutation({
    mutationFn: createTransaction,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["transactions"] }),
  });

  const addPosMut = useMutation({
    mutationFn: upsertPosition,
    onSuccess: (_, vars) => {
      // Auto-update cost basis using FX rate from portfolio cache → persist to Supabase
      if (vars.avg_cost_native && vars.shares != null && vars.shares > 0) {
        const portfolioCache = qc.getQueryData<PortfolioSummary>(["portfolio"]);
        const fxRate = portfolioCache?.rows?.find(r => r.currency === (vars.currency || "USD"))?.fx_rate ?? 1.0;
        const newBasis = (cost_basis_usd ?? 0) + vars.shares! * vars.avg_cost_native * fxRate;
        updateSettings({ cost_basis_usd: newBasis }).then((data) => setSettings(data));
      }
      // Auto-register invested capital as a BUY transaction
      if (vars.avg_cost_native && vars.shares != null && vars.shares > 0) {
        auditMut.mutate({
          ticker: vars.ticker,
          date: posForm.date || today(),
          action: "BUY" as TransactionAction,
          quantity: vars.shares!,
          price_native: vars.avg_cost_native,
          fee_native: 0,
          currency: vars.currency || "USD",
          comment: "Auto-registered from position entry",
        } as Parameters<typeof createTransaction>[0]);
      }
      saveCapitalSnapshot().catch(() => {});
      qc.invalidateQueries({ queryKey: ["positions"] });
      qc.invalidateQueries({ queryKey: ["portfolio"] });
      qc.invalidateQueries({ queryKey: ["rebalancing"] });
      qc.invalidateQueries({ queryKey: ["frontier"] });
      setShowPosForm(false);
      setPosForm(initPositionForm);
    },
  });

  const delPosMut = useMutation({
    mutationFn: deletePosition,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["positions"] });
      qc.invalidateQueries({ queryKey: ["portfolio"] });
    },
  });

  const upsertCashMut = useMutation({
    mutationFn: upsertCash,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cash"] });
      setShowBrokerForm(false);
      setShowYieldForm(false);
      setBrokerForm({ currency: "USD", amount: "" });
      setYieldForm(initCashForm);
    },
  });

  const delCashMut = useMutation({
    mutationFn: ({ currency, account_name }: { currency: string; account_name?: string | null }) =>
      deleteCash(currency, account_name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cash"] }),
  });

  function startEdit(pos: Position) {
    setEditing((e) => ({
      ...e,
      [pos.ticker]: {
        shares: String(pos.shares),
        avg_cost_native: String(pos.avg_cost_native ?? ""),
        name: pos.name,
        currency: pos.currency,
      },
    }));
  }

  function cancelEdit(ticker: string) {
    setEditing((e) => { const n = { ...e }; delete n[ticker]; return n; });
  }

  async function saveEdit(pos: Position) {
    const row = editing[pos.ticker];
    if (!row) return;
    const newShares = parseFloat(row.shares);
    const newAvg = row.avg_cost_native ? parseFloat(row.avg_cost_native) : undefined;

    await updateMut.mutateAsync({ ticker: pos.ticker, data: { shares: newShares, avg_cost_native: newAvg, name: row.name, currency: row.currency } });

    // Register capital delta as BUY/SELL transaction + update cost_basis_usd
    const deltaShares = newShares - pos.shares;
    if (deltaShares !== 0) {
      const price = newAvg ?? pos.avg_cost_native ?? 0;
      auditMut.mutate({
        ticker: pos.ticker,
        date: new Date().toISOString().split("T")[0],
        action: (deltaShares > 0 ? "BUY" : "SELL") as TransactionAction,
        quantity: Math.abs(deltaShares),
        price_native: price,
        fee_native: 0,
        currency: pos.currency,
        comment: `Shares: ${pos.shares} → ${newShares}${newAvg && newAvg !== pos.avg_cost_native ? ` | Avg cost: ${pos.avg_cost_native ?? "—"} → ${newAvg}` : ""}`,
      } as Parameters<typeof createTransaction>[0]);
      qc.invalidateQueries({ queryKey: ["transactions"] });

      // Update cost_basis_usd: delta in USD using fx_rate from portfolio cache
      const portfolioCache = qc.getQueryData<PortfolioSummary>(["portfolio"]);
      const fxRate = portfolioCache?.rows?.find(r => r.ticker === pos.ticker)?.fx_rate ?? 1.0;
      const newBasis = (cost_basis_usd ?? 0) + deltaShares * price * fxRate;
      updateSettings({ cost_basis_usd: newBasis }).then((data) => setSettings(data));
    }
  }

  // ── Broker reconciliation state ──────────────────────────────────────────
  type ReconcileRow = { value: string; pnl_pct: string };
  const [reconcile, setReconcile] = useState<Record<string, ReconcileRow>>({});
  const [reconcileOpen, setReconcileOpen] = useState(false);
  const [applyStatus, setApplyStatus] = useState<Record<string, "ok" | "err">>({});

  function reconcileImpliedAvgCost(shares: number, value: string, pnl_pct: string): number | null {
    const v = parseFloat(value);
    const p = parseFloat(pnl_pct);
    if (!v || isNaN(v) || isNaN(p) || shares <= 0) return null;
    const invested = v / (1 + p / 100);
    return invested / shares;
  }

  async function applyReconcile(pos: Position) {
    const row = reconcile[pos.ticker];
    if (!row) return;
    const implied = reconcileImpliedAvgCost(pos.shares, row.value, row.pnl_pct);
    if (implied == null || implied <= 0) return;
    try {
      await updateMut.mutateAsync({ ticker: pos.ticker, data: { avg_cost_native: parseFloat(implied.toFixed(4)) } });
      setApplyStatus((s) => ({ ...s, [pos.ticker]: "ok" }));
      setReconcile((r) => { const n = { ...r }; delete n[pos.ticker]; return n; });
      setTimeout(() => setApplyStatus((s) => { const n = { ...s }; delete n[pos.ticker]; return n; }), 2500);
    } catch {
      setApplyStatus((s) => ({ ...s, [pos.ticker]: "err" }));
    }
  }

  async function applyAllReconcile() {
    const posMap = Object.fromEntries((positions ?? []).map((p: Position) => [p.ticker, p]));
    for (const [ticker, row] of Object.entries(reconcile)) {
      const pos = posMap[ticker];
      if (!pos) continue;
      const implied = reconcileImpliedAvgCost(pos.shares, row.value, row.pnl_pct);
      if (implied == null || implied <= 0) continue;
      try {
        await updateMut.mutateAsync({ ticker, data: { avg_cost_native: parseFloat(implied.toFixed(4)) } });
        setApplyStatus((s) => ({ ...s, [ticker]: "ok" }));
      } catch {
        setApplyStatus((s) => ({ ...s, [ticker]: "err" }));
      }
    }
    setReconcile({});
  }

  // Separate broker cash (no account_name) from external (has account_name)
  const brokerCash = (cash ?? []).filter((c) => !c.account_name);
  const externalCash = (cash ?? []).filter((c) => !!c.account_name);

  // Audit trail = ADJUSTMENT transactions
  const auditLog = (transactions ?? [])
    .filter((t) => t.action === "ADJUSTMENT")
    .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());

  return (
    <div className="space-y-6">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Manage Portfolio</h1>

      {/* ── Section 0: Broker Reconciliation Agent (XTB) ── */}
      <div className="bbg-card border border-bloomberg-gold/20">
        <div className="flex items-start justify-between mb-1">
          <p className="bbg-header mb-0">🤖 Broker Reconciliation Agent (XTB)</p>
          <span className="text-[9px] text-bloomberg-gold border border-bloomberg-gold/30 px-1.5 py-0.5">AI</span>
        </div>
        <p className="text-bloomberg-muted text-[10px] mb-3">
          Sube tu reporte XTB (Cash Operations .xlsx). El agente importa transacciones, detecta duplicados,
          reconcilia posiciones (shares + avg cost) y valida con IA.<br />
          <span className="text-bloomberg-gold">XTB: Mi Cuenta → Historial → Cash Operations → Exportar Excel</span>
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
                const result = await brokerReconcile(xtbFile);
                setXtbResult(result);
                qc.invalidateQueries({ queryKey: ["positions"] });
                qc.invalidateQueries({ queryKey: ["portfolio"] });
                qc.invalidateQueries({ queryKey: ["transactions"] });
                qc.invalidateQueries({ queryKey: ["portfolio-history"] });
                qc.invalidateQueries({ queryKey: ["rebalancing"] });
                qc.invalidateQueries({ queryKey: ["cash"] });
              } catch (e: any) {
                const detail = e?.response?.data?.detail || String(e);
                setXtbResult({ imported: 0, skipped_duplicates: 0, errors: [detail], positions_updated: 0, positions_created: 0, reconciled_tickers: [], deposits_usd: 0, agent_summary: null });
              }
              setXtbLoading(false);
            }}
            disabled={!xtbFile || xtbLoading}
            className="bg-bloomberg-gold text-bloomberg-bg text-[10px] font-bold px-3 py-1.5 hover:opacity-90 disabled:opacity-50 uppercase tracking-wider"
          >
            {xtbLoading ? "Reconciliando…" : "RECONCILE"}
          </button>
          {xtbLoading && <span className="text-bloomberg-muted text-[10px]">Importando + reconciliando posiciones + validando con IA… ~20s</span>}
        </div>
        {xtbResult && (
          <div className={`mt-3 p-3 text-[10px] border space-y-2 ${xtbResult.imported > 0 || xtbResult.positions_updated > 0 ? "border-green-500/30 bg-green-500/5" : "border-bloomberg-border"}`}>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <div>
                <p className="text-bloomberg-muted uppercase tracking-widest text-[9px]">Importadas</p>
                <p className="font-bold text-bloomberg-text text-sm">{xtbResult.imported}</p>
              </div>
              <div>
                <p className="text-bloomberg-muted uppercase tracking-widest text-[9px]">Duplicadas omitidas</p>
                <p className="font-bold text-bloomberg-muted text-sm">{xtbResult.skipped_duplicates}</p>
              </div>
              <div>
                <p className="text-bloomberg-muted uppercase tracking-widest text-[9px]">Posiciones actualizadas</p>
                <p className="font-bold text-bloomberg-gold text-sm">{xtbResult.positions_updated}</p>
              </div>
              <div>
                <p className="text-bloomberg-muted uppercase tracking-widest text-[9px]">Posiciones creadas</p>
                <p className="font-bold text-green-400 text-sm">{xtbResult.positions_created}</p>
              </div>
            </div>
            {xtbResult.deposits_usd > 0 && (
              <p className="text-bloomberg-muted">
                Depósitos detectados: <span className="text-bloomberg-gold font-bold">${xtbResult.deposits_usd.toFixed(2)}</span>
                <span className="text-bloomberg-muted ml-2">→ actualiza el saldo en <span className="text-bloomberg-text">Broker Cash</span> abajo si hay cash sin invertir</span>
              </p>
            )}
            {xtbResult.reconciled_tickers.length > 0 && (
              <p className="text-bloomberg-muted">Tickers reconciliados: <span className="text-bloomberg-text">{xtbResult.reconciled_tickers.join(", ")}</span></p>
            )}
            {xtbResult.agent_summary && (
              <div className="border-l-2 border-bloomberg-gold pl-2 mt-2">
                <p className="text-[9px] text-bloomberg-gold uppercase tracking-widest mb-0.5">Validación IA</p>
                <p className="text-bloomberg-text leading-relaxed">{xtbResult.agent_summary}</p>
              </div>
            )}
            {xtbResult.errors.length > 0 && (
              <ul className="text-red-400">
                {xtbResult.errors.map((e, i) => <li key={i}>⚠ {e}</li>)}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* ── Section 1: Current Positions ── */}
      <div className="bbg-card">
        <div className="flex items-center justify-between mb-3">
          <p className="bbg-header mb-0">Current Positions</p>
          <div className="flex items-center gap-2">
            <button
              onClick={async () => {
                const blob = await exportPositionsCsv();
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `positions_${new Date().toISOString().slice(0, 10)}.csv`;
                a.click();
                URL.revokeObjectURL(url);
              }}
              className="flex items-center gap-1 text-[10px] text-bloomberg-muted border border-bloomberg-border px-2 py-1 hover:text-bloomberg-gold hover:border-bloomberg-gold"
              title="Export to CSV"
            >
              ↓ CSV
            </button>
            <button
              onClick={() => setShowPosForm((v) => !v)}
              className="flex items-center gap-1 text-[10px] text-bloomberg-muted border border-bloomberg-border px-2 py-1 hover:text-bloomberg-gold hover:border-bloomberg-gold"
            >
              <Plus size={11} /> Add Position
            </button>
          </div>
        </div>

        {showPosForm && (
          <div className="mb-4 p-3 border border-bloomberg-border bg-bloomberg-bg">
            <p className="text-bloomberg-muted text-[10px] uppercase mb-2">New Position</p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-2">
              <div>
                <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Ticker</label>
                <input
                  type="text"
                  value={posForm.ticker}
                  onChange={(e) => setPosForm((p) => ({ ...p, ticker: e.target.value.toUpperCase() }))}
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-2 sm:py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
                />
              </div>
              <div>
                <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Name</label>
                <input
                  type="text"
                  value={posForm.name}
                  onChange={(e) => setPosForm((p) => ({ ...p, name: e.target.value }))}
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-2 sm:py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
                />
              </div>
              <div>
                <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Shares</label>
                <input
                  type="number"
                  step="any"
                  value={posForm.shares}
                  onChange={(e) => setPosForm((p) => ({ ...p, shares: e.target.value }))}
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-2 sm:py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
                />
              </div>
              <div>
                <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Avg Cost</label>
                <input
                  type="number"
                  step="any"
                  value={posForm.avg_cost_native}
                  onChange={(e) => setPosForm((p) => ({ ...p, avg_cost_native: e.target.value }))}
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-2 sm:py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
                />
              </div>
              <div>
                <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Currency</label>
                <select
                  value={posForm.currency}
                  onChange={(e) => setPosForm((p) => ({ ...p, currency: e.target.value }))}
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-2 sm:py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
                >
                  {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Purchase Date</label>
                <input
                  type="date"
                  value={posForm.date}
                  onChange={(e) => setPosForm((p) => ({ ...p, date: e.target.value }))}
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-2 sm:py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
                />
              </div>
            </div>
            {posForm.shares && posForm.avg_cost_native && (
              <p className="text-bloomberg-muted text-[10px] mb-2">
                Capital invested: <span className="text-bloomberg-gold font-semibold">
                  {posForm.currency} {(parseFloat(posForm.shares) * parseFloat(posForm.avg_cost_native)).toFixed(2)}
                </span>
              </p>
            )}
            <div className="flex gap-2">
              <button
                onClick={() =>
                  addPosMut.mutate({
                    ticker: posForm.ticker,
                    name: posForm.name || posForm.ticker,
                    shares: parseFloat(posForm.shares) || 0,
                    avg_cost_native: posForm.avg_cost_native ? parseFloat(posForm.avg_cost_native) : undefined,
                    currency: posForm.currency,
                    market: "US",
                  })
                }
                disabled={!posForm.ticker || !posForm.shares}
                className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-4 py-1 disabled:opacity-50"
              >
                SAVE
              </button>
              <button onClick={() => setShowPosForm(false)} className="text-bloomberg-muted text-xs px-3 py-1 border border-bloomberg-border">
                CANCEL
              </button>
            </div>
          </div>
        )}

        {posLoading ? (
          <p className="text-bloomberg-muted text-xs py-2">Loading…</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="bbg-table">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th className="hidden sm:table-cell">Name</th>
                  <th className="text-right">Shares</th>
                  <th className="text-right hidden sm:table-cell">Avg Cost (USD)</th>
                  <th className="hidden md:table-cell">CCY</th>
                  <th className="hidden md:table-cell">Market</th>
                  <th className="text-center">Actions</th>
                </tr>
              </thead>
              <tbody>
                {(positions ?? []).map((pos: Position) => {
                  const isEditing = !!editing[pos.ticker];
                  const row = editing[pos.ticker];
                  const status = saveStatus[pos.ticker];
                  return (
                    <tr key={pos.ticker} className={isEditing ? "bg-bloomberg-card" : ""}>
                      <td className="text-bloomberg-gold font-medium">{pos.ticker}</td>
                      <td className="hidden sm:table-cell">
                        {isEditing ? (
                          <input
                            value={row.name}
                            onChange={(e) => setEditing((ed) => ({ ...ed, [pos.ticker]: { ...ed[pos.ticker], name: e.target.value } }))}
                            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 sm:py-0.5 text-xs w-full sm:w-32 focus:outline-none focus:border-bloomberg-gold"
                          />
                        ) : (
                          <span className="text-bloomberg-muted">{pos.name}</span>
                        )}
                      </td>
                      <td className="text-right">
                        {isEditing ? (
                          <input
                            type="number"
                            step="any"
                            value={row.shares}
                            onChange={(e) => setEditing((ed) => ({ ...ed, [pos.ticker]: { ...ed[pos.ticker], shares: e.target.value } }))}
                            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 sm:py-0.5 text-xs w-20 sm:w-28 text-right focus:outline-none focus:border-bloomberg-gold"
                          />
                        ) : (
                          <span>{pos.shares.toFixed(4)}</span>
                        )}
                      </td>
                      <td className="text-right hidden sm:table-cell">
                        {isEditing ? (
                          <input
                            type="number"
                            step="any"
                            value={row.avg_cost_native}
                            onChange={(e) => setEditing((ed) => ({ ...ed, [pos.ticker]: { ...ed[pos.ticker], avg_cost_native: e.target.value } }))}
                            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1.5 sm:py-0.5 text-xs w-full sm:w-28 text-right focus:outline-none focus:border-bloomberg-gold"
                          />
                        ) : (
                          <span className="text-bloomberg-muted">
                            {pos.avg_cost_native != null ? fmtCurrency(pos.avg_cost_native, pos.currency) : "—"}
                          </span>
                        )}
                      </td>
                      <td className="hidden md:table-cell">
                        {isEditing ? (
                          <select
                            value={row.currency}
                            onChange={(e) => setEditing((ed) => ({ ...ed, [pos.ticker]: { ...ed[pos.ticker], currency: e.target.value } }))}
                            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-1 py-1.5 sm:py-0.5 text-xs"
                          >
                            {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
                          </select>
                        ) : (
                          <span className="text-bloomberg-muted">{pos.currency}</span>
                        )}
                      </td>
                      <td className="text-bloomberg-muted hidden md:table-cell">{pos.market}</td>
                      <td className="text-center">
                        <div className="flex items-center justify-center gap-2">
                          {isEditing ? (
                            <>
                              <button
                                onClick={() => saveEdit(pos)}
                                disabled={updateMut.isPending}
                                className="text-green-400 hover:text-green-300 disabled:opacity-50"
                                title="Save"
                              >
                                <Check size={13} />
                              </button>
                              <button onClick={() => cancelEdit(pos.ticker)} className="text-bloomberg-muted hover:text-bloomberg-text" title="Cancel">
                                <X size={13} />
                              </button>
                            </>
                          ) : (
                            <>
                              {status === "ok" && <Check size={12} className="text-green-400" />}
                              {status === "err" && <AlertCircle size={12} className="text-red-400" />}
                              <button onClick={() => startEdit(pos)} className="text-bloomberg-muted hover:text-bloomberg-gold" title="Edit">
                                <Pencil size={12} />
                              </button>
                              <button
                                onClick={() => { if (confirm(`Delete ${pos.ticker}?`)) delPosMut.mutate(pos.ticker); }}
                                className="text-bloomberg-muted hover:text-red-400"
                                title="Delete"
                              >
                                <Trash2 size={12} />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── CSV Bulk Import ── */}
      <div className="bbg-card">
        <div className="flex items-center justify-between mb-3">
          <div>
            <p className="bbg-header mb-0">Bulk Import Positions</p>
            <p className="text-bloomberg-muted text-[10px]">
              Upload a CSV with columns: <span className="text-bloomberg-gold">ticker, shares</span> (optional: avg_cost_native, currency, name)
            </p>
          </div>
          <label className={`flex items-center gap-1.5 text-[10px] border px-3 py-1.5 cursor-pointer transition-colors ${
            csvImporting
              ? "border-bloomberg-border text-bloomberg-muted opacity-50 pointer-events-none"
              : "border-bloomberg-gold text-bloomberg-gold hover:bg-bloomberg-gold/10"
          }`}>
            {csvImporting ? "Importing…" : "↑ Upload CSV"}
            <input type="file" accept=".csv,text/csv" className="hidden" onChange={handleCsvImport} disabled={csvImporting} />
          </label>
        </div>

        {/* Template hint */}
        <p className="text-bloomberg-muted text-[9px] mb-2 font-mono">
          ticker,shares,avg_cost_native,currency,name<br />
          VWCE.DE,14.534,142.46,EUR,Vanguard FTSE All-World<br />
          QQQM,10,180.50,USD,Invesco NASDAQ 100
        </p>

        {/* Result */}
        {csvResult && (
          <div className={`border p-3 text-xs ${csvResult.errors.length === 0 ? "border-green-800 bg-green-900/20" : "border-bloomberg-gold bg-bloomberg-gold/5"}`}>
            <div className="flex gap-4 mb-1">
              <span className="text-green-400 font-bold">✓ {csvResult.imported} imported</span>
              {csvResult.skipped > 0 && <span className="text-bloomberg-muted">{csvResult.skipped} skipped</span>}
              {csvResult.errors.length > 0 && <span className="text-red-400">{csvResult.errors.length} error(s)</span>}
            </div>
            {csvResult.errors.length > 0 && (
              <ul className="space-y-0.5 text-[10px]">
                {csvResult.errors.map((e, i) => (
                  <li key={i} className="text-red-400">Row {e.row}{e.ticker ? ` (${e.ticker})` : ""}: {e.error}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* ── Section 2: Broker Reconciliation ── */}
      <div className="bbg-card">
        <div className="flex items-center justify-between mb-1">
          <div>
            <p className="bbg-header mb-0">Broker Reconciliation</p>
            <p className="text-bloomberg-muted text-[10px]">
              Enter <span className="text-bloomberg-gold">Valor</span> and <span className="text-bloomberg-gold">Beneficio neto %</span> from XTB → auto-computes avg cost
            </p>
          </div>
          <button
            onClick={() => setReconcileOpen((v) => !v)}
            className="text-[10px] text-bloomberg-muted border border-bloomberg-border px-2 py-1 hover:text-bloomberg-gold hover:border-bloomberg-gold"
          >
            {reconcileOpen ? "HIDE" : "SHOW"}
          </button>
        </div>

        {reconcileOpen && (
          <>
            <div className="overflow-x-auto mt-3">
              <table className="bbg-table">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th className="text-right">Shares</th>
                    <th className="text-right">Broker Value (USD)</th>
                    <th className="text-right">Broker PnL %</th>
                    <th className="text-right">→ Implied Avg Cost</th>
                    <th className="text-right">Current Avg Cost</th>
                    <th className="text-right">Δ</th>
                    <th className="text-center">Apply</th>
                  </tr>
                </thead>
                <tbody>
                  {(positions ?? []).map((pos: Position) => {
                    const row = reconcile[pos.ticker] ?? { value: "", pnl_pct: "" };
                    const implied = reconcileImpliedAvgCost(pos.shares, row.value, row.pnl_pct);
                    const current = pos.avg_cost_native ?? null;
                    const delta = implied != null && current != null ? ((implied - current) / current) * 100 : null;
                    const status = applyStatus[pos.ticker];
                    return (
                      <tr key={pos.ticker}>
                        <td className="text-bloomberg-gold font-medium">{pos.ticker}</td>
                        <td className="text-right text-bloomberg-muted">{pos.shares.toFixed(4)}</td>
                        <td className="text-right">
                          <input
                            type="number"
                            step="any"
                            placeholder="e.g. 152.78"
                            value={row.value}
                            onChange={(e) => setReconcile((r) => ({ ...r, [pos.ticker]: { ...row, value: e.target.value } }))}
                            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-0.5 text-xs w-28 text-right focus:outline-none focus:border-bloomberg-gold"
                          />
                        </td>
                        <td className="text-right">
                          <input
                            type="number"
                            step="any"
                            placeholder="e.g. 8.68"
                            value={row.pnl_pct}
                            onChange={(e) => setReconcile((r) => ({ ...r, [pos.ticker]: { ...row, pnl_pct: e.target.value } }))}
                            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-0.5 text-xs w-24 text-right focus:outline-none focus:border-bloomberg-gold"
                          />
                        </td>
                        <td className="text-right font-medium text-bloomberg-gold">
                          {implied != null ? fmtCurrency(implied, pos.currency) : "—"}
                        </td>
                        <td className="text-right text-bloomberg-muted">
                          {current != null ? fmtCurrency(current, pos.currency) : "—"}
                        </td>
                        <td className={`text-right text-xs font-medium ${delta == null ? "text-bloomberg-muted" : Math.abs(delta) < 0.5 ? "text-green-400" : "text-yellow-400"}`}>
                          {delta != null ? `${delta > 0 ? "+" : ""}${delta.toFixed(1)}%` : "—"}
                        </td>
                        <td className="text-center">
                          {status === "ok" ? (
                            <Check size={13} className="text-green-400 mx-auto" />
                          ) : status === "err" ? (
                            <AlertCircle size={13} className="text-red-400 mx-auto" />
                          ) : (
                            <button
                              onClick={() => applyReconcile(pos)}
                              disabled={implied == null || updateMut.isPending}
                              className="text-[10px] bg-bloomberg-gold text-bloomberg-bg font-bold px-2 py-0.5 disabled:opacity-30"
                            >
                              APPLY
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex justify-end">
              <button
                onClick={applyAllReconcile}
                disabled={Object.keys(reconcile).length === 0 || updateMut.isPending}
                className="text-[10px] bg-bloomberg-gold text-bloomberg-bg font-bold px-4 py-1 disabled:opacity-30"
              >
                APPLY ALL
              </button>
            </div>
          </>
        )}
      </div>

      {/* ── Section 3: Cash Balances — Broker / Portfolio ── */}
      <div className="bbg-card">
        <div className="flex items-center justify-between mb-3">
          <div>
            <p className="bbg-header mb-0">Broker Cash (Portfolio)</p>
            <p className="text-bloomberg-muted text-[10px]">Uninvested cash sitting in your brokerage accounts</p>
          </div>
          <button
            onClick={() => setShowBrokerForm((v) => !v)}
            className="flex items-center gap-1 text-[10px] text-bloomberg-muted border border-bloomberg-border px-2 py-1 hover:text-bloomberg-gold hover:border-bloomberg-gold"
          >
            <Plus size={11} /> Set Balance
          </button>
        </div>

        {showBrokerForm && (
          <div className="mb-4 p-3 border border-bloomberg-border bg-bloomberg-bg flex flex-wrap gap-3 items-end">
            <div>
              <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Currency</label>
              <select
                value={brokerForm.currency}
                onChange={(e) => setBrokerForm((f) => ({ ...f, currency: e.target.value }))}
                className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs"
              >
                {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Amount</label>
              <input
                type="number"
                step="any"
                value={brokerForm.amount}
                onChange={(e) => setBrokerForm((f) => ({ ...f, amount: e.target.value }))}
                className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs w-32 focus:outline-none focus:border-bloomberg-gold"
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => upsertCashMut.mutate({ currency: brokerForm.currency, amount: parseFloat(brokerForm.amount) || 0, account_name: null })}
                disabled={!brokerForm.amount}
                className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-4 py-1 disabled:opacity-50"
              >
                SAVE
              </button>
              <button onClick={() => setShowBrokerForm(false)} className="text-bloomberg-muted text-xs px-3 py-1 border border-bloomberg-border">
                CANCEL
              </button>
            </div>
          </div>
        )}

        {cashLoading ? (
          <p className="text-bloomberg-muted text-xs">Loading…</p>
        ) : brokerCash.length === 0 ? (
          <p className="text-bloomberg-muted text-xs py-2">No broker cash recorded.</p>
        ) : (
          <table className="bbg-table">
            <thead>
              <tr>
                <th>Currency</th>
                <th className="text-right">Amount</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {brokerCash.map((c) => (
                <tr key={c.currency}>
                  <td className="text-bloomberg-gold font-medium">{c.currency}</td>
                  <td className="text-right font-medium">{fmtCurrency(c.amount, c.currency)}</td>
                  <td className="text-right">
                    <button
                      onClick={() => { if (confirm("Remove?")) delCashMut.mutate({ currency: c.currency, account_name: null }); }}
                      className="text-bloomberg-muted hover:text-red-400"
                    >
                      <Trash2 size={11} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Section 4: External Cash — High Yield / Savings ── */}
      <div className="bbg-card">
        <div className="flex items-center justify-between mb-3">
          <div>
            <p className="bbg-header mb-0">External Cash (High Yield / Savings)</p>
            <p className="text-bloomberg-muted text-[10px]">Money in savings accounts, high-yield accounts, digital banks — not invested</p>
          </div>
          <button
            onClick={() => setShowYieldForm((v) => !v)}
            className="flex items-center gap-1 text-[10px] text-bloomberg-muted border border-bloomberg-border px-2 py-1 hover:text-bloomberg-gold hover:border-bloomberg-gold"
          >
            <Plus size={11} /> Add Account
          </button>
        </div>

        {showYieldForm && (
          <div className="mb-4 p-3 border border-bloomberg-border bg-bloomberg-bg flex flex-wrap gap-3 items-end">
            <div>
              <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Account Name</label>
              <input
                type="text"
                placeholder="e.g. Nubank, Marcus, Daviplata"
                value={yieldForm.account_name}
                onChange={(e) => setYieldForm((f) => ({ ...f, account_name: e.target.value }))}
                className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs w-44 focus:outline-none focus:border-bloomberg-gold"
              />
            </div>
            <div>
              <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Currency</label>
              <select
                value={yieldForm.currency}
                onChange={(e) => setYieldForm((f) => ({ ...f, currency: e.target.value }))}
                className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs"
              >
                {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Amount</label>
              <input
                type="number"
                step="any"
                value={yieldForm.amount}
                onChange={(e) => setYieldForm((f) => ({ ...f, amount: e.target.value }))}
                className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs w-32 focus:outline-none focus:border-bloomberg-gold"
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={() =>
                  upsertCashMut.mutate({
                    currency: yieldForm.currency,
                    amount: parseFloat(yieldForm.amount) || 0,
                    account_name: yieldForm.account_name || null,
                  })
                }
                disabled={!yieldForm.amount || !yieldForm.account_name}
                className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-4 py-1 disabled:opacity-50"
              >
                SAVE
              </button>
              <button onClick={() => setShowYieldForm(false)} className="text-bloomberg-muted text-xs px-3 py-1 border border-bloomberg-border">
                CANCEL
              </button>
            </div>
          </div>
        )}

        {cashLoading ? (
          <p className="text-bloomberg-muted text-xs">Loading…</p>
        ) : externalCash.length === 0 ? (
          <p className="text-bloomberg-muted text-xs py-2">No external accounts recorded.</p>
        ) : (
          <table className="bbg-table">
            <thead>
              <tr>
                <th>Account</th>
                <th>Currency</th>
                <th className="text-right">Amount</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {externalCash.map((c) => (
                <tr key={`${c.account_name}-${c.currency}`}>
                  <td className="text-bloomberg-gold font-medium">{c.account_name}</td>
                  <td className="text-bloomberg-muted">{c.currency}</td>
                  <td className="text-right font-medium">{fmtCurrency(c.amount, c.currency)}</td>
                  <td className="text-right">
                    <button
                      onClick={() => { if (confirm("Remove?")) delCashMut.mutate({ currency: c.currency, account_name: c.account_name }); }}
                      className="text-bloomberg-muted hover:text-red-400"
                    >
                      <Trash2 size={11} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Section 5: Audit Trail ── */}
      <div className="bbg-card">
        <p className="bbg-header">Audit Trail — Position Adjustments</p>
        <p className="text-bloomberg-muted text-[10px] mb-3">
          History of manual share count changes made from this page.
        </p>
        {txLoading ? (
          <p className="text-bloomberg-muted text-xs">Loading…</p>
        ) : auditLog.length === 0 ? (
          <p className="text-bloomberg-muted text-xs py-2">No manual adjustments yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="bbg-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Ticker</th>
                  <th className="text-right">New Shares</th>
                  <th>CCY</th>
                  <th>Change Detail</th>
                </tr>
              </thead>
              <tbody>
                {auditLog.map((t) => (
                  <tr key={t.id}>
                    <td className="text-bloomberg-muted">{fmtDate(t.date)}</td>
                    <td className="text-bloomberg-gold font-medium">{t.ticker}</td>
                    <td className="text-right">{t.quantity.toFixed(4)}</td>
                    <td className="text-bloomberg-muted">{t.currency}</td>
                    <td className="text-bloomberg-muted text-[10px]">{t.comment || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
