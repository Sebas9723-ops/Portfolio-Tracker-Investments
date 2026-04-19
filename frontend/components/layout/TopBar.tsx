"use client";
import { Menu, RefreshCw, Sun, Moon } from "lucide-react";
import { useMarketQuotes } from "@/lib/hooks/useMarketQuotes";
import { useSettingsStore } from "@/lib/store/settingsStore";
import { useThemeStore } from "@/lib/store/themeStore";
import { fmtCurrency, fmtPct, colorClass } from "@/lib/formatters";

const WATCH_TICKERS = ["VOO", "QQQM", "^GSPC", "^VIX"];
const LABELS: Record<string, string> = {
  "VOO": "S&P500 ETF", "QQQM": "NASDAQ ETF", "^GSPC": "S&P500", "^VIX": "VIX",
};

interface TopBarProps {
  onMenuClick: () => void;
}

export function TopBar({ onMenuClick }: TopBarProps) {
  const { data: quotes, isFetching } = useMarketQuotes(WATCH_TICKERS);
  const base_currency = useSettingsStore((s) => s.base_currency);
  const { dark, toggle } = useThemeStore();

  return (
    <header
      className="h-9 flex items-center justify-between px-3 shrink-0 text-xs bg-bloomberg-card"
      style={{ borderBottom: "1px solid var(--border)" }}
    >
      {/* Hamburger — only on mobile/tablet */}
      <button
        onClick={onMenuClick}
        className="lg:hidden flex items-center justify-center w-7 h-7 text-bloomberg-muted hover:text-bloomberg-text mr-2 shrink-0"
        aria-label="Open menu"
      >
        <Menu size={16} />
      </button>

      {/* Market watch strip — scrollable on small screens */}
      <div className="flex items-center gap-4 overflow-x-auto flex-1 min-w-0 scrollbar-none">
        {WATCH_TICKERS.map((t) => {
          const q = quotes?.[t];
          return (
            <span key={t} className="flex items-center gap-1 shrink-0">
              <span className="text-bloomberg-muted hidden sm:inline">{LABELS[t] || t}</span>
              <span className="text-bloomberg-muted sm:hidden">{t.replace("^", "")}</span>
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

      {/* Status + currency + theme toggle */}
      <div className="flex items-center gap-2 text-bloomberg-muted shrink-0 ml-2">
        {isFetching && <RefreshCw size={11} className="animate-spin" />}
        <span
          className="text-[10px] font-bold px-2 py-0.5 border"
          style={{ borderColor: "#f3a712", color: "#f3a712" }}
        >
          {base_currency}
        </span>
        <span className="text-bloomberg-text-dim hidden sm:inline">
          {new Date().toLocaleTimeString("en-US", { hour12: false })}
        </span>
        <button
          onClick={toggle}
          className="flex items-center justify-center w-6 h-6 text-bloomberg-muted hover:text-bloomberg-text transition-colors"
          title={dark ? "Switch to light mode" : "Switch to dark mode"}
        >
          {dark ? <Sun size={13} /> : <Moon size={13} />}
        </button>
      </div>
    </header>
  );
}
