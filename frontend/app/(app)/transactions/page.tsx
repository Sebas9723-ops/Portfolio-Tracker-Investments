"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchTransactions, createTransaction, deleteTransaction } from "@/lib/api/transactions";
import { fmtCurrency, fmtDate, colorClass } from "@/lib/formatters";
import { Plus, Trash2 } from "lucide-react";
import type { TransactionAction } from "@/lib/types";

const ACTIONS: TransactionAction[] = ["BUY", "SELL", "DIVIDEND", "SPLIT", "FEE"];

const initForm = { ticker: "", date: new Date().toISOString().split("T")[0], action: "BUY" as TransactionAction, quantity: "", price_native: "", fee_native: "0", currency: "USD", comment: "" };

export default function TransactionsPage() {
  const { data: transactions, isLoading } = useQuery({ queryKey: ["transactions"], queryFn: fetchTransactions });
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(initForm);

  const createMut = useMutation({
    mutationFn: createTransaction,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["portfolioHistory"] });
      setShowForm(false);
      setForm(initForm);
    },
  });

  const delMut = useMutation({
    mutationFn: deleteTransaction,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["portfolioHistory"] });
    },
  });

  const totalBought = transactions?.filter((t) => t.action === "BUY")
    .reduce((s, t) => s + t.quantity * t.price_native + t.fee_native, 0) ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Transactions</h1>
          <p className="text-bloomberg-muted text-[10px]">{transactions?.length ?? 0} records · Total deployed: {fmtCurrency(totalBought)}</p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 text-[10px] text-bloomberg-muted border border-bloomberg-border px-3 py-1.5 hover:text-bloomberg-gold hover:border-bloomberg-gold"
        >
          <Plus size={11} /> Add Transaction
        </button>
      </div>

      {showForm && (
        <div className="bbg-card">
          <p className="bbg-header">New Transaction</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {(["ticker", "date", "quantity", "price_native", "fee_native", "currency", "comment"] as const).map((field) => (
              <div key={field}>
                <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">{field}</label>
                <input
                  type={["date"].includes(field) ? "date" : ["quantity", "price_native", "fee_native"].includes(field) ? "number" : "text"}
                  className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-2 sm:py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
                  value={(form as Record<string, string>)[field]}
                  onChange={(e) => setForm((f) => ({ ...f, [field]: e.target.value }))}
                  step="any"
                />
              </div>
            ))}
            <div>
              <label className="block text-bloomberg-muted text-[10px] uppercase mb-1">Action</label>
              <select
                className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-2 sm:py-1 text-xs focus:outline-none focus:border-bloomberg-gold"
                value={form.action}
                onChange={(e) => setForm((f) => ({ ...f, action: e.target.value as TransactionAction }))}
              >
                {ACTIONS.map((a) => <option key={a}>{a}</option>)}
              </select>
            </div>
          </div>
          <div className="flex gap-2 mt-3">
            <button
              onClick={() => createMut.mutate({
                ticker: form.ticker.toUpperCase(),
                date: form.date,
                action: form.action,
                quantity: parseFloat(form.quantity),
                price_native: parseFloat(form.price_native),
                fee_native: parseFloat(form.fee_native) || 0,
                currency: form.currency,
                comment: form.comment || null,
              } as Parameters<typeof createTransaction>[0])}
              className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-4 py-1"
            >
              SAVE
            </button>
            <button onClick={() => setShowForm(false)} className="text-bloomberg-muted text-xs px-3 py-1 border border-bloomberg-border">
              CANCEL
            </button>
          </div>
        </div>
      )}

      <div className="bbg-card">
        {isLoading ? (
          <div className="text-bloomberg-muted text-xs py-4">Loading…</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="bbg-table">
              <thead>
                <tr>
                  <th>Date</th><th>Ticker</th><th>Action</th>
                  <th className="text-right hidden sm:table-cell">Qty</th>
                  <th className="text-right hidden sm:table-cell">Price</th>
                  <th className="text-right hidden md:table-cell">Fee</th>
                  <th className="text-right">Total</th>
                  <th className="hidden md:table-cell">CCY</th>
                  <th className="hidden lg:table-cell">Comment</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {(transactions ?? []).map((tx) => {
                  const total = tx.quantity * tx.price_native;
                  return (
                    <tr key={tx.id}>
                      <td className="text-bloomberg-muted">{fmtDate(tx.date)}</td>
                      <td className="text-bloomberg-gold font-medium">{tx.ticker}</td>
                      <td className={tx.action === "BUY" ? "positive" : tx.action === "SELL" ? "negative" : "muted"}>
                        {tx.action}
                      </td>
                      <td className="text-right hidden sm:table-cell">{tx.quantity.toFixed(4)}</td>
                      <td className="text-right hidden sm:table-cell">{fmtCurrency(tx.price_native, tx.currency)}</td>
                      <td className="text-right text-bloomberg-muted hidden md:table-cell">{fmtCurrency(tx.fee_native, tx.currency)}</td>
                      <td className={`text-right ${colorClass(tx.action === "SELL" ? 1 : -1)}`}>
                        {fmtCurrency(tx.action === "SELL" ? total : -total, tx.currency)}
                      </td>
                      <td className="text-bloomberg-muted hidden md:table-cell">{tx.currency}</td>
                      <td className="text-bloomberg-muted text-[10px] hidden lg:table-cell">{tx.comment || "—"}</td>
                      <td>
                        <button onClick={() => { if (confirm("Delete?")) delMut.mutate(tx.id); }}
                          className="text-bloomberg-muted hover:text-bloomberg-red">
                          <Trash2 size={11} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
