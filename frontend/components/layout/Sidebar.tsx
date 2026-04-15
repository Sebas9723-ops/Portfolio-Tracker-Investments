"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, PieChart, TrendingUp, Target, RefreshCw,
  Shield, Calendar, DollarSign, ArrowLeftRight, BarChart2,
  Activity, Eye, Newspaper, Globe, Grid, LineChart, Settings, LogOut, Search, SlidersHorizontal,
  UserCircle,
} from "lucide-react";
import { useAuthStore } from "@/lib/store/authStore";
import { useProfileStore, type InvestorProfile } from "@/lib/store/profileStore";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { updateProfile } from "@/lib/api/profile";
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
  { label: "Perfil",          href: "/profile",            icon: UserCircle },
  { label: "Settings",        href: "/settings",           icon: Settings },
];

const PROFILES: { key: InvestorProfile; label: string; short: string; color: string }[] = [
  { key: "conservative", label: "Conservador", short: "C", color: "#2563eb" },
  { key: "base",         label: "Base",        short: "B", color: "#16a34a" },
  { key: "aggressive",   label: "Agresivo",    short: "A", color: "#dc2626" },
];

function ProfileSwitcher() {
  const { profile, setProfile, setTargetReturn } = useProfileStore();
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: (p: InvestorProfile) => updateProfile(p),
    onSuccess: (_, p) => {
      setProfile(p);
      qc.invalidateQueries({ queryKey: ["rebalancing-suggestions"] });
      qc.invalidateQueries({ queryKey: ["profile-optimal"] });
    },
  });

  return (
    <div className="px-3 py-2 border-b border-bloomberg-border">
      <div className="text-[10px] text-bloomberg-muted mb-1.5 font-medium uppercase tracking-wide">
        Perfil
      </div>
      <div className="flex gap-1">
        {PROFILES.map((p) => {
          const isActive = profile === p.key;
          return (
            <button
              key={p.key}
              title={p.label}
              onClick={() => mutation.mutate(p.key)}
              disabled={mutation.isPending}
              className={cn(
                "flex-1 py-1 rounded-md text-[10px] font-semibold transition-all",
                isActive
                  ? "text-white"
                  : "text-bloomberg-muted bg-bloomberg-bg hover:bg-bloomberg-border"
              )}
              style={isActive ? { backgroundColor: p.color } : {}}
            >
              {p.short}
            </button>
          );
        })}
      </div>
      <div className="text-[10px] text-bloomberg-muted mt-1 text-center">
        {PROFILES.find((p) => p.key === profile)?.label}
      </div>
    </div>
  );
}

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

      {/* Investor Profile Switcher */}
      <ProfileSwitcher />

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
