"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UserSettings } from "@/lib/types";

interface SettingsState extends UserSettings {
  cost_basis_usd: number | null;
  setCostBasis: (v: number | null) => void;
  setSettings: (s: Partial<UserSettings>) => void;
}

const defaults: UserSettings = {
  base_currency: "USD",
  rebalancing_threshold: 0.05,
  max_single_asset: 0.40,
  min_bonds: 0.10,
  min_gold: 0.05,
  preferred_benchmark: "VOO",
  risk_free_rate: 0.045,
  rolling_window: 63,
  tc_model: "broker",
  investor_profile: "base",   // matches backend profile engine (conservative | base | aggressive)
  ticker_weight_rules: {},
  combination_ranges: {},
};

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      ...defaults,
      cost_basis_usd: null,
      setCostBasis: (v) => set({ cost_basis_usd: v }),
      // Only merge UserSettings keys — never overwrites cost_basis_usd from backend sync
      setSettings: (s) => set((prev) => {
        const filtered = Object.fromEntries(
          Object.entries(s).filter(([k]) => k in defaults)
        );
        return { ...prev, ...filtered };
      }),
    }),
    { name: "settings-storage" }
  )
);
