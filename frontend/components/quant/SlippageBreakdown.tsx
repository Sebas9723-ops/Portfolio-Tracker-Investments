"use client";

import { fmtCurrency } from "@/lib/formatters";
import type { AllocationRow, SlippageEntry } from "@/lib/api/contribution";

interface SlippageBreakdownProps {
  allocations: AllocationRow[];
  slippageBreakdown: Record<string, SlippageEntry>;
  currency?: string;
}

export function SlippageBreakdown({
  allocations,
  slippageBreakdown,
  currency = "USD",
}: SlippageBreakdownProps) {
  const totalSlippage = allocations.reduce((s, r) => s + r.slippage_cost, 0);
  const totalGross = allocations.reduce((s, r) => s + r.gross_amount, 0);
  const totalNet = allocations.reduce((s, r) => s + r.net_amount, 0);

  return (
    <div className="overflow-x-auto">
      <table className="bbg-table">
        <thead>
          <tr>
            <th>Ticker</th>
            <th className="text-right">Current %</th>
            <th className="text-right">Target %</th>
            <th className="text-right">Gap</th>
            <th className="text-right">Gross</th>
            <th className="text-right">Slippage</th>
            <th className="text-right">Spread</th>
            <th className="text-right">Vol. Impact</th>
            <th className="text-right text-green-400">Net Buy</th>
          </tr>
        </thead>
        <tbody>
          {allocations.map((r) => {
            const slip = slippageBreakdown[r.ticker];
            return (
              <tr key={r.ticker}>
                <td className="text-bloomberg-gold font-medium">{r.ticker}</td>
                <td className="text-right text-bloomberg-muted">
                  {(r.current_weight * 100).toFixed(1)}%
                </td>
                <td className="text-right">
                  {(r.target_weight * 100).toFixed(1)}%
                </td>
                <td className="text-right text-bloomberg-muted">
                  +{(r.gap * 100).toFixed(1)}%
                </td>
                <td className="text-right">{fmtCurrency(r.gross_amount, currency)}</td>
                <td className="text-right text-red-400">
                  -{fmtCurrency(r.slippage_cost, currency)}
                </td>
                <td className="text-right text-bloomberg-muted text-[10px]">
                  {slip ? `${(slip.spread_cost * 100).toFixed(3)}%` : "—"}
                </td>
                <td className="text-right text-bloomberg-muted text-[10px]">
                  {slip ? `${(slip.volume_impact * 100).toFixed(3)}%` : "—"}
                </td>
                <td className="text-right text-green-400 font-semibold">
                  {fmtCurrency(r.net_amount, currency)}
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-bloomberg-border">
            <td colSpan={4} className="text-bloomberg-muted text-[10px] text-right pt-2">
              Totals
            </td>
            <td className="text-right pt-2 font-medium">
              {fmtCurrency(totalGross, currency)}
            </td>
            <td className="text-right pt-2 text-red-400 font-medium">
              -{fmtCurrency(totalSlippage, currency)}
            </td>
            <td colSpan={2} />
            <td className="text-right pt-2 text-green-400 font-bold">
              {fmtCurrency(totalNet, currency)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
