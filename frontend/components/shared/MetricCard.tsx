"use client";
import { cn, } from "@/lib/utils";

interface MetricCardProps {
  label: string;
  value: string;
  delta?: string;
  deltaPositive?: boolean;
  sub?: string;
  className?: string;
}

export function MetricCard({ label, value, delta, deltaPositive, sub, className }: MetricCardProps) {
  return (
    <div className={cn("bbg-card", className)}>
      <p className="text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">{label}</p>
      <p className="text-bloomberg-text text-lg font-semibold leading-tight">{value}</p>
      {delta && (
        <p className={cn("text-xs mt-0.5", deltaPositive ? "positive" : "negative")}>{delta}</p>
      )}
      {sub && <p className="text-bloomberg-muted text-[10px] mt-0.5">{sub}</p>}
    </div>
  );
}
