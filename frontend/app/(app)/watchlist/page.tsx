"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchWatchlist, addToWatchlist, removeFromWatchlist } from "@/lib/api/settings";
import { useMarketQuotes } from "@/lib/hooks/useMarketQuotes";
import { fmtCurrency, fmtPct, colorClass } from "@/lib/formatters";
import { Plus, Trash2 } from "lucide-react";

const PRESETS: Record<string, { ticker: string; name: string }[]> = {
  Indices: [
    { ticker: "^GSPC", name: "S&P 500" },
    { ticker: "^NDX", name: "NASDAQ 100" },
    { ticker: "^DJI", name: "Dow Jones" },
    { ticker: "^RUT", name: "Russell 2000" },
    { ticker: "^STOXX50E", name: "Euro Stoxx 50" },
    { ticker: "^FTSE", name: "FTSE 100" },
    { ticker: "^N225", name: "Nikkei 225" },
    { ticker: "^VIX", name: "VIX" },
  ],
  FX: [
    { ticker: "EURUSD=X", name: "EUR/USD" },
    { ticker: "GBPUSD=X", name: "GBP/USD" },
    { ticker: "USDJPY=X", name: "USD/JPY" },
    { ticker: "USDCHF=X", name: "USD/CHF" },
    { ticker: "USDCOP=X", name: "USD/COP" },
    { ticker: "USDAUD=X", name: "USD/AUD" },
  ],
  Commodities: [
    { ticker: "GC=F", name: "Gold" },
    { ticker: "SI=F", name: "Silver" },
    { ticker: "CL=F", name: "Crude Oil" },
    { ticker: "NG=F", name: "Natural Gas" },
    { ticker: "HG=F", name: "Copper" },
  ],
  Crypto: [
    { ticker: "BTC-USD", name: "Bitcoin" },
    { ticker: "ETH-USD", name: "Ethereum" },
    { ticker: "SOL-USD", name: "Solana" },
  ],
  Rates: [
    { ticker: "^IRX", name: "3M T-Bill" },
    { ticker: "^FVX", name: "5Y Treasury" },
    { ticker: "^TNX", name: "10Y Treasury" },
    { ticker: "^TYX", name: "30Y Treasury" },
  ],
};

export default function WatchlistPage() {
  const { data: items, isLoading } = useQuery({ queryKey: ["watchlist"], queryFn: fetchWatchlist });
  const qc = useQueryClient();
  const [input, setInput] = useState("");

  const tickers = (items ?? []).map((i: { ticker: string }) => i.ticker);
  const { data: quotes } = useMarketQuotes(tickers);

  const addMut = useMutation({
    mutationFn: (payload: { ticker: string; name?: string }) => addToWatchlist(payload.ticker, payload.name),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["watchlist"] }); setInput(""); },
  });
  const delMut = useMutation({
    mutationFn: removeFromWatchlist,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const existingTickers = new Set(tickers);

  const addPreset = (group: string) => {
    const toAdd = PRESETS[group].filter((p) => !existingTickers.has(p.ticker));
    toAdd.forEach((p) => addMut.mutate({ ticker: p.ticker, name: p.name }));
  };

  return (
    <div className="space-y-4">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Watchlist</h1>

      {/* Add + Presets */}
      <div className="flex flex-wrap gap-2 items-center">
        <input value={input} onChange={(e) => setInput(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && input && addMut.mutate({ ticker: input })}
          placeholder="Add ticker…"
          className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-3 py-1.5 text-xs w-32 focus:outline-none focus:border-bloomberg-gold" />
        <button onClick={() => input && addMut.mutate({ ticker: input })}
          className="flex items-center gap-1 bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-3 py-1.5">
          <Plus size={11} /> ADD
        </button>
        <div className="border-l border-bloomberg-border pl-2 flex gap-1 flex-wrap">
          <span className="text-bloomberg-muted text-[10px] self-center">Presets:</span>
          {Object.keys(PRESETS).map((group) => (
            <button key={group} onClick={() => addPreset(group)}
              className="text-[10px] px-2 py-1 border border-bloomberg-border text-bloomberg-muted hover:border-bloomberg-gold hover:text-bloomberg-gold">
              + {group}
            </button>
          ))}
        </div>
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
              {(!items || items.length === 0) && (
                <tr><td colSpan={7} className="text-bloomberg-muted text-center py-4 text-xs">No tickers. Add one or load a preset.</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
