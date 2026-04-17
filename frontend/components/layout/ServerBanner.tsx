"use client";
import { useEffect, useState } from "react";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { Wifi } from "lucide-react";

export function ServerBanner() {
  const { isLoading } = usePortfolio();
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (!isLoading) {
      setShow(false);
      return;
    }
    const id = setTimeout(() => setShow(true), 5000);
    return () => clearTimeout(id);
  }, [isLoading]);

  if (!show) return null;

  return (
    <div className="fixed top-9 inset-x-0 z-50 flex items-center justify-center pointer-events-none">
      <div className="flex items-center gap-2 bg-bloomberg-card border border-bloomberg-gold/40 px-4 py-2 text-[11px] text-bloomberg-gold shadow-lg">
        <Wifi size={12} className="animate-pulse" />
        Conectando servidor… (~15s)
      </div>
    </div>
  );
}
