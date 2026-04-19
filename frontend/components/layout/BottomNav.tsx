"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, TrendingUp, Newspaper, Settings, Menu } from "lucide-react";
import { cn } from "@/lib/utils";

const TABS = [
  { label: "Core",     href: "/dashboard",   icon: LayoutDashboard },
  { label: "Analysis", href: "/analytics",   icon: TrendingUp },
  { label: "Research", href: "/news",         icon: Newspaper },
  { label: "Admin",    href: "/settings",     icon: Settings },
];

interface BottomNavProps {
  onMenuClick: () => void;
}

export function BottomNav({ onMenuClick }: BottomNavProps) {
  const pathname = usePathname();

  const CORE    = ["/dashboard", "/portfolio", "/rebalancing", "/investment-horizon"];
  const ANALYSIS = ["/analytics", "/risk", "/optimization"];
  const RESEARCH = ["/fundamentals", "/technicals", "/news", "/watchlist", "/lookup", "/market-overview", "/sector-heatmap", "/yield-curve"];
  const ADMIN   = ["/income", "/transactions", "/manage", "/profile", "/settings"];

  function isGroupActive(group: string) {
    if (group === "Core")     return CORE.includes(pathname);
    if (group === "Analysis") return ANALYSIS.includes(pathname);
    if (group === "Research") return RESEARCH.includes(pathname);
    if (group === "Admin")    return ADMIN.includes(pathname);
    return false;
  }

  return (
    <nav
      className="lg:hidden fixed bottom-0 inset-x-0 z-30 flex items-center bg-bloomberg-card"
      style={{ borderTop: "1px solid var(--border)", height: 56 }}
    >
      {TABS.map((tab) => {
        const active = isGroupActive(tab.label);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={cn(
              "flex flex-col items-center justify-center flex-1 h-full gap-0.5 text-[10px] transition-colors",
              active ? "text-bloomberg-text font-semibold" : "text-bloomberg-muted"
            )}
          >
            <tab.icon size={18} strokeWidth={active ? 2.5 : 1.8} />
            {tab.label}
          </Link>
        );
      })}
      {/* Menu button opens full sidebar */}
      <button
        onClick={onMenuClick}
        className="flex flex-col items-center justify-center flex-1 h-full gap-0.5 text-[10px] text-bloomberg-muted"
      >
        <Menu size={18} strokeWidth={1.8} />
        Menu
      </button>
    </nav>
  );
}
