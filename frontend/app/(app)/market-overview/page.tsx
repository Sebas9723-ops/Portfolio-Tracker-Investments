"use client";
import { useQuery } from "@tanstack/react-query";
import { useMarketQuotes } from "@/lib/hooks/useMarketQuotes";
import { fetchMarketBreadth, fetchEarningsCalendar } from "@/lib/api/market";
import { fmtCurrency, fmtPct, colorClass } from "@/lib/formatters";

const INDICES = [
  { ticker: "^GSPC",    label: "S&P 500" },
  { ticker: "^NDX",     label: "NASDAQ 100" },
  { ticker: "^DJI",     label: "Dow Jones" },
  { ticker: "^RUT",     label: "Russell 2000" },
  { ticker: "^STOXX50E",label: "Euro Stoxx 50" },
  { ticker: "^FTSE",    label: "FTSE 100" },
  { ticker: "^N225",    label: "Nikkei 225" },
  { ticker: "^VIX",     label: "VIX" },
];

const FX = [
  { ticker: "EURUSD=X", label: "EUR/USD" },
  { ticker: "GBPUSD=X", label: "GBP/USD" },
  { ticker: "USDJPY=X", label: "USD/JPY" },
  { ticker: "USDCHF=X", label: "USD/CHF" },
  { ticker: "USDCAD=X", label: "USD/CAD" },
  { ticker: "AUDUSD=X", label: "AUD/USD" },
  { ticker: "NZDUSD=X", label: "NZD/USD" },
  { ticker: "USDCOP=X", label: "USD/COP" },
];

const COMMODITIES = [
  { ticker: "GC=F",  label: "Gold" },
  { ticker: "SI=F",  label: "Silver" },
  { ticker: "CL=F",  label: "Crude Oil WTI" },
  { ticker: "BZ=F",  label: "Brent Crude" },
  { ticker: "NG=F",  label: "Natural Gas" },
  { ticker: "HG=F",  label: "Copper" },
  { ticker: "PL=F",  label: "Platinum" },
];

const RATES = [
  { ticker: "^IRX", label: "3M T-Bill" },
  { ticker: "^FVX", label: "5Y Treasury" },
  { ticker: "^TNX", label: "10Y Treasury" },
  { ticker: "^TYX", label: "30Y Treasury" },
];

const FUTURES = [
  { ticker: "ES=F",  label: "S&P 500 Futures" },
  { ticker: "NQ=F",  label: "Nasdaq Futures" },
  { ticker: "YM=F",  label: "DJIA Futures" },
  { ticker: "RTY=F", label: "Russell Futures" },
  { ticker: "ZB=F",  label: "30Y Bond Futures" },
  { ticker: "ZN=F",  label: "10Y Note Futures" },
  { ticker: "VX=F",  label: "VIX Futures" },
  { ticker: "ZC=F",  label: "Corn" },
  { ticker: "ZS=F",  label: "Soybeans" },
  { ticker: "ZW=F",  label: "Wheat" },
];

function Section({ title, items, quotes }: {
  title: string;
  items: { ticker: string; label: string }[];
  quotes: Record<string, { price: number; change_pct: number | null; currency: string }> | undefined;
}) {
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

function BreadthBar({ value, max, color }: { value: number; max: number; color: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-bloomberg-border rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${Math.min(100, (value / max) * 100)}%`, background: color }} />
      </div>
      <span className="text-bloomberg-text text-[10px] font-bold w-8 text-right">{value}</span>
    </div>
  );
}

export default function MarketOverviewPage() {
  const allTickers = [...INDICES, ...FX, ...COMMODITIES, ...RATES, ...FUTURES].map((i) => i.ticker);
  const { data: quotes } = useMarketQuotes(allTickers);
  const q = quotes as Record<string, { price: number; change_pct: number | null; currency: string }> | undefined;

  const { data: breadth, isLoading: breadthLoading } = useQuery({
    queryKey: ["market-breadth"],
    queryFn: fetchMarketBreadth,
    staleTime: 5 * 60 * 1000,
  });

  const { data: earnings } = useQuery({
    queryKey: ["earnings-calendar", 14],
    queryFn: () => fetchEarningsCalendar(14),
    staleTime: 60 * 60 * 1000,
  });

  return (
    <div className="space-y-4">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Market Overview</h1>

      {/* ── Market Breadth ── */}
      <div className="bbg-card">
        <div className="flex items-center justify-between mb-3">
          <p className="bbg-header mb-0">Market Breadth</p>
          {breadthLoading && <span className="text-bloomberg-muted text-[9px]">Computing…</span>}
          {breadth && <span className="text-bloomberg-muted text-[9px]">Universe: {breadth.universe_size} stocks</span>}
        </div>
        {breadth ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Advancing / Declining */}
            <div className="space-y-2">
              <p className="text-bloomberg-muted text-[9px] uppercase tracking-widest">Advancing / Declining</p>
              <div className="space-y-1">
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-green-400">Advancing</span>
                  <span className="text-green-400 font-bold">{breadth.advancing} ({breadth.advancing_pct}%)</span>
                </div>
                <BreadthBar value={breadth.advancing} max={breadth.universe_size} color="#4dff4d" />
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-red-400">Declining</span>
                  <span className="text-red-400 font-bold">{breadth.declining} ({breadth.declining_pct}%)</span>
                </div>
                <BreadthBar value={breadth.declining} max={breadth.universe_size} color="#ef4444" />
              </div>
            </div>

            {/* SMA Breadth */}
            <div className="space-y-2">
              <p className="text-bloomberg-muted text-[9px] uppercase tracking-widest">Above Moving Averages</p>
              <div className="space-y-1">
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-bloomberg-text">Above SMA50</span>
                  <span className="text-bloomberg-gold font-bold">{breadth.above_sma50} ({breadth.above_sma50_pct}%)</span>
                </div>
                <BreadthBar value={breadth.above_sma50} max={breadth.universe_size} color="#f3a712" />
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-bloomberg-text">Above SMA200</span>
                  <span className="text-bloomberg-gold font-bold">{breadth.above_sma200} ({breadth.above_sma200_pct}%)</span>
                </div>
                <BreadthBar value={breadth.above_sma200} max={breadth.universe_size} color="#f3a712" />
              </div>
            </div>
          </div>
        ) : !breadthLoading ? (
          <p className="text-bloomberg-muted text-[10px]">Click to load breadth data.</p>
        ) : (
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => <div key={i} className="h-5 bg-bloomberg-border/30 animate-pulse rounded" />)}
          </div>
        )}

        {/* Top Gainers / Losers */}
        {breadth && (breadth.top_gainers.length > 0 || breadth.top_losers.length > 0) && (
          <div className="grid grid-cols-2 gap-4 mt-4">
            <div>
              <p className="text-bloomberg-muted text-[9px] uppercase tracking-widest mb-1">Top Gainers</p>
              {breadth.top_gainers.map((r) => (
                <div key={r.ticker} className="flex justify-between text-[10px] py-0.5">
                  <span className="text-bloomberg-gold font-bold">{r.ticker}</span>
                  <span className="text-green-400 font-bold">+{r.change_pct.toFixed(2)}%</span>
                </div>
              ))}
            </div>
            <div>
              <p className="text-bloomberg-muted text-[9px] uppercase tracking-widest mb-1">Top Losers</p>
              {breadth.top_losers.map((r) => (
                <div key={r.ticker} className="flex justify-between text-[10px] py-0.5">
                  <span className="text-bloomberg-gold font-bold">{r.ticker}</span>
                  <span className="text-red-400 font-bold">{r.change_pct.toFixed(2)}%</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Unusual Volume / Relative Volume ── */}
      {breadth && breadth.rel_vol_leaders.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Unusual Volume (Relative Volume &gt; 1.5×)</p>
          <div className="overflow-x-auto">
            <table className="bbg-table text-[10px]">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th className="text-right">Price</th>
                  <th className="text-right">1D%</th>
                  <th className="text-right">Rel. Volume</th>
                </tr>
              </thead>
              <tbody>
                {breadth.rel_vol_leaders.map((r) => (
                  <tr key={r.ticker}>
                    <td className="text-bloomberg-gold font-bold">{r.ticker}</td>
                    <td className="text-right">${r.price.toFixed(2)}</td>
                    <td className={`text-right font-medium ${colorClass(r.change_pct)}`}>
                      {r.change_pct >= 0 ? "+" : ""}{r.change_pct.toFixed(2)}%
                    </td>
                    <td className={`text-right font-bold ${(r.rel_vol ?? 0) >= 3 ? "text-red-400" : "text-bloomberg-gold"}`}>
                      {r.rel_vol?.toFixed(1)}×
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Main sections grid ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <Section title="Global Indices" items={INDICES} quotes={q} />
        <Section title="FX" items={FX} quotes={q} />
        <Section title="Commodities" items={COMMODITIES} quotes={q} />
        <Section title="US Rates" items={RATES} quotes={q} />
      </div>

      {/* ── Futures ── */}
      <div className="bbg-card">
        <p className="bbg-header">Futures</p>
        <div className="overflow-x-auto">
          <table className="bbg-table text-[10px]">
            <thead>
              <tr><th>Contract</th><th className="text-right">Price</th><th className="text-right">Chg%</th></tr>
            </thead>
            <tbody>
              {FUTURES.map(({ ticker, label }) => {
                const fq = q?.[ticker];
                return (
                  <tr key={ticker}>
                    <td className="text-bloomberg-text">{label} <span className="text-bloomberg-muted text-[9px]">{ticker}</span></td>
                    <td className="text-right">{fq ? fmtCurrency(fq.price, fq.currency) : "—"}</td>
                    <td className={`text-right font-medium ${colorClass(fq?.change_pct)}`}>{fmtPct(fq?.change_pct ?? null)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Upcoming Earnings ── */}
      {earnings && earnings.events.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Upcoming Earnings — Next {earnings.days_ahead} Days</p>
          <div className="overflow-x-auto">
            <table className="bbg-table text-[10px]">
              <thead>
                <tr>
                  <th>Date</th><th>Ticker</th><th>Company</th><th>Sector</th>
                  <th className="text-right">Mkt Cap (B)</th>
                  <th className="text-right">EPS Est.</th>
                </tr>
              </thead>
              <tbody>
                {earnings.events.map((e, i) => (
                  <tr key={i}>
                    <td className="text-bloomberg-gold font-medium">{e.earnings_date}</td>
                    <td className="text-bloomberg-gold font-bold">{e.ticker}</td>
                    <td className="text-bloomberg-muted max-w-[140px] truncate">{e.name}</td>
                    <td className="text-bloomberg-muted text-[9px]">{e.sector}</td>
                    <td className="text-right">{e.market_cap_b > 0 ? `$${e.market_cap_b.toFixed(1)}B` : "—"}</td>
                    <td className="text-right text-bloomberg-muted">{e.eps_estimate != null ? e.eps_estimate.toFixed(2) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
