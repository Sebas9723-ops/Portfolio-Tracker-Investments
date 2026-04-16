"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchPositions, upsertPosition, updatePosition, deletePosition } from "@/lib/api/portfolio";
import { fetchTransactions, createTransaction, fetchCash, upsertCash, deleteCash } from "@/lib/api/transactions";
import { fmtCurrency, fmtDate } from "@/lib/formatters";
import { Pencil, Trash2, Plus, Check, X, AlertCircle } from "lucide-react";
import type { Position, TransactionAction } from "@/lib/types";

const CURRENCIES = ["USD", "EUR", "GBP", "COP", "CHF", "AUD"];
const MARKETS = ["US", "LSE", "XETRA", "EURONEXT", "TSX", "ASX"];

const today = () => new Date().toISOString().split("T")[0];
const initPositionForm = { ticker: "", name: "", shares: "", avg_cost_native: "", currency: "USD", date: today() };
const initCashForm = { currency: "USD", amount: "", account_name: "" };

type EditRow = { shares: string; avg_cost_native: string; name: string; currency: string };

export default function ManagePage() {
  const qc = useQueryClient();

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

  const updateMut = useMutation({
    mutationFn: ({ ticker, data }: { ticker: string; data: { shares?: number; avg_cost_native?: number; name?: string; currency?: string } }) =>
      updatePosition(ticker, data),
    onSuccess: (_, vars) => {
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
      // Auto-register invested capital as a BUY transaction
      if (vars.avg_cost_native && vars.shares > 0) {
        auditMut.mutate({
          ticker: vars.ticker,
          date: posForm.date || today(),
          action: "BUY" as TransactionAction,
          quantity: vars.shares,
          price_native: vars.avg_cost_native,
          fee_native: 0,
          currency: vars.currency || "USD",
          comment: "Auto-registered from position entry",
        } as Parameters<typeof createTransaction>[0]);
      }
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

    // Register capital delta as BUY/SELL transaction
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
    }
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

      {/* ── Section 1: Current Positions ── */}
      <div className="bbg-card">
        <div className="flex items-center justify-between mb-3">
          <p className="bbg-header mb-0">Current Positions</p>
          <button
            onClick={() => setShowPosForm((v) => !v)}
            className="flex items-center gap-1 text-[10px] text-bloomberg-muted border border-bloomberg-border px-2 py-1 hover:text-bloomberg-gold hover:border-bloomberg-gold"
          >
            <Plus size={11} /> Add Position
          </button>
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
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
                />
              </div>
              <div>
                <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Name</label>
                <input
                  type="text"
                  value={posForm.name}
                  onChange={(e) => setPosForm((p) => ({ ...p, name: e.target.value }))}
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
                />
              </div>
              <div>
                <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Shares</label>
                <input
                  type="number"
                  step="any"
                  value={posForm.shares}
                  onChange={(e) => setPosForm((p) => ({ ...p, shares: e.target.value }))}
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
                />
              </div>
              <div>
                <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Avg Cost</label>
                <input
                  type="number"
                  step="any"
                  value={posForm.avg_cost_native}
                  onChange={(e) => setPosForm((p) => ({ ...p, avg_cost_native: e.target.value }))}
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
                />
              </div>
              <div>
                <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Currency</label>
                <select
                  value={posForm.currency}
                  onChange={(e) => setPosForm((p) => ({ ...p, currency: e.target.value }))}
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
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
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
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
                  <th>Name</th>
                  <th className="text-right">Shares</th>
                  <th className="text-right">Avg Cost (USD)</th>
                  <th>CCY</th>
                  <th>Market</th>
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
                      <td>
                        {isEditing ? (
                          <input
                            value={row.name}
                            onChange={(e) => setEditing((ed) => ({ ...ed, [pos.ticker]: { ...ed[pos.ticker], name: e.target.value } }))}
                            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-0.5 text-xs w-32 focus:outline-none focus:border-bloomberg-gold"
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
                            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-0.5 text-xs w-28 text-right focus:outline-none focus:border-bloomberg-gold"
                          />
                        ) : (
                          <span>{pos.shares.toFixed(4)}</span>
                        )}
                      </td>
                      <td className="text-right">
                        {isEditing ? (
                          <input
                            type="number"
                            step="any"
                            value={row.avg_cost_native}
                            onChange={(e) => setEditing((ed) => ({ ...ed, [pos.ticker]: { ...ed[pos.ticker], avg_cost_native: e.target.value } }))}
                            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-0.5 text-xs w-28 text-right focus:outline-none focus:border-bloomberg-gold"
                          />
                        ) : (
                          <span className="text-bloomberg-muted">
                            {pos.avg_cost_native != null ? fmtCurrency(pos.avg_cost_native, pos.currency) : "—"}
                          </span>
                        )}
                      </td>
                      <td>
                        {isEditing ? (
                          <select
                            value={row.currency}
                            onChange={(e) => setEditing((ed) => ({ ...ed, [pos.ticker]: { ...ed[pos.ticker], currency: e.target.value } }))}
                            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-1 py-0.5 text-xs"
                          >
                            {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
                          </select>
                        ) : (
                          <span className="text-bloomberg-muted">{pos.currency}</span>
                        )}
                      </td>
                      <td className="text-bloomberg-muted">{pos.market}</td>
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

      {/* ── Section 2: Cash Balances — Broker / Portfolio ── */}
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

      {/* ── Section 3: External Cash — High Yield / Savings ── */}
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

      {/* ── Section 4: Audit Trail ── */}
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
