"use client";

import { fmtCurrency } from "@/lib/formatters";
import type { AllocationRow, SlippageEntry } from "@/lib/api/contribution";

const SIGNAL_STYLES: Record<string, { label: string; className: string }> = {
  net_alpha_positive:   { label: "α+",       className: "bg-green-900/50 text-green-400 border-green-700" },
  high_expected_return: { label: "μ high",    className: "bg-bloomberg-gold/20 text-bloomberg-gold border-bloomberg-gold/40" },
  underweight:          { label: "UW",        className: "bg-blue-900/50 text-blue-300 border-blue-700" },
  corr_penalty_applied: { label: "corr ↓",   className: "bg-orange-900/50 text-orange-300 border-orange-700" },
  liquidity_capped:     { label: "liq cap",  className: "bg-purple-900/50 text-purple-300 border-purple-700" },
};

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
  const totalGross    = allocations.reduce((s, r) => s + r.gross_amount, 0);
  const totalNet      = allocations.reduce((s, r) => s + r.net_amount, 0);

  const hasSignals  = allocations.some((r) => r.signals && r.signals.length > 0);
  const hasPctCap   = allocations.some((r) => r.pct_of_capital != null);
  const hasExpRet   = allocations.some((r) => r.expected_return_pct != null);

  return (
    <div className="overflow-x-auto">
      <table className="bbg-table">
        <thead>
          <tr>
            <th>Ticker</th>
            <th className="text-right">Current %</th>
            <th className="text-right">Target %</th>
            <th className="text-right">Gap</th>
            {hasPctCap  && <th className="text-right">% Capital</th>}
            {hasExpRet  && <th className="text-right">Exp. Ret</th>}
            {hasSignals && <th>Signals</th>}
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
                {hasPctCap && (
                  <td className="text-right font-medium">
                    {r.pct_of_capital != null ? `${r.pct_of_capital.toFixed(1)}%` : "—"}
                  </td>
                )}
                {hasExpRet && (
                  <td className={`text-right text-[10px] ${
                    (r.expected_return_pct ?? 0) >= 0 ? "text-green-400" : "text-red-400"
                  }`}>
                    {r.expected_return_pct != null
                      ? `${r.expected_return_pct > 0 ? "+" : ""}${r.expected_return_pct.toFixed(1)}%`
                      : "—"}
                  </td>
                )}
                {hasSignals && (
                  <td>
                    <div className="flex flex-wrap gap-1">
                      {(r.signals ?? []).map((s) => {
                        const style = SIGNAL_STYLES[s] ?? { label: s, className: "bg-gray-800 text-gray-400 border-gray-600" };
                        return (
                          <span
                            key={s}
                            className={`text-[9px] px-1 py-0.5 border rounded-sm font-mono ${style.className}`}
                          >
                            {style.label}
                          </span>
                        );
                      })}
                    </div>
                  </td>
                )}
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
            <td
              colSpan={4 + (hasPctCap ? 1 : 0) + (hasExpRet ? 1 : 0) + (hasSignals ? 1 : 0)}
              className="text-bloomberg-muted text-[10px] text-right pt-2"
            >
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
