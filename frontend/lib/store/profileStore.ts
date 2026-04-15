import { create } from "zustand";
import { persist } from "zustand/middleware";

export type InvestorProfile = "conservative" | "base" | "aggressive";

interface ProfileState {
  profile: InvestorProfile;
  targetReturn: number; // e.g. 0.10 = 10%
  _hydrated: boolean;
  setProfile: (profile: InvestorProfile) => void;
  setTargetReturn: (v: number) => void;
  setHydrated: () => void;
}

export const useProfileStore = create<ProfileState>()(
  persist(
    (set) => ({
      profile: "base",
      targetReturn: 0.08,
      _hydrated: false,
      setProfile: (profile) => set({ profile }),
      setTargetReturn: (targetReturn) => set({ targetReturn }),
      setHydrated: () => set({ _hydrated: true }),
    }),
    {
      name: "investor-profile",
      skipHydration: true, // prevents SSR/client mismatch
    }
  )
);
