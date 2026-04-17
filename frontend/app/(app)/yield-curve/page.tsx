"use client";
import { useMarketQuotes } from "@/lib/hooks/useMarketQuotes";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

const TENORS = [
  { ticker: "^IRX", label: "3M", months: 3 },
  { ticker: "^FVX", label: "5Y", months: 60 },
  { ticker: "^TNX", label: "10Y", months: 120 },
  { ticker: "^TYX", label: "30Y", months: 360 },
];

export default function YieldCurvePage() {
  const tickers = TENORS.map((t) => t.ticker);
  const { data: quotes } = useMarketQuotes(tickers);

  const chartData = TENORS.map(({ ticker, label }) => ({
    tenor: label,
    yield: quotes?.[ticker]?.price ?? null,
  }));

  return (
    <div className="space-y-4">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">US Treasury Yield Curve</h1>

      <div className="bbg-card">
        <p className="bbg-header">Current Yield Curve</p>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={chartData} margin={{ top: 10, right: 20, bottom: 10, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
            <XAxis dataKey="tenor" tick={{ fontSize: 10, fill: "#8a9bb5" }} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "#8a9bb5" }} tickLine={false} axisLine={false}
              tickFormatter={(v) => `${v.toFixed(2)}%`} width={50} />
            <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
              formatter={(v: number) => [`${v.toFixed(3)}%`, "Yield"]} />
            <Line type="monotone" dataKey="yield" stroke="#f3a712" strokeWidth={2} dot={{ fill: "#f3a712", r: 4 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {TENORS.map(({ ticker, label }) => {
          const q = quotes?.[ticker];
          return (
            <div key={ticker} className="bbg-card text-center">
              <p className="text-bloomberg-muted text-[10px] uppercase">{label}</p>
              <p className="text-bloomberg-gold text-lg font-bold">
                {q ? `${q.price.toFixed(3)}%` : "—"}
              </p>
              {q?.change_pct && (
                <p className={q.change_pct >= 0 ? "positive text-[10px]" : "negative text-[10px]"}>
                  {q.change_pct >= 0 ? "+" : ""}{q.change_pct.toFixed(2)}bp
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
