"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchScreener } from "@/lib/api/market";
import type { ScreenerRow } from "@/lib/api/market";
import { fmtCurrency, fmtPct, colorClass } from "@/lib/formatters";
import { usePortfolio } from "@/lib/hooks/usePortfolio";

const SECTORS = [
  "Technology", "Financial Services", "Healthcare", "Communication Services",
  "Consumer Cyclical", "Consumer Defensive", "Industrials", "Energy",
  "Utilities", "Real Estate", "Basic Materials",
];

type SortKey = keyof ScreenerRow;

function FilterInput({ label, value, onChange, placeholder = "—" }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return (
    <div>
      <label className="block text-bloomberg-muted text-[9px] uppercase mb-1">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-[10px] focus:outline-none focus:border-bloomberg-gold"
      />
    </div>
  );
}

export default function ScreenerPage() {
  const { data: portfolio } = usePortfolio();
  const portfolioTickers = new Set((portfolio?.rows ?? []).map((r) => r.ticker));

  const [sector, setSector] = useState("");
  const [minPe, setMinPe] = useState("");
  const [maxPe, setMaxPe] = useState("");
  const [minDivYield, setMinDivYield] = useState("");
  const [minRoe, setMinRoe] = useState("");
  const [maxDebtEq, setMaxDebtEq] = useState("");
  const [minMktCap, setMinMktCap] = useState("");
  const [maxMktCap, setMaxMktCap] = useState("");
  const [minRelVol, setMinRelVol] = useState("");
  const [tickerFilter, setTickerFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("market_cap_b");
  const [sortDesc, setSortDesc] = useState(true);
  const [limit, setLimit] = useState(50);
  const [enabled, setEnabled] = useState(false);

  const params = {
    sector: sector || undefined,
    min_pe: minPe ? parseFloat(minPe) : undefined,
    max_pe: maxPe ? parseFloat(maxPe) : undefined,
    min_div_yield: minDivYield ? parseFloat(minDivYield) : undefined,
    min_roe: minRoe ? parseFloat(minRoe) : undefined,
    max_debt_eq: maxDebtEq ? parseFloat(maxDebtEq) : undefined,
    min_market_cap_b: minMktCap ? parseFloat(minMktCap) : undefined,
    max_market_cap_b: maxMktCap ? parseFloat(maxMktCap) : undefined,
    min_rel_vol: minRelVol ? parseFloat(minRelVol) : undefined,
    tickers: tickerFilter || undefined,
    sort_by: sortKey,
    sort_desc: sortDesc,
    limit,
  };

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["screener", params],
    queryFn: () => fetchScreener(params),
    enabled,
    staleTime: 30 * 60 * 1000,
  });

  const handleRun = () => {
    setEnabled(true);
    refetch();
  };

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortDesc((d) => !d);
    else { setSortKey(key); setSortDesc(true); }
  };

  const SortTh = ({ k, label }: { k: SortKey; label: string }) => (
    <th
      className={`text-right cursor-pointer select-none hover:text-bloomberg-gold ${sortKey === k ? "text-bloomberg-gold" : ""}`}
      onClick={() => handleSort(k)}
    >
      {label}{sortKey === k ? (sortDesc ? " ▼" : " ▲") : ""}
    </th>
  );

  const REC_COLOR: Record<string, string> = {
    strong_buy: "#22c55e", buy: "#4dff4d", hold: "#f3a712",
    sell: "#fb923c", strong_sell: "#ef4444",
  };

  return (
    <div className="space-y-4">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">Stock Screener</h1>

      {/* Filters */}
      <div className="bbg-card">
        <p className="bbg-header mb-3">Filters</p>
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
          {/* Sector */}
          <div>
            <label className="block text-bloomberg-muted text-[9px] uppercase mb-1">Sector</label>
            <select
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-[10px] focus:outline-none focus:border-bloomberg-gold"
            >
              <option value="">All Sectors</option>
              {SECTORS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          <FilterInput label="Min P/E" value={minPe} onChange={setMinPe} placeholder="e.g. 5" />
          <FilterInput label="Max P/E" value={maxPe} onChange={setMaxPe} placeholder="e.g. 30" />
          <FilterInput label="Min Div Yield %" value={minDivYield} onChange={setMinDivYield} placeholder="e.g. 2" />
          <FilterInput label="Min ROE %" value={minRoe} onChange={setMinRoe} placeholder="e.g. 10" />
          <FilterInput label="Max Debt/Eq" value={maxDebtEq} onChange={setMaxDebtEq} placeholder="e.g. 2" />
          <FilterInput label="Min Mkt Cap ($B)" value={minMktCap} onChange={setMinMktCap} placeholder="e.g. 1" />
          <FilterInput label="Max Mkt Cap ($B)" value={maxMktCap} onChange={setMaxMktCap} placeholder="e.g. 500" />
          <FilterInput label="Min Rel. Volume" value={minRelVol} onChange={setMinRelVol} placeholder="e.g. 1.5" />
          <FilterInput label="Tickers (comma)" value={tickerFilter} onChange={setTickerFilter} placeholder="AAPL,MSFT" />

          {/* Limit */}
          <div>
            <label className="block text-bloomberg-muted text-[9px] uppercase mb-1">Max Results</label>
            <select
              value={limit}
              onChange={(e) => setLimit(parseInt(e.target.value))}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-2 py-1 text-[10px] focus:outline-none focus:border-bloomberg-gold"
            >
              {[25, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
        </div>

        <div className="flex items-center gap-3 mt-4">
          <button
            onClick={handleRun}
            disabled={isLoading}
            className="bg-bloomberg-gold text-bloomberg-bg text-xs font-bold px-5 py-1.5 hover:opacity-90 disabled:opacity-50"
          >
            {isLoading ? "Scanning…" : "RUN SCREENER"}
          </button>
          {data && (
            <span className="text-bloomberg-muted text-[10px]">
              {data.rows.length} results · {data.universe_fetched} stocks scanned
            </span>
          )}
        </div>
      </div>

      {/* Results */}
      {data && data.rows.length > 0 && (
        <div className="bbg-card">
          <p className="bbg-header">Results</p>
          <div className="overflow-x-auto">
            <table className="bbg-table text-[10px]">
              <thead>
                <tr>
                  <th
                    className={`cursor-pointer select-none hover:text-bloomberg-gold ${sortKey === "ticker" ? "text-bloomberg-gold" : ""}`}
                    onClick={() => handleSort("ticker")}
                  >
                    Ticker{sortKey === "ticker" ? (sortDesc ? " ▼" : " ▲") : ""}
                  </th>
                  <th>Name</th>
                  <th className="hidden md:table-cell">Sector</th>
                  <SortTh k="price" label="Price" />
                  <SortTh k="change_pct" label="1D%" />
                  <SortTh k="market_cap_b" label="Mkt Cap" />
                  <SortTh k="pe" label="P/E" />
                  <SortTh k="forward_pe" label="Fwd P/E" />
                  <SortTh k="div_yield" label="Div%" />
                  <SortTh k="roe" label="ROE%" />
                  <SortTh k="rel_vol" label="Rel Vol" />
                  <SortTh k="short_float" label="Short%" />
                  <SortTh k="upside" label="Upside%" />
                  <th className="text-right">Rating</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => {
                  const inPortfolio = portfolioTickers.has(row.ticker);
                  const recColor = REC_COLOR[row.recommendation] ?? "#8a9bb5";
                  return (
                    <tr key={row.ticker} className={inPortfolio ? "bg-bloomberg-gold/5" : ""}>
                      <td>
                        <span className="text-bloomberg-gold font-bold">{row.ticker}</span>
                        {inPortfolio && (
                          <span className="ml-1 text-[8px] text-bloomberg-gold border border-bloomberg-gold px-0.5">★</span>
                        )}
                      </td>
                      <td className="text-bloomberg-muted max-w-[120px] truncate hidden sm:table-cell">{row.name}</td>
                      <td className="text-bloomberg-muted text-[9px] hidden md:table-cell">{row.sector}</td>
                      <td className="text-right">${row.price.toFixed(2)}</td>
                      <td className={`text-right font-medium ${colorClass(row.change_pct)}`}>
                        {row.change_pct >= 0 ? "+" : ""}{row.change_pct.toFixed(2)}%
                      </td>
                      <td className="text-right">{row.market_cap_b != null ? `$${row.market_cap_b.toFixed(1)}B` : "—"}</td>
                      <td className="text-right">{row.pe != null ? row.pe.toFixed(1) : "—"}</td>
                      <td className="text-right">{row.forward_pe != null ? row.forward_pe.toFixed(1) : "—"}</td>
                      <td className="text-right">{row.div_yield > 0 ? fmtPct(row.div_yield) : "—"}</td>
                      <td className={`text-right ${colorClass(row.roe)}`}>{row.roe != null ? fmtPct(row.roe) : "—"}</td>
                      <td className={`text-right font-medium ${(row.rel_vol ?? 0) >= 2 ? "text-bloomberg-gold" : ""}`}>
                        {row.rel_vol != null ? `${row.rel_vol.toFixed(1)}×` : "—"}
                      </td>
                      <td className={`text-right ${(row.short_float ?? 0) > 15 ? "text-red-400" : ""}`}>
                        {row.short_float > 0 ? fmtPct(row.short_float) : "—"}
                      </td>
                      <td className={`text-right font-medium ${colorClass(row.upside)}`}>
                        {row.upside != null ? `${row.upside >= 0 ? "+" : ""}${row.upside.toFixed(1)}%` : "—"}
                      </td>
                      <td className="text-right">
                        <span className="text-[9px] font-bold capitalize" style={{ color: recColor }}>
                          {row.recommendation?.replace("_", " ") ?? "—"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-bloomberg-muted text-[9px] mt-1">★ = in your portfolio · Data cached 30 min</p>
        </div>
      )}

      {data && data.rows.length === 0 && (
        <div className="bbg-card">
          <p className="text-bloomberg-muted text-xs">No results match your filters. Try relaxing the criteria.</p>
        </div>
      )}
    </div>
  );
}
