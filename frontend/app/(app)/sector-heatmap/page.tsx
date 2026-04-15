"use client";
import { useMarketQuotes } from "@/lib/hooks/useMarketQuotes";
import { fmtPct, colorClass } from "@/lib/formatters";

const SECTORS = [
  { ticker: "XLK", label: "Technology" },
  { ticker: "XLF", label: "Financials" },
  { ticker: "XLV", label: "Healthcare" },
  { ticker: "XLC", label: "Communication" },
  { ticker: "XLY", label: "Consumer Discr." },
  { ticker: "XLP", label: "Consumer Staples" },
  { ticker: "XLI", label: "Industrials" },
  { ticker: "XLE", label: "Energy" },
  { ticker: "XLU", label: "Utilities" },
  { ticker: "XLRE", label: "Real Estate" },
  { ticker: "XLB", label: "Materials" },
];

export default function SectorHeatmapPage() {
  const tickers = SECTORS.map((s) => s.ticker);
  const { data: quotes } = useMarketQuotes(tickers);

  return (
    <div className="space-y-4">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Sector Heatmap (SPDR ETFs)</h1>
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
              <p className={`text-lg font-bold ${colorClass(pct)}`}>
                {fmtPct(pct)}
              </p>
              {q && <p className="text-bloomberg-muted text-[10px]">${q.price.toFixed(2)}</p>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
