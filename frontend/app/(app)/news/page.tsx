"use client";
import { useQuery } from "@tanstack/react-query";
import { fetchNews } from "@/lib/api/settings";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { fmtDateTime } from "@/lib/formatters";
import { ExternalLink } from "lucide-react";

export default function NewsPage() {
  const { data: portfolio } = usePortfolio();
  const tickers = portfolio?.rows.map((r) => r.ticker) ?? ["VOO"];

  const { data: articles, isLoading } = useQuery({
    queryKey: ["news", tickers.slice(0, 5).sort().join(",")],
    queryFn: () => fetchNews(tickers.slice(0, 5)),
    enabled: tickers.length > 0,
    staleTime: 5 * 60 * 1000,
    refetchInterval: 300_000, // 5 min
  });

  return (
    <div className="space-y-4">
      <h1 className="text-bloomberg-gold text-xs font-bold uppercase tracking-widest">
        News · {tickers.slice(0, 5).join(", ")}
      </h1>

      {isLoading && <div className="text-bloomberg-muted text-xs">Loading…</div>}

      <div className="space-y-2">
        {(articles ?? []).map((a: Record<string, unknown>, i: number) => (
          <div key={i} className="bbg-card hover:border-bloomberg-muted transition-colors">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-bloomberg-gold text-[10px] font-medium">{a.ticker as string}</span>
                  <span className="text-bloomberg-muted text-[10px]">{a.source as string}</span>
                  <span className="text-bloomberg-text-dim text-[10px]">
                    {a.datetime ? fmtDateTime(new Date((a.datetime as number) * 1000).toISOString()) : "—"}
                  </span>
                </div>
                <p className="text-bloomberg-text text-xs font-medium leading-snug">{a.headline as string}</p>
                {!!a.summary && (
                  <p className="text-bloomberg-muted text-[10px] mt-1 line-clamp-2">{a.summary as string}</p>
                )}
              </div>
              <a href={a.url as string} target="_blank" rel="noopener noreferrer"
                className="text-bloomberg-muted hover:text-bloomberg-gold shrink-0 mt-0.5">
                <ExternalLink size={12} />
              </a>
            </div>
          </div>
        ))}
        {!isLoading && (!articles || articles.length === 0) && (
          <div className="text-bloomberg-muted text-xs py-4">No recent news.</div>
        )}
      </div>
    </div>
  );
}
