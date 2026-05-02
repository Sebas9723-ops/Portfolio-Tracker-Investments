"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchFundamentals, fetchInsiderTransactions, fetchAnalystRatings } from "@/lib/api/settings";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { MetricCard } from "@/components/shared/MetricCard";
import { fmtCurrency, fmtPct, fmtNumber } from "@/lib/formatters";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

const REC_COLORS: Record<string, string> = {
  "strong_buy": "#22c55e", "buy": "#4dff4d", "hold": "#f3a712",
  "sell": "#fb923c", "strong_sell": "#ef4444",
};
const REC_LABELS: Record<string, string> = {
  "strong_buy": "Strong Buy", "buy": "Buy", "hold": "Hold",
  "sell": "Sell", "strong_sell": "Strong Sell",
};

export default function FundamentalsPage() {
  const [ticker, setTicker] = useState("VOO");
  const [input, setInput] = useState("VOO");
  const { data: portfolio } = usePortfolio();
  const allTracked = [
    ...(portfolio?.rows.map((r) => r.ticker) ?? []),
    ...(portfolio?.pending_tickers ?? []),
  ];

  const { data, isLoading } = useQuery({
    queryKey: ["fundamentals", ticker],
    queryFn: () => fetchFundamentals(ticker),
    enabled: !!ticker,
  });

  const { data: insiders } = useQuery({
    queryKey: ["insiders", ticker],
    queryFn: () => fetchInsiderTransactions(ticker),
    enabled: !!ticker,
    staleTime: 60 * 60 * 1000,
  });

  const { data: analystData } = useQuery({
    queryKey: ["analyst-ratings", ticker],
    queryFn: () => fetchAnalystRatings(ticker),
    enabled: !!ticker,
    staleTime: 60 * 60 * 1000,
  });

  const submit = () => { if (input) { setTicker(input.toUpperCase()); } };

  const recKey = analystData?.recommendation_key ?? "";
  const recColor = REC_COLORS[recKey] ?? "#8a9bb5";
  const recLabel = REC_LABELS[recKey] ?? recKey?.replace("_", " ")?.toUpperCase() ?? "—";

  // Build stacked bar for analyst consensus breakdown (latest rec_history entry)
  const latestRec = analystData?.rec_history?.[0];
  const consensusData = latestRec ? [
    { label: "Strong Buy", value: latestRec.strong_buy, color: "#22c55e" },
    { label: "Buy",        value: latestRec.buy,        color: "#4dff4d" },
    { label: "Hold",       value: latestRec.hold,       color: "#f3a712" },
    { label: "Sell",       value: latestRec.sell,       color: "#fb923c" },
    { label: "Strong Sell",value: latestRec.strong_sell,color: "#ef4444" },
  ].filter((d) => d.value > 0) : [];

  return (
    <div className="space-y-4">
      {/* Ticker input */}
      <div className="space-y-2">
        <div className="flex items-center gap-3">
          <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Fundamentals</h1>
          <input value={input} onChange={(e) => setInput(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === "Enter" && submit()} placeholder="Ticker…"
            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs w-24 focus:outline-none focus:border-bloomberg-gold" />
          <button onClick={submit} className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-3 py-1">GO</button>
        </div>
        {allTracked.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {allTracked.map((t) => (
              <button key={t} onClick={() => { setTicker(t); setInput(t); }}
                className={`text-[10px] px-2 py-0.5 border transition-colors ${
                  ticker === t ? "border-bloomberg-gold text-bloomberg-gold" : "border-bloomberg-border text-bloomberg-muted hover:border-bloomberg-muted"
                }`}>{t}</button>
            ))}
          </div>
        )}
      </div>

      {isLoading && <div className="text-bloomberg-muted text-xs">Loading…</div>}

      {data && (
        <>
          {/* Header */}
          <div className="bbg-card">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div>
                <p className="text-bloomberg-gold font-bold text-sm">{data.longName || ticker}</p>
                <p className="text-bloomberg-muted text-[10px]">{data.sector} · {data.industry}</p>
                {data.longBusinessSummary && (
                  <p className="text-bloomberg-muted text-[10px] mt-2 leading-relaxed line-clamp-3">{data.longBusinessSummary}</p>
                )}
              </div>
              {/* Analyst consensus badge */}
              {recKey && (
                <div className="border px-3 py-2 text-center min-w-[90px]" style={{ borderColor: recColor }}>
                  <p className="text-[9px] text-bloomberg-muted uppercase tracking-widest">Consensus</p>
                  <p className="font-bold text-sm mt-0.5" style={{ color: recColor }}>{recLabel}</p>
                  {analystData?.n_analysts && (
                    <p className="text-bloomberg-muted text-[9px]">{analystData.n_analysts} analysts</p>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Valuation metrics */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <MetricCard label="Market Cap" value={data.marketCap ? fmtCurrency(data.marketCap, "USD", true) : "—"} />
            <MetricCard label="Trailing P/E" value={data.trailingPE?.toFixed(1) ?? "—"} />
            <MetricCard label="Forward P/E" value={data.forwardPE?.toFixed(1) ?? "—"} />
            <MetricCard label="P/B Ratio" value={data.priceToBook?.toFixed(2) ?? "—"} />
            <MetricCard label="Div Yield" value={data.dividendYield != null ? fmtPct(data.dividendYield) : "—"} />
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

          {/* Short interest + volume row */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <MetricCard label="Short Float" value={data.shortPercentOfFloat != null ? fmtPct(data.shortPercentOfFloat * 100) : "—"} />
            <MetricCard label="Short Ratio" value={data.shortRatio?.toFixed(1) ?? "—"} sub="days to cover" />
            <MetricCard label="Shares Short" value={data.sharesShort ? fmtNumber(data.sharesShort, 0) : "—"} />
            <MetricCard label="Rel. Volume" value={data.relative_volume != null ? `${data.relative_volume}x` : "—"} />
            <MetricCard label="Avg Volume" value={data.averageVolume ? fmtNumber(data.averageVolume, 0) : "—"} />
          </div>

          {/* 52W range */}
          {data.fiftyTwoWeekHigh && data.fiftyTwoWeekLow && (
            <div className="bbg-card">
              <p className="bbg-header">52-Week Range</p>
              <div className="flex items-center gap-3 mt-1">
                <span className="text-red-400 text-[10px] font-bold">{data.fiftyTwoWeekLow?.toFixed(2)}</span>
                <div className="flex-1 h-2 bg-bloomberg-border rounded-full overflow-hidden">
                  {(() => {
                    const lo = data.fiftyTwoWeekLow ?? 0;
                    const hi = data.fiftyTwoWeekHigh ?? 1;
                    const cur = data.fiftyDayAverage ?? ((lo + hi) / 2);
                    const pct = Math.max(0, Math.min(100, ((cur - lo) / (hi - lo)) * 100));
                    return <div className="h-full bg-bloomberg-gold rounded-full" style={{ width: `${pct}%` }} />;
                  })()}
                </div>
                <span className="text-green-400 text-[10px] font-bold">{data.fiftyTwoWeekHigh?.toFixed(2)}</span>
              </div>
              <div className="flex gap-6 mt-2 text-[10px]">
                <span className="text-bloomberg-muted">SMA50: <span className="text-bloomberg-text">{data.fiftyDayAverage?.toFixed(2) ?? "—"}</span></span>
                <span className="text-bloomberg-muted">SMA200: <span className="text-bloomberg-text">{data.twoHundredDayAverage?.toFixed(2) ?? "—"}</span></span>
              </div>
            </div>
          )}
        </>
      )}

      {/* Analyst Ratings */}
      {analystData && (analystData.target_mean || analystData.upgrades.length > 0) && (
        <div className="bbg-card">
          <p className="bbg-header">Analyst Ratings &amp; Price Targets</p>

          {/* Target price summary */}
          {analystData.target_mean && analystData.current_price && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <div className="border border-bloomberg-border p-2">
                <p className="text-bloomberg-muted text-[9px] uppercase">Target (Mean)</p>
                <p className="text-bloomberg-gold font-bold text-sm">${analystData.target_mean.toFixed(2)}</p>
                {analystData.current_price && (
                  <p className={`text-[10px] font-medium ${analystData.target_mean > analystData.current_price ? "text-green-400" : "text-red-400"}`}>
                    {analystData.target_mean > analystData.current_price ? "+" : ""}{((analystData.target_mean / analystData.current_price - 1) * 100).toFixed(1)}% upside
                  </p>
                )}
              </div>
              <div className="border border-bloomberg-border p-2">
                <p className="text-bloomberg-muted text-[9px] uppercase">Target High</p>
                <p className="text-green-400 font-bold text-sm">{analystData.target_high ? `$${analystData.target_high.toFixed(2)}` : "—"}</p>
              </div>
              <div className="border border-bloomberg-border p-2">
                <p className="text-bloomberg-muted text-[9px] uppercase">Target Low</p>
                <p className="text-red-400 font-bold text-sm">{analystData.target_low ? `$${analystData.target_low.toFixed(2)}` : "—"}</p>
              </div>
              <div className="border border-bloomberg-border p-2">
                <p className="text-bloomberg-muted text-[9px] uppercase">Analysts</p>
                <p className="text-bloomberg-text font-bold text-sm">{analystData.n_analysts ?? "—"}</p>
              </div>
            </div>
          )}

          {/* Consensus bar chart */}
          {consensusData.length > 0 && (
            <div className="mb-4">
              <p className="text-bloomberg-muted text-[9px] uppercase mb-2">Analyst Distribution</p>
              <ResponsiveContainer width="100%" height={80}>
                <BarChart data={consensusData} layout="vertical" margin={{ top: 0, right: 40, bottom: 0, left: 70 }}>
                  <XAxis type="number" tick={{ fontSize: 8, fill: "#8a9bb5" }} />
                  <YAxis type="category" dataKey="label" tick={{ fontSize: 9, fill: "#8a9bb5" }} width={65} />
                  <Tooltip contentStyle={{ background: "#0b0f14", border: "1px solid #1e2535", fontSize: 10 }} />
                  <Bar dataKey="value" radius={[0, 2, 2, 0]}>
                    {consensusData.map((d) => <Cell key={d.label} fill={d.color} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Recent upgrades/downgrades */}
          {analystData.upgrades.length > 0 && (
            <div>
              <p className="text-bloomberg-muted text-[9px] uppercase mb-2">Recent Rating Changes</p>
              <table className="bbg-table text-[10px]">
                <thead>
                  <tr><th>Date</th><th>Firm</th><th>From</th><th>To</th><th>Action</th></tr>
                </thead>
                <tbody>
                  {analystData.upgrades.slice(0, 10).map((u, i) => (
                    <tr key={i}>
                      <td className="text-bloomberg-muted">{u.date}</td>
                      <td className="font-medium">{u.firm}</td>
                      <td className="text-bloomberg-muted">{u.from_grade || "—"}</td>
                      <td className={u.is_upgrade ? "text-green-400 font-bold" : "text-red-400 font-bold"}>{u.to_grade}</td>
                      <td className={`text-[9px] uppercase font-bold ${u.is_upgrade ? "text-green-400" : "text-red-400"}`}>{u.action}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Insider Transactions */}
      {insiders && insiders.transactions.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Insider Transactions</p>
          <table className="bbg-table text-[10px]">
            <thead>
              <tr><th>Date</th><th>Insider</th><th>Title</th><th>Transaction</th><th className="text-right">Shares</th><th className="text-right">Value</th></tr>
            </thead>
            <tbody>
              {insiders.transactions.slice(0, 15).map((tx, i) => (
                <tr key={i}>
                  <td className="text-bloomberg-muted">{tx.date}</td>
                  <td className="font-medium max-w-[120px] truncate">{tx.insider}</td>
                  <td className="text-bloomberg-muted text-[9px] max-w-[100px] truncate">{tx.title}</td>
                  <td className={`font-bold ${tx.is_buy ? "text-green-400" : "text-red-400"}`}>{tx.transaction}</td>
                  <td className="text-right">{tx.shares ? fmtNumber(tx.shares) : "—"}</td>
                  <td className="text-right text-bloomberg-muted">{tx.value ? fmtCurrency(tx.value, "USD", true) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
