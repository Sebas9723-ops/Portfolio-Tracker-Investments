"use client";
import { useMarketQuotes } from "@/lib/hooks/useMarketQuotes";
import { fmtCurrency, fmtPct, colorClass } from "@/lib/formatters";
import { RefreshCw } from "lucide-react";

const WATCH_TICKERS = ["VOO", "QQQM", "^GSPC", "^VIX"];
const LABELS: Record<string, string> = {
  "VOO": "S&P500 ETF", "QQQM": "NASDAQ ETF", "^GSPC": "S&P500", "^VIX": "VIX",
};

export function TopBar() {
  const { data: quotes, isFetching } = useMarketQuotes(WATCH_TICKERS);

  return (
    <header
      className="h-9 flex items-center justify-between px-4 shrink-0 text-xs bg-white"
      style={{ borderBottom: "1px solid #e2e8f0" }}
    >
      {/* Market watch strip */}
      <div className="flex items-center gap-6">
        {WATCH_TICKERS.map((t) => {
          const q = quotes?.[t];
          return (
            <span key={t} className="flex items-center gap-1.5">
              <span className="text-bloomberg-muted">{LABELS[t] || t}</span>
              {q ? (
                <>
                  <span className="text-bloomberg-text font-medium">{fmtCurrency(q.price)}</span>
                  <span className={colorClass(q.change_pct)}>{fmtPct(q.change_pct)}</span>
                </>
              ) : (
                <span className="text-bloomberg-muted">—</span>
              )}
            </span>
          );
        })}
      </div>

      {/* Status */}
      <div className="flex items-center gap-2 text-bloomberg-muted">
        {isFetching && <RefreshCw size={11} className="animate-spin text-bloomberg-muted" />}
        <span className="text-bloomberg-text-dim">
          {new Date().toLocaleTimeString("en-US", { hour12: false })}
        </span>
      </div>
    </header>
  );
}
