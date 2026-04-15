"use client";
import { useMarketQuotes } from "@/lib/hooks/useMarketQuotes";
import { fmtCurrency, fmtPct, colorClass } from "@/lib/formatters";

const INDICES = [
  { ticker: "^GSPC", label: "S&P 500" },
  { ticker: "^NDX", label: "NASDAQ 100" },
  { ticker: "^DJI", label: "Dow Jones" },
  { ticker: "^RUT", label: "Russell 2000" },
  { ticker: "^STOXX50E", label: "Euro Stoxx 50" },
  { ticker: "^FTSE", label: "FTSE 100" },
  { ticker: "^N225", label: "Nikkei 225" },
  { ticker: "^VIX", label: "VIX" },
];
const FX = [
  { ticker: "EURUSD=X", label: "EUR/USD" },
  { ticker: "GBPUSD=X", label: "GBP/USD" },
  { ticker: "USDJPY=X", label: "USD/JPY" },
  { ticker: "USDCHF=X", label: "USD/CHF" },
];
const COMMODITIES = [
  { ticker: "GC=F", label: "Gold" },
  { ticker: "CL=F", label: "Crude Oil" },
  { ticker: "SI=F", label: "Silver" },
  { ticker: "BTC-USD", label: "Bitcoin" },
];
const RATES = [
  { ticker: "^IRX", label: "3M T-Bill" },
  { ticker: "^FVX", label: "5Y Treasury" },
  { ticker: "^TNX", label: "10Y Treasury" },
  { ticker: "^TYX", label: "30Y Treasury" },
];

function Section({ title, items, quotes }: { title: string; items: { ticker: string; label: string }[]; quotes: Record<string, { price: number; change_pct: number | null; currency: string }> | undefined }) {
  return (
    <div className="bbg-card">
      <p className="bbg-header">{title}</p>
      <table className="bbg-table">
        <thead><tr><th>Name</th><th className="text-right">Price</th><th className="text-right">Chg%</th></tr></thead>
        <tbody>
          {items.map(({ ticker, label }) => {
            const q = quotes?.[ticker];
            return (
              <tr key={ticker}>
                <td className="text-bloomberg-text">{label}</td>
                <td className="text-right">{q ? fmtCurrency(q.price, q.currency) : "—"}</td>
                <td className={`text-right ${colorClass(q?.change_pct)}`}>{fmtPct(q?.change_pct ?? null)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function MarketOverviewPage() {
  const allTickers = [...INDICES, ...FX, ...COMMODITIES, ...RATES].map((i) => i.ticker);
  const { data: quotes } = useMarketQuotes(allTickers);

  return (
    <div className="space-y-4">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Market Overview</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <Section title="Global Indices" items={INDICES} quotes={quotes as Record<string, { price: number; change_pct: number | null; currency: string }> | undefined} />
        <Section title="FX" items={FX} quotes={quotes as Record<string, { price: number; change_pct: number | null; currency: string }> | undefined} />
        <Section title="Commodities / Crypto" items={COMMODITIES} quotes={quotes as Record<string, { price: number; change_pct: number | null; currency: string }> | undefined} />
        <Section title="US Rates" items={RATES} quotes={quotes as Record<string, { price: number; change_pct: number | null; currency: string }> | undefined} />
      </div>
    </div>
  );
}
