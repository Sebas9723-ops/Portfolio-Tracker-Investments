"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/store/authStore";
import { useProfileStore, type InvestorProfile } from "@/lib/store/profileStore";
import { useSettingsStore } from "@/lib/store/settingsStore";
import { fetchSettings } from "@/lib/api/settings";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { BottomNav } from "@/components/layout/BottomNav";

const VALID_PROFILES = new Set(["conservative", "base", "aggressive"]);

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const router = useRouter();
  const setSettings = useSettingsStore((s) => s.setSettings);
  const setProfile = useProfileStore((s) => s.setProfile);
  const [hydrated, setHydrated] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    useProfileStore.persist.rehydrate();
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (hydrated && !isAuthenticated) router.push("/login");
  }, [hydrated, isAuthenticated, router]);

  useEffect(() => {
    if (hydrated && isAuthenticated) {
      fetchSettings().then((data) => {
        setSettings(data);
        if (data.investor_profile && VALID_PROFILES.has(data.investor_profile)) {
          setProfile(data.investor_profile as InvestorProfile);
        }
      }).catch(() => {});
    }
  }, [hydrated, isAuthenticated]);

  if (!hydrated || !isAuthenticated) return null;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      <div className="flex flex-col flex-1 overflow-hidden min-w-0">
        <TopBar onMenuClick={() => setSidebarOpen(true)} />
        {/* Extra bottom padding on mobile so content isn't behind BottomNav */}
        <main className="flex-1 overflow-y-auto p-3 sm:p-4 pb-20 lg:pb-4">
          {children}
        </main>
      </div>

      <BottomNav onMenuClick={() => setSidebarOpen(true)} />
    </div>
  );
}
