"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchHistorical, fetchQuote } from "@/lib/api/market";
import { fetchFundamentals, fetchNews } from "@/lib/api/settings";
import { MetricCard } from "@/components/shared/MetricCard";
import { fmtCurrency, fmtPct, fmtNumber, fmtDateTime } from "@/lib/formatters";
import { colorClass } from "@/lib/formatters";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, Legend,
} from "recharts";
import { ExternalLink } from "lucide-react";

function monteCarlo1Y(
  price: number, vol: number, ret: number, nPaths = 300,
) {
  const months = 12;
  const mu = ret / 12;
  const sigma = vol / Math.sqrt(12);
  const paths = Array.from({ length: nPaths }, () => {
    const path = [price];
    for (let m = 0; m < months; m++) {
      const r = mu + sigma * (Math.random() + Math.random() + Math.random() - 1.5) * Math.sqrt(2 / 3);
      path.push(path[path.length - 1] * (1 + r));
    }
    return path;
  });
  return Array.from({ length: months + 1 }, (_, i) => {
    const vals = paths.map((p) => p[i]).sort((a, b) => a - b);
    return {
      month: i,
      p10: vals[Math.floor(0.10 * nPaths)],
      p50: vals[Math.floor(0.50 * nPaths)],
      p90: vals[Math.floor(0.90 * nPaths)],
    };
  });
}

export default function LookupPage() {
  const [ticker, setTicker] = useState("VOO");
  const [input, setInput] = useState("VOO");
  const [period, setPeriod] = useState("1y");

  const { data: quote } = useQuery({
    queryKey: ["lookup-quote", ticker],
    queryFn: () => fetchQuote(ticker),
    enabled: !!ticker,
  });
  const { data: hist } = useQuery({
    queryKey: ["lookup-hist", ticker, period],
    queryFn: () => fetchHistorical(ticker, period),
    enabled: !!ticker,
  });
  const { data: fund } = useQuery({
    queryKey: ["lookup-fund", ticker],
    queryFn: () => fetchFundamentals(ticker),
    enabled: !!ticker,
  });
  const { data: news } = useQuery({
    queryKey: ["lookup-news", ticker],
    queryFn: () => fetchNews([ticker]),
    enabled: !!ticker,
  });

  const chartData = (hist?.bars ?? []).map((b: { date: string; close: number }) => ({
    date: b.date,
    price: b.close,
  }));

  // Compute annualized return & vol from history
  const annualRet = (() => {
    if (chartData.length < 2) return 0.07;
    const first = chartData[0].price;
    const last = chartData[chartData.length - 1].price;
    const years = chartData.length / 252;
    return Math.pow(last / first, 1 / years) - 1;
  })();
  const annualVol = (() => {
    if (chartData.length < 20) return 0.15;
    const returns = chartData.slice(1).map((d, i) => Math.log(d.price / chartData[i].price));
    const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
    const variance = returns.reduce((a, b) => a + (b - mean) ** 2, 0) / returns.length;
    return Math.sqrt(variance * 252);
  })();

  const mcData = quote?.price
    ? monteCarlo1Y(quote.price, annualVol, annualRet)
    : [];

  const submit = () => {
    if (input) setTicker(input.toUpperCase());
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Ticker Lookup</h1>
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="Ticker…"
            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs w-28 focus:outline-none focus:border-bloomberg-gold"
          />
          <button onClick={submit} className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-3 py-1">GO</button>
        </div>
        <div className="flex gap-1">
          {["3m", "6m", "1y", "2y", "5y"].map((p) => (
            <button key={p} onClick={() => setPeriod(p)}
              className={`text-[10px] px-2 py-1 border ${period === p ? "border-bloomberg-gold text-bloomberg-gold" : "border-bloomberg-border text-bloomberg-muted"}`}>
              {p.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Quote strip */}
      {quote && (
        <div className="bbg-card flex flex-wrap gap-6 items-center">
          <div>
            <p className="text-bloomberg-gold font-bold text-xl">{fmtCurrency(quote.price, quote.currency)}</p>
            <p className="text-bloomberg-muted text-[10px]">{ticker} · {quote.currency} · {quote.source}</p>
          </div>
          <div className={`text-sm font-semibold ${colorClass(quote.change_pct)}`}>
            {quote.change != null ? fmtCurrency(quote.change, quote.currency) : "—"}
            {" "}({fmtPct(quote.change_pct ?? null)}) today
          </div>
          {fund?.longName && (
            <div className="flex-1">
              <p className="text-bloomberg-text text-xs font-medium">{fund.longName}</p>
              <p className="text-bloomberg-muted text-[10px]">{fund.sector} · {fund.industry}</p>
            </div>
          )}
        </div>
      )}

      {/* Price chart */}
      {chartData.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">{ticker} Price History ({period})</p>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
              <defs>
                <linearGradient id="priceGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f3a712" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#f3a712" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false}
                tickFormatter={(v) => fmtCurrency(v, quote?.currency ?? "USD", true)} width={60} />
              <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                formatter={(v: number) => fmtCurrency(v, quote?.currency ?? "USD")} />
              <Area type="monotone" dataKey="price" stroke="#f3a712" strokeWidth={1.5} fill="url(#priceGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Fundamentals */}
        {fund && (
          <div className="bbg-card space-y-3">
            <p className="bbg-header">Valuation Metrics</p>
            <div className="grid grid-cols-2 gap-2">
              <MetricCard label="Market Cap" value={fund.marketCap ? fmtCurrency(fund.marketCap, "USD", true) : "—"} />
              <MetricCard label="Trailing P/E" value={fund.trailingPE?.toFixed(1) ?? "—"} />
              <MetricCard label="Forward P/E" value={fund.forwardPE?.toFixed(1) ?? "—"} />
              <MetricCard label="P/B Ratio" value={fund.priceToBook?.toFixed(2) ?? "—"} />
              <MetricCard label="Div Yield" value={fund.dividendYield != null ? fmtPct(fund.dividendYield) : "—"} />
              <MetricCard label="Beta" value={fund.beta?.toFixed(2) ?? "—"} />
              <MetricCard label="52W High" value={fund.fiftyTwoWeekHigh ? fmtCurrency(fund.fiftyTwoWeekHigh, quote?.currency ?? "USD") : "—"} />
              <MetricCard label="52W Low" value={fund.fiftyTwoWeekLow ? fmtCurrency(fund.fiftyTwoWeekLow, quote?.currency ?? "USD") : "—"} />
            </div>
            {fund.longBusinessSummary && (
              <p className="text-bloomberg-muted text-[10px] leading-relaxed line-clamp-4 mt-2">
                {fund.longBusinessSummary}
              </p>
            )}
          </div>
        )}

        {/* 1Y Monte Carlo */}
        {mcData.length > 0 && (
          <div className="bbg-card">
            <p className="bbg-header">1Y Monte Carlo Projection (300 paths)</p>
            <div className="flex gap-4 mb-2">
              <span className="text-bloomberg-muted text-[10px]">
                Ann. Return: <span className="text-bloomberg-gold">{fmtPct(annualRet * 100)}</span>
              </span>
              <span className="text-bloomberg-muted text-[10px]">
                Ann. Vol: <span className="text-bloomberg-gold">{fmtPct(annualVol * 100)}</span>
              </span>
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={mcData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
                <XAxis dataKey="month" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false}
                  tickFormatter={(v) => `M${v}`} />
                <YAxis tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false}
                  tickFormatter={(v) => fmtCurrency(v, quote?.currency ?? "USD", true)} width={55} />
                <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 10 }}
                  formatter={(v: number) => fmtCurrency(v, quote?.currency ?? "USD")} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                <Line type="monotone" dataKey="p90" stroke="#4dff4d" strokeWidth={1} dot={false} name="Bull P90" />
                <Line type="monotone" dataKey="p50" stroke="#f3a712" strokeWidth={2} dot={false} name="Base P50" />
                <Line type="monotone" dataKey="p10" stroke="#ff4d4d" strokeWidth={1} dot={false} name="Bear P10" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* News */}
      {news && news.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Recent News</p>
          <div className="space-y-3">
            {news.slice(0, 5).map((a: Record<string, unknown>, i: number) => (
              <div key={i} className="flex items-start justify-between gap-4 border-b border-bloomberg-border pb-2 last:border-0 last:pb-0">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-bloomberg-muted text-[10px]">{a.source as string}</span>
                    <span className="text-bloomberg-muted text-[10px]">·</span>
                    <span className="text-bloomberg-muted text-[10px]">
                      {a.datetime ? fmtDateTime(new Date((a.datetime as number) * 1000).toISOString()) : "—"}
                    </span>
                  </div>
                  <p className="text-bloomberg-text text-xs font-medium leading-snug">{a.headline as string}</p>
                </div>
                <a href={a.url as string} target="_blank" rel="noopener noreferrer"
                  className="text-bloomberg-muted hover:text-bloomberg-gold shrink-0">
                  <ExternalLink size={12} />
                </a>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
