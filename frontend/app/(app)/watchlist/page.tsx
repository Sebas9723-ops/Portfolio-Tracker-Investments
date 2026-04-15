"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchWatchlist, addToWatchlist, removeFromWatchlist } from "@/lib/api/settings";
import { useMarketQuotes } from "@/lib/hooks/useMarketQuotes";
import { fmtCurrency, fmtPct, colorClass } from "@/lib/formatters";
import { Plus, Trash2 } from "lucide-react";

export default function WatchlistPage() {
  const { data: items, isLoading } = useQuery({ queryKey: ["watchlist"], queryFn: fetchWatchlist });
  const qc = useQueryClient();
  const [input, setInput] = useState("");

  const tickers = (items ?? []).map((i: { ticker: string }) => i.ticker);
  const { data: quotes } = useMarketQuotes(tickers);

  const addMut = useMutation({
    mutationFn: () => addToWatchlist(input.toUpperCase()),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["watchlist"] }); setInput(""); },
  });
  const delMut = useMutation({
    mutationFn: removeFromWatchlist,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  return (
    <div className="space-y-4">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Watchlist</h1>

      <div className="flex gap-2">
        <input value={input} onChange={(e) => setInput(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && input && addMut.mutate()}
          placeholder="Add ticker…"
          className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-3 py-1.5 text-xs w-32 focus:outline-none focus:border-bloomberg-gold" />
        <button onClick={() => input && addMut.mutate()}
          className="flex items-center gap-1 bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-3 py-1.5">
          <Plus size={11} /> ADD
        </button>
      </div>

      <div className="bbg-card">
        {isLoading ? (
          <div className="text-bloomberg-muted text-xs py-4">Loading…</div>
        ) : (
          <table className="bbg-table">
            <thead>
              <tr>
                <th>Ticker</th><th>Name</th>
                <th className="text-right">Price</th>
                <th className="text-right">Change</th>
                <th className="text-right">Change%</th>
                <th>Source</th><th></th>
              </tr>
            </thead>
            <tbody>
              {(items ?? []).map((item: { ticker: string; name?: string }) => {
                const q = quotes?.[item.ticker];
                return (
                  <tr key={item.ticker}>
                    <td className="text-bloomberg-gold font-medium">{item.ticker}</td>
                    <td className="text-bloomberg-muted">{item.name || "—"}</td>
                    <td className="text-right">{q ? fmtCurrency(q.price, q.currency) : "—"}</td>
                    <td className={`text-right ${colorClass(q?.change)}`}>{q?.change != null ? fmtCurrency(q.change, q.currency) : "—"}</td>
                    <td className={`text-right ${colorClass(q?.change_pct)}`}>{fmtPct(q?.change_pct ?? null)}</td>
                    <td className="text-bloomberg-muted text-[10px]">{q?.source || "—"}</td>
                    <td>
                      <button onClick={() => delMut.mutate(item.ticker)}
                        className="text-bloomberg-muted hover:text-bloomberg-red">
                        <Trash2 size={11} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
