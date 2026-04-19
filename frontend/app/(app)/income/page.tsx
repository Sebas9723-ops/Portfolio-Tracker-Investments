"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchDividends } from "@/lib/api/transactions";
import { fmtCurrency, fmtDate } from "@/lib/formatters";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export default function IncomePage() {
  const { data: dividends, isLoading } = useQuery({ queryKey: ["dividends"], queryFn: fetchDividends });
  const [view, setView] = useState<"chart" | "calendar">("chart");

  const byMonth = (dividends ?? []).reduce((acc: Record<string, number>, d: Record<string, unknown>) => {
    const m = (d.date as string).slice(0, 7);
    acc[m] = (acc[m] ?? 0) + Number(d.amount_native);
    return acc;
  }, {});
  const monthlyData = Object.entries(byMonth).sort(([a], [b]) => a.localeCompare(b))
    .map(([month, amount]) => ({ month, amount }));

  const totalIncome = (Object.values(byMonth) as number[]).reduce((s, v) => s + v, 0);

  // Calendar data — group by year → month (0-based)
  const calendarData: Record<number, Record<number, { total: number; entries: Record<string, unknown>[] }>> = {};
  for (const d of (dividends ?? []) as Record<string, unknown>[]) {
    const date = new Date(d.date as string);
    const yr = date.getFullYear();
    const mo = date.getMonth();
    if (!calendarData[yr]) calendarData[yr] = {};
    if (!calendarData[yr][mo]) calendarData[yr][mo] = { total: 0, entries: [] };
    calendarData[yr][mo].total += Number(d.amount_native);
    calendarData[yr][mo].entries.push(d);
  }
  const years = Object.keys(calendarData).map(Number).sort((a, b) => b - a);
  const maxMonthlyAmt = Math.max(...(Object.values(byMonth) as number[]), 1);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Income</h1>
          <p className="text-bloomberg-muted text-[10px]">Total dividends: {fmtCurrency(totalIncome)}</p>
        </div>
        <div className="flex gap-1">
          {(["chart", "calendar"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`text-[10px] px-3 py-1 border transition-colors ${
                view === v
                  ? "border-bloomberg-gold text-bloomberg-gold bg-bloomberg-gold/10"
                  : "border-bloomberg-border text-bloomberg-muted hover:border-bloomberg-muted"
              }`}
            >
              {v === "chart" ? "Bar Chart" : "Calendar"}
            </button>
          ))}
        </div>
      </div>

      {view === "chart" ? (
        <>
          {monthlyData.length > 0 && (
            <div className="bbg-card">
              <p className="bbg-header">Monthly Dividend Income</p>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={monthlyData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="month" tick={{ fontSize: 9 }} tickLine={false} />
                  <YAxis tick={{ fontSize: 9 }} tickLine={false} axisLine={false} width={40} />
                  <Tooltip formatter={(v: number) => fmtCurrency(v)} />
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
        </>
      ) : (
        /* ── Calendar View ── */
        <div className="space-y-4">
          {years.length === 0 && (
            <div className="bbg-card text-bloomberg-muted text-xs text-center py-8">No dividend history yet.</div>
          )}
          {years.map((yr) => (
            <div key={yr} className="bbg-card">
              <p className="bbg-header">{yr}</p>
              <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2">
                {MONTH_LABELS.map((label, mo) => {
                  const cell = calendarData[yr]?.[mo];
                  const intensity = cell ? Math.min(cell.total / maxMonthlyAmt, 1) : 0;
                  const bg = cell ? `rgba(243,167,18,${0.08 + intensity * 0.55})` : undefined;
                  return (
                    <div
                      key={mo}
                      className="border border-bloomberg-border p-2 min-h-[64px] relative"
                      style={bg ? { background: bg, borderColor: "rgba(243,167,18,0.3)" } : undefined}
                    >
                      <p className="text-bloomberg-muted text-[9px] uppercase mb-1">{label}</p>
                      {cell ? (
                        <>
                          <p className="text-bloomberg-text text-xs font-semibold">{fmtCurrency(cell.total)}</p>
                          <p className="text-bloomberg-muted text-[9px] mt-0.5">
                            {cell.entries.map((e) => e.ticker as string).join(", ")}
                          </p>
                        </>
                      ) : (
                        <p className="text-bloomberg-muted text-[9px]">—</p>
                      )}
                    </div>
                  );
                })}
              </div>
              <p className="text-bloomberg-muted text-[9px] mt-2 text-right">
                Annual total: {fmtCurrency(Object.values(calendarData[yr] ?? {}).reduce((s, c) => s + c.total, 0))}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
