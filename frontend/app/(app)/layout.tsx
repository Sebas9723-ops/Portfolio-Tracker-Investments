"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/store/authStore";
import { useProfileStore } from "@/lib/store/profileStore";
import { useSettingsStore } from "@/lib/store/settingsStore";
import { fetchSettings } from "@/lib/api/settings";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const router = useRouter();
  const setSettings = useSettingsStore((s) => s.setSettings);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    useProfileStore.persist.rehydrate();
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (hydrated && !isAuthenticated) {
      router.push("/login");
    }
  }, [hydrated, isAuthenticated, router]);

  // Bootstrap settings from DB on every app load so the store is always in sync.
  useEffect(() => {
    if (hydrated && isAuthenticated) {
      fetchSettings().then(setSettings).catch(() => {});
    }
  }, [hydrated, isAuthenticated]);

  if (!hydrated || !isAuthenticated) return null;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <TopBar />
        <main className="flex-1 overflow-y-auto p-4">{children}</main>
      </div>
    </div>
  );
}
