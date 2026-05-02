"use client";
import { useState } from "react";
import { useMarketQuotes } from "@/lib/hooks/useMarketQuotes";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { fmtPct, fmtCurrency, colorClass } from "@/lib/formatters";

const SECTORS = [
  { ticker: "XLK",  label: "Technology",        sector: "Technology" },
  { ticker: "XLF",  label: "Financials",         sector: "Financial Services" },
  { ticker: "XLV",  label: "Healthcare",          sector: "Healthcare" },
  { ticker: "XLC",  label: "Communication",       sector: "Communication Services" },
  { ticker: "XLY",  label: "Consumer Discr.",     sector: "Consumer Cyclical" },
  { ticker: "XLP",  label: "Consumer Staples",    sector: "Consumer Defensive" },
  { ticker: "XLI",  label: "Industrials",         sector: "Industrials" },
  { ticker: "XLE",  label: "Energy",              sector: "Energy" },
  { ticker: "XLU",  label: "Utilities",           sector: "Utilities" },
  { ticker: "XLRE", label: "Real Estate",         sector: "Real Estate" },
  { ticker: "XLB",  label: "Materials",           sector: "Basic Materials" },
];

export default function SectorHeatmapPage() {
  const [mode, setMode] = useState<"market" | "pnl">("market");
  const tickers = SECTORS.map((s) => s.ticker);
  const { data: quotes } = useMarketQuotes(tickers);
  const { data: portfolio } = usePortfolio();

  // Aggregate portfolio P&L by sector
  const sectorPnl: Record<string, { pnl: number; value: number }> = {};
  if (portfolio?.rows) {
    for (const row of portfolio.rows) {
      const sec = row.sector ?? "Unknown";
      if (!sectorPnl[sec]) sectorPnl[sec] = { pnl: 0, value: 0 };
      sectorPnl[sec].pnl += row.unrealized_pnl ?? 0;
      sectorPnl[sec].value += row.value_base ?? 0;
    }
  }

  const ccy = portfolio?.base_currency ?? "USD";

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Sector Heatmap</h1>
        <div className="flex gap-1">
          {(["market", "pnl"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`text-[10px] px-3 py-1 border transition-colors ${
                mode === m ? "border-bloomberg-gold text-bloomberg-gold" : "border-bloomberg-border text-bloomberg-muted hover:border-bloomberg-muted"
              }`}
            >
              {m === "market" ? "Market 1D%" : "Portfolio P&L"}
            </button>
          ))}
        </div>
      </div>

      {mode === "market" ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {SECTORS.map(({ ticker, label }) => {
            const q = quotes?.[ticker];
            const pct = q?.change_pct ?? null;
            const intensity = Math.min(Math.abs(pct ?? 0) / 5, 1);
            const bg = pct == null ? "#111820"
              : pct > 0 ? `rgba(77,255,77,${intensity * 0.4})`
              : `rgba(255,77,77,${intensity * 0.4})`;
            return (
              <div key={ticker} className="bbg-card text-center" style={{ background: bg }}>
                <p className="text-bloomberg-muted text-[10px] uppercase">{label}</p>
                <p className="text-bloomberg-gold text-xs font-medium">{ticker}</p>
                <p className={`text-lg font-bold ${colorClass(pct)}`}>{fmtPct(pct)}</p>
                {q && <p className="text-bloomberg-muted text-[10px]">${q.price.toFixed(2)}</p>}
              </div>
            );
          })}
        </div>
      ) : (
        <>
          {portfolio ? (
            // P&L heatmap: one tile per portfolio holding (not SPDR sectors,
            // since holdings are diversified ETFs that don't map to single sectors)
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[...portfolio.rows]
                .sort((a, b) => (b.value_base ?? 0) - (a.value_base ?? 0))
                .map((row) => {
                  const pnl = row.unrealized_pnl ?? null;
                  const pnlPct = row.unrealized_pnl_pct ?? null;
                  const intensity = Math.min(Math.abs(pnlPct ?? 0) / 15, 1);
                  const bg = pnl == null ? "#111820"
                    : pnl > 0 ? `rgba(77,255,77,${0.08 + intensity * 0.32})`
                    : `rgba(255,77,77,${0.08 + intensity * 0.32})`;
                  return (
                    <div key={row.ticker} className="bbg-card text-center py-4" style={{ background: bg }}>
                      <p className="text-bloomberg-gold font-bold text-sm">{row.ticker}</p>
                      <p className="text-bloomberg-muted text-[10px] truncate">{row.name}</p>
                      <p className={`text-xl font-black mt-1 ${colorClass(pnlPct)}`}>
                        {pnlPct != null ? `${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%` : "—"}
                      </p>
                      {pnl != null && (
                        <p className={`text-xs font-medium ${colorClass(pnl)}`}>
                          {pnl >= 0 ? "+" : ""}{fmtCurrency(pnl, ccy)}
                        </p>
                      )}
                      <p className="text-bloomberg-muted text-[10px] mt-1">{fmtCurrency(row.value_base, ccy)}</p>
                    </div>
                  );
                })}
            </div>
          ) : (
            <p className="text-bloomberg-muted text-xs">Loading portfolio data…</p>
          )}
        </>
      )}
    </div>
  );
}
