"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, PieChart, TrendingUp, Target, RefreshCw,
  Shield, Calendar, DollarSign, ArrowLeftRight, BarChart2,
  Activity, Eye, Newspaper, Globe, Grid, LineChart, Settings, LogOut,
  Search, SlidersHorizontal, UserCircle, X,
} from "lucide-react";
import { useAuthStore } from "@/lib/store/authStore";
import { useProfileStore, type InvestorProfile } from "@/lib/store/profileStore";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { updateProfile } from "@/lib/api/profile";
import { cn } from "@/lib/utils";

// Only Core and Analysis pages are prefetched on hover
const PREFETCH_GROUPS = new Set(["Core", "Analysis"]);

const NAV_GROUPS = [
  {
    label: "Core",
    items: [
      { label: "Dashboard",   href: "/dashboard",          icon: LayoutDashboard },
      { label: "Portfolio",   href: "/portfolio",          icon: PieChart },
      { label: "Rebalancing", href: "/rebalancing",        icon: RefreshCw },
      { label: "Horizon",     href: "/investment-horizon", icon: Calendar },
    ],
  },
  {
    label: "Analysis",
    items: [
      { label: "Analytics",    href: "/analytics",    icon: TrendingUp },
      { label: "Risk",         href: "/risk",         icon: Shield },
      { label: "Optimization", href: "/optimization", icon: Target },
    ],
  },
  {
    label: "Research",
    items: [
      { label: "Fundamentals",    href: "/fundamentals",    icon: BarChart2 },
      { label: "Technicals",      href: "/technicals",      icon: Activity },
      { label: "News",            href: "/news",            icon: Newspaper },
      { label: "Watchlist",       href: "/watchlist",       icon: Eye },
      { label: "Lookup",          href: "/lookup",          icon: Search },
      { label: "Market Overview", href: "/market-overview", icon: Globe },
      { label: "Sector Heatmap",  href: "/sector-heatmap",  icon: Grid },
      { label: "Yield Curve",     href: "/yield-curve",     icon: LineChart },
    ],
  },
  {
    label: "Admin",
    items: [
      { label: "Income",       href: "/income",       icon: DollarSign },
      { label: "Transactions", href: "/transactions", icon: ArrowLeftRight },
      { label: "Manage",       href: "/manage",       icon: SlidersHorizontal },
      { label: "Profile",      href: "/profile",      icon: UserCircle },
      { label: "Settings",     href: "/settings",     icon: Settings },
    ],
  },
];

const PROFILES: { key: InvestorProfile; label: string; short: string; color: string }[] = [
  { key: "conservative", label: "Conservative", short: "C", color: "#2563eb" },
  { key: "base",         label: "Base",         short: "B", color: "#16a34a" },
  { key: "aggressive",   label: "Aggressive",   short: "A", color: "#dc2626" },
];

function ProfileSwitcher() {
  const { profile, setProfile } = useProfileStore();
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
      <div className="text-[10px] text-bloomberg-muted mb-1.5 font-medium uppercase tracking-wide">Profile</div>
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
                isActive ? "text-white" : "text-bloomberg-muted bg-bloomberg-bg hover:bg-bloomberg-border"
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

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  const pathname = usePathname();
  const logout = useAuthStore((s) => s.logout);

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/30 lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={cn(
          "fixed top-0 left-0 z-50 h-full w-56 flex flex-col bg-bloomberg-card transition-transform duration-200",
          "lg:static lg:translate-x-0 lg:z-auto",
          isOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        )}
        style={{ borderRight: "1px solid var(--border)" }}
      >
        {/* Logo + close button */}
        <div className="flex items-center justify-between px-4 py-4 border-b border-bloomberg-border shrink-0">
          <div>
            <span className="text-bloomberg-text font-bold text-sm tracking-tight">Portfolio</span>
            <span className="text-bloomberg-muted text-[11px] ml-1">Tracker</span>
          </div>
          <button onClick={onClose} className="lg:hidden text-bloomberg-muted hover:text-bloomberg-text p-0.5">
            <X size={15} />
          </button>
        </div>

        {/* Profile switcher */}
        <ProfileSwitcher />

        {/* Nav groups */}
        <nav className="flex-1 overflow-y-auto py-2">
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className="mb-1">
              <div className="px-4 pt-3 pb-1 text-[9px] font-bold uppercase tracking-widest text-bloomberg-muted/60 select-none">
                {group.label}
              </div>
              {group.items.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={onClose}
                  prefetch={PREFETCH_GROUPS.has(group.label)}
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
              ))}
            </div>
          ))}
        </nav>

        {/* Logout */}
        <button
          onClick={logout}
          className="flex items-center gap-2 px-4 py-3 text-xs text-bloomberg-muted hover:text-red-500 border-t border-bloomberg-border transition-colors shrink-0"
        >
          <LogOut size={13} />
          Logout
        </button>
      </aside>
    </>
  );
}
