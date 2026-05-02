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
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {SECTORS.map(({ label, sector }) => {
                const data = sectorPnl[sector];
                const pnl = data?.pnl ?? null;
                const value = data?.value ?? 0;
                const pnlPct = data && value > 0 ? (data.pnl / (value - data.pnl)) * 100 : null;
                const intensity = Math.min(Math.abs(pnlPct ?? 0) / 10, 1);
                const bg = pnl == null ? "#111820"
                  : pnl > 0 ? `rgba(77,255,77,${intensity * 0.4})`
                  : `rgba(255,77,77,${intensity * 0.4})`;
                return (
                  <div key={sector} className="bbg-card text-center" style={{ background: bg }}>
                    <p className="text-bloomberg-muted text-[10px] uppercase">{label}</p>
                    {pnl != null ? (
                      <>
                        <p className={`text-lg font-bold ${colorClass(pnl)}`}>
                          {pnl >= 0 ? "+" : ""}{fmtCurrency(pnl, ccy)}
                        </p>
                        <p className={`text-xs font-medium ${colorClass(pnlPct)}`}>
                          {pnlPct != null ? fmtPct(pnlPct) : "—"}
                        </p>
                        <p className="text-bloomberg-muted text-[10px]">{fmtCurrency(value, ccy)} value</p>
                      </>
                    ) : (
                      <p className="text-bloomberg-muted text-sm mt-2">—</p>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-bloomberg-muted text-xs">Loading portfolio data…</p>
          )}
          {portfolio && (
            <div className="bbg-card">
              <p className="bbg-header">Sector Breakdown (Holdings)</p>
              <table className="bbg-table text-[10px]">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Sector</th>
                    <th className="text-right">Value</th>
                    <th className="text-right">P&L</th>
                    <th className="text-right">P&L%</th>
                  </tr>
                </thead>
                <tbody>
                  {[...portfolio.rows]
                    .sort((a, b) => (b.unrealized_pnl ?? 0) - (a.unrealized_pnl ?? 0))
                    .map((row) => (
                      <tr key={row.ticker}>
                        <td className="text-bloomberg-gold font-bold">{row.ticker}</td>
                        <td className="text-bloomberg-muted">{row.sector ?? "—"}</td>
                        <td className="text-right">{fmtCurrency(row.value_base, ccy)}</td>
                        <td className={`text-right font-medium ${colorClass(row.unrealized_pnl)}`}>
                          {row.unrealized_pnl != null
                            ? `${row.unrealized_pnl >= 0 ? "+" : ""}${fmtCurrency(row.unrealized_pnl, ccy)}`
                            : "—"}
                        </td>
                        <td className={`text-right font-medium ${colorClass(row.unrealized_pnl_pct)}`}>
                          {fmtPct(row.unrealized_pnl_pct ?? null)}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
