"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, PieChart, TrendingUp, Target, RefreshCw,
  Shield, Calendar, DollarSign, ArrowLeftRight, BarChart2,
  Activity, Eye, Newspaper, Globe, Grid, LineChart, Settings, LogOut, Search, SlidersHorizontal,
} from "lucide-react";
import { useAuthStore } from "@/lib/store/authStore";
import { cn } from "@/lib/utils";

const NAV = [
  { label: "Dashboard",       href: "/dashboard",          icon: LayoutDashboard },
  { label: "Portfolio",       href: "/portfolio",          icon: PieChart },
  { label: "Analytics",       href: "/analytics",          icon: TrendingUp },
  { label: "Optimization",    href: "/optimization",       icon: Target },
  { label: "Rebalancing",     href: "/rebalancing",        icon: RefreshCw },
  { label: "Risk",            href: "/risk",               icon: Shield },
  { label: "Horizon",         href: "/investment-horizon", icon: Calendar },
  { label: "Income",          href: "/income",             icon: DollarSign },
  { label: "Transactions",    href: "/transactions",       icon: ArrowLeftRight },
  { label: "Manage",          href: "/manage",             icon: SlidersHorizontal },
  null, // divider
  { label: "Fundamentals",    href: "/fundamentals",       icon: BarChart2 },
  { label: "Technicals",      href: "/technicals",         icon: Activity },
  { label: "Watchlist",       href: "/watchlist",          icon: Eye },
  { label: "Lookup",          href: "/lookup",             icon: Search },
  { label: "News",            href: "/news",               icon: Newspaper },
  { label: "Market Overview", href: "/market-overview",    icon: Globe },
  { label: "Sector Heatmap",  href: "/sector-heatmap",     icon: Grid },
  { label: "Yield Curve",     href: "/yield-curve",        icon: LineChart },
  null,
  { label: "Settings",        href: "/settings",           icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const logout = useAuthStore((s) => s.logout);

  return (
    <aside className="w-44 shrink-0 h-screen sticky top-0 flex flex-col bg-white"
           style={{ borderRight: "1px solid #e2e8f0" }}>
      {/* Logo */}
      <div className="px-4 py-5 border-b border-bloomberg-border">
        <span className="text-bloomberg-text font-bold text-sm tracking-tight">Portfolio</span>
        <br />
        <span className="text-bloomberg-muted text-[11px]">Tracker</span>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2">
        {NAV.map((item, i) =>
          item === null ? (
            <div key={i} className="my-1 mx-3 border-t border-bloomberg-border" />
          ) : (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2 px-3 py-1.5 text-xs transition-colors rounded-lg mx-1",
                pathname === item.href
                  ? "text-bloomberg-text bg-bloomberg-bg font-semibold"
                  : "text-bloomberg-muted hover:text-bloomberg-text hover:bg-bloomberg-bg"
              )}
            >
              <item.icon size={13} />
              {item.label}
            </Link>
          )
        )}
      </nav>

      {/* Logout */}
      <button
        onClick={logout}
        className="flex items-center gap-2 px-4 py-3 text-xs text-bloomberg-muted hover:text-red-500 border-t border-bloomberg-border transition-colors"
      >
        <LogOut size={13} />
        Logout
      </button>
    </aside>
  );
}
