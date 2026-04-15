"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UserSettings } from "@/lib/types";

interface SettingsState extends UserSettings {
  setSettings: (s: Partial<UserSettings>) => void;
}

const defaults: UserSettings = {
  base_currency: "USD",
  rebalancing_threshold: 0.05,
  max_single_asset: 0.30,
  min_bonds: 0.10,
  min_gold: 0.05,
  preferred_benchmark: "VOO",
  risk_free_rate: 0.045,
  rolling_window: 63,
  tc_model: "broker",
  investor_profile: "balanced",
  ticker_weight_rules: {},
};

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      ...defaults,
      setSettings: (s) => set((prev) => ({ ...prev, ...s })),
    }),
    { name: "settings-storage" }
  )
);
