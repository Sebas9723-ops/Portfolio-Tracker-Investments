"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchFundamentals } from "@/lib/api/settings";
import { MetricCard } from "@/components/shared/MetricCard";
import { fmtCurrency, fmtPct, fmtNumber } from "@/lib/formatters";

export default function FundamentalsPage() {
  const [ticker, setTicker] = useState("VOO");
  const [input, setInput] = useState("VOO");

  const { data, isLoading } = useQuery({
    queryKey: ["fundamentals", ticker],
    queryFn: () => fetchFundamentals(ticker),
    enabled: !!ticker,
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Fundamentals</h1>
        <input value={input} onChange={(e) => setInput(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && setTicker(input)}
          placeholder="Ticker…"
          className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs w-24 focus:outline-none focus:border-bloomberg-gold" />
        <button onClick={() => setTicker(input)}
          className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-3 py-1">GO</button>
      </div>

      {isLoading && <div className="text-bloomberg-muted text-xs">Loading…</div>}

      {data && (
        <>
          <div className="bbg-card">
            <p className="text-bloomberg-gold font-bold text-sm">{data.longName || ticker}</p>
            <p className="text-bloomberg-muted text-[10px]">{data.sector} · {data.industry}</p>
            {data.longBusinessSummary && (
              <p className="text-bloomberg-muted text-[10px] mt-2 leading-relaxed line-clamp-3">{data.longBusinessSummary}</p>
            )}
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <MetricCard label="Market Cap" value={data.marketCap ? fmtCurrency(data.marketCap, "USD", true) : "—"} />
            <MetricCard label="Trailing P/E" value={data.trailingPE?.toFixed(1) ?? "—"} />
            <MetricCard label="Forward P/E" value={data.forwardPE?.toFixed(1) ?? "—"} />
            <MetricCard label="P/B Ratio" value={data.priceToBook?.toFixed(2) ?? "—"} />
            <MetricCard label="Div Yield" value={data.dividendYield != null ? fmtPct(data.dividendYield * 100) : "—"} />
            <MetricCard label="Beta" value={data.beta?.toFixed(2) ?? "—"} />
            <MetricCard label="ROE" value={data.returnOnEquity != null ? fmtPct(data.returnOnEquity * 100) : "—"} />
            <MetricCard label="ROA" value={data.returnOnAssets != null ? fmtPct(data.returnOnAssets * 100) : "—"} />
            <MetricCard label="Gross Margin" value={data.grossMargins != null ? fmtPct(data.grossMargins * 100) : "—"} />
            <MetricCard label="Profit Margin" value={data.profitMargins != null ? fmtPct(data.profitMargins * 100) : "—"} />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <MetricCard label="Revenue" value={data.totalRevenue ? fmtCurrency(data.totalRevenue, "USD", true) : "—"} />
            <MetricCard label="Net Income" value={data.netIncomeToCommon ? fmtCurrency(data.netIncomeToCommon, "USD", true) : "—"} />
            <MetricCard label="Free Cash Flow" value={data.freeCashflow ? fmtCurrency(data.freeCashflow, "USD", true) : "—"} />
            <MetricCard label="Total Debt" value={data.totalDebt ? fmtCurrency(data.totalDebt, "USD", true) : "—"} />
            <MetricCard label="Cash" value={data.totalCash ? fmtCurrency(data.totalCash, "USD", true) : "—"} />
            <MetricCard label="Book Value" value={data.bookValue?.toFixed(2) ?? "—"} sub="per share" />
          </div>
        </>
      )}
    </div>
  );
}
