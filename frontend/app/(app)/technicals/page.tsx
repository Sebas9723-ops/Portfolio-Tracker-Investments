"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchTechnicals } from "@/lib/api/settings";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";

const PERIODS = ["3m", "6m", "1y", "2y"];

export default function TechnicalsPage() {
  const [ticker, setTicker] = useState("VOO");
  const [input, setInput] = useState("VOO");
  const [period, setPeriod] = useState("1y");

  const { data, isLoading } = useQuery({
    queryKey: ["technicals", ticker, period],
    queryFn: () => fetchTechnicals(ticker, period),
    staleTime: 5 * 60 * 1000,
    enabled: !!ticker,
  });

  // Merge bars + indicators
  const chartData = (data?.bars ?? []).map((bar: Record<string, unknown>) => {
    const d = bar.date as string;
    const row: Record<string, unknown> = { ...bar };
    for (const key of ["sma20", "sma50", "sma200", "bb_upper", "bb_mid", "bb_lower"]) {
      const point = (data?.indicators?.[key] as Array<{ date: string; value: number }> | undefined)?.find((p) => p.date === d);
      row[key] = point?.value ?? null;
    }
    return row;
  });

  const rsiData = (data?.indicators?.rsi as Array<{ date: string; value: number }> | undefined) ?? [];
  const macdData = (data?.bars ?? []).map((bar: Record<string, unknown>) => {
    const d = bar.date as string;
    const macd = (data?.indicators?.macd as Array<{ date: string; value: number }> | undefined)?.find((p) => p.date === d)?.value ?? null;
    const signal = (data?.indicators?.macd_signal as Array<{ date: string; value: number }> | undefined)?.find((p) => p.date === d)?.value ?? null;
    const hist = (data?.indicators?.macd_hist as Array<{ date: string; value: number }> | undefined)?.find((p) => p.date === d)?.value ?? null;
    return { date: d, macd, signal, hist };
  });

  return (
    <ErrorBoundary>
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Technicals</h1>
        <div className="flex gap-2">
          <input value={input} onChange={(e) => setInput(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === "Enter" && setTicker(input)}
            placeholder="Ticker…"
            className="bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-xs w-24 focus:outline-none focus:border-bloomberg-gold" />
          <button onClick={() => setTicker(input)}
            className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-3 py-1">GO</button>
        </div>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button key={p} onClick={() => setPeriod(p)}
              className={`text-[10px] px-2 py-1 border ${period === p ? "border-bloomberg-gold text-bloomberg-gold" : "border-bloomberg-border text-bloomberg-muted"}`}>
              {p.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {isLoading && <div className="text-bloomberg-muted text-xs">Loading…</div>}

      {/* Price + SMAs + BBands */}
      {chartData.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">{ticker} — Price + Moving Averages</p>
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false} width={45} />
              <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 10 }} />
              <Line type="monotone" dataKey="close" stroke="#d4dde8" strokeWidth={1.5} dot={false} name="Close" />
              <Line type="monotone" dataKey="sma20" stroke="#f3a712" strokeWidth={1} dot={false} name="SMA20" />
              <Line type="monotone" dataKey="sma50" stroke="#38b2ff" strokeWidth={1} dot={false} name="SMA50" strokeDasharray="3 3" />
              <Line type="monotone" dataKey="sma200" stroke="#c084fc" strokeWidth={1} dot={false} name="SMA200" strokeDasharray="5 5" />
              <Line type="monotone" dataKey="bb_upper" stroke="#ff4d4d" strokeWidth={0.5} dot={false} name="BB Upper" strokeDasharray="2 2" />
              <Line type="monotone" dataKey="bb_lower" stroke="#4dff4d" strokeWidth={0.5} dot={false} name="BB Lower" strokeDasharray="2 2" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* RSI */}
      {rsiData.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">RSI (14)</p>
          <ResponsiveContainer width="100%" height={120}>
            <ComposedChart data={rsiData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} interval="preserveStartEnd" />
              <YAxis domain={[0, 100]} tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false} width={30} />
              <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 10 }} />
              <ReferenceLine y={70} stroke="#ff4d4d" strokeDasharray="3 3" />
              <ReferenceLine y={30} stroke="#4dff4d" strokeDasharray="3 3" />
              <Line type="monotone" dataKey="value" stroke="#f3a712" strokeWidth={1.5} dot={false} name="RSI" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* MACD */}
      {macdData.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">MACD (12, 26, 9)</p>
          <ResponsiveContainer width="100%" height={120}>
            <ComposedChart data={macdData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false} width={40} />
              <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 10 }} />
              <ReferenceLine y={0} stroke="#1e2535" />
              <Bar dataKey="hist" fill="#f3a712" opacity={0.5} name="Histogram" />
              <Line type="monotone" dataKey="macd" stroke="#38b2ff" strokeWidth={1.5} dot={false} name="MACD" />
              <Line type="monotone" dataKey="signal" stroke="#ff4d4d" strokeWidth={1} dot={false} name="Signal" strokeDasharray="3 3" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
    </ErrorBoundary>
  );
}
