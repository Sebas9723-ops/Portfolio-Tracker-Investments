"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchPositions, upsertPosition, deletePosition } from "@/lib/api/portfolio";
import { fetchCash } from "@/lib/api/transactions";
import { fmtCurrency } from "@/lib/formatters";
import { useSettingsStore } from "@/lib/store/settingsStore";
import { Plus, Trash2 } from "lucide-react";
import type { Position } from "@/lib/types";

export default function PortfolioPage() {
  const { data: positions, isLoading } = useQuery({ queryKey: ["positions"], queryFn: fetchPositions });
  const { data: cash } = useQuery({ queryKey: ["cash"], queryFn: fetchCash });
  const qc = useQueryClient();
  const base_currency = useSettingsStore((s) => s.base_currency);

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ticker: "", name: "", shares: "", avg_cost_native: "", currency: "USD" });

  const addMutation = useMutation({
    mutationFn: upsertPosition,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["positions"] }); qc.invalidateQueries({ queryKey: ["portfolio"] }); setShowForm(false); setForm({ ticker: "", name: "", shares: "", avg_cost_native: "", currency: "USD" }); },
  });

  const delMutation = useMutation({
    mutationFn: deletePosition,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["positions"] }); qc.invalidateQueries({ queryKey: ["portfolio"] }); },
  });

  if (isLoading) return <div className="text-bloomberg-muted text-xs p-4">Loading…</div>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Positions</h1>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 text-[10px] text-bloomberg-muted border border-bloomberg-border px-3 py-1.5 hover:text-bloomberg-gold hover:border-bloomberg-gold"
        >
          <Plus size={11} /> Add Position
        </button>
      </div>

      {/* Add form */}
      {showForm && (
        <div className="bbg-card">
          <p className="bbg-header">New Position</p>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {(["ticker", "name", "shares", "avg_cost_native", "currency"] as const).map((field) => (
              <div key={field}>
                <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">{field}</label>
                <input
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
                  value={form[field]}
                  onChange={(e) => setForm((f) => ({ ...f, [field]: e.target.value }))}
                />
              </div>
            ))}
          </div>
          <div className="flex gap-2 mt-3">
            <button
              onClick={() => addMutation.mutate({
                ticker: form.ticker.toUpperCase(),
                name: form.name || form.ticker.toUpperCase(),
                shares: parseFloat(form.shares) || 0,
                avg_cost_native: form.avg_cost_native ? parseFloat(form.avg_cost_native) : undefined,
                currency: form.currency || "USD",
              })}
              className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-4 py-1 hover:opacity-90"
            >
              SAVE
            </button>
            <button onClick={() => setShowForm(false)} className="text-bloomberg-muted text-xs px-3 py-1 border border-bloomberg-border hover:text-bloomberg-text">
              CANCEL
            </button>
          </div>
        </div>
      )}

      {/* Positions table */}
      <div className="bbg-card">
        <div className="overflow-x-auto">
          <table className="bbg-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Name</th>
                <th className="text-right">Shares</th>
                <th className="text-right">Avg Cost</th>
                <th>Currency</th>
                <th>Market</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(positions || []).map((p: Position) => (
                <tr key={p.id}>
                  <td className="text-bloomberg-gold font-medium">{p.ticker}</td>
                  <td className="text-bloomberg-muted">{p.name}</td>
                  <td className="text-right">{p.shares.toFixed(4)}</td>
                  <td className="text-right">{p.avg_cost_native != null ? fmtCurrency(p.avg_cost_native, p.currency) : "—"}</td>
                  <td>{p.currency}</td>
                  <td className="text-bloomberg-muted">{p.market}</td>
                  <td>
                    <button onClick={() => { if (confirm(`Delete ${p.ticker}?`)) delMutation.mutate(p.ticker); }}
                      className="text-bloomberg-muted hover:text-bloomberg-red">
                      <Trash2 size={11} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Cash balances */}
      {cash && cash.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Cash Balances</p>
          <table className="bbg-table">
            <thead><tr><th>Account</th><th>Currency</th><th className="text-right">Amount</th></tr></thead>
            <tbody>
              {cash.map((c, i) => (
                <tr key={i}>
                  <td className="text-bloomberg-muted">{c.account_name || "—"}</td>
                  <td>{c.currency}</td>
                  <td className="text-right">{fmtCurrency(c.amount, c.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
