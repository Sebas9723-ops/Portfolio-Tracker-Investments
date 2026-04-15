"use client";
import { useQuery } from "@tanstack/react-query";
import { fetchDividends } from "@/lib/api/transactions";
import { fmtCurrency, fmtDate } from "@/lib/formatters";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

export default function IncomePage() {
  const { data: dividends, isLoading } = useQuery({ queryKey: ["dividends"], queryFn: fetchDividends });

  const byMonth = (dividends ?? []).reduce((acc: Record<string, number>, d: Record<string, unknown>) => {
    const m = (d.date as string).slice(0, 7);
    acc[m] = (acc[m] ?? 0) + Number(d.amount_native);
    return acc;
  }, {});
  const monthlyData = Object.entries(byMonth).sort(([a], [b]) => a.localeCompare(b))
    .map(([month, amount]) => ({ month, amount }));

  const totalIncome = (Object.values(byMonth) as number[]).reduce((s, v) => s + v, 0);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Income</h1>
        <p className="text-bloomberg-muted text-[10px]">Total dividends: {fmtCurrency(totalIncome)}</p>
      </div>

      {monthlyData.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Monthly Dividend Income</p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={monthlyData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2535" />
              <XAxis dataKey="month" tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} />
              <YAxis tick={{ fontSize: 9, fill: "#8a9bb5" }} tickLine={false} axisLine={false} width={40} />
              <Tooltip contentStyle={{ background: "#111820", border: "1px solid #1e2535", fontSize: 11 }}
                formatter={(v: number) => fmtCurrency(v)} />
              <Bar dataKey="amount" fill="#f3a712" barSize={20} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="bbg-card">
        <p className="bbg-header">Dividend History</p>
        {isLoading ? <div className="text-bloomberg-muted text-xs py-2">Loading…</div> : (
          <table className="bbg-table">
            <thead><tr><th>Date</th><th>Ticker</th><th className="text-right">Amount</th><th>Currency</th></tr></thead>
            <tbody>
              {(dividends ?? []).map((d: Record<string, unknown>, i: number) => (
                <tr key={i}>
                  <td className="text-bloomberg-muted">{fmtDate(d.date as string)}</td>
                  <td className="text-bloomberg-gold">{d.ticker as string}</td>
                  <td className="text-right">{fmtCurrency(Number(d.amount_native), d.currency as string)}</td>
                  <td className="text-bloomberg-muted">{d.currency as string}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
