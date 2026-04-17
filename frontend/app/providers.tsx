"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { useAuthStore } from "@/lib/store/authStore";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5 * 60 * 1000,     // 5 minutes
            gcTime: 30 * 60 * 1000,        // 30 minutes
            retry: 3,
            retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 30_000),
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  // Rehydrate auth store from localStorage on the client only.
  // skipHydration in the store prevents SSR/client mismatch ("Application error" on load).
  useEffect(() => {
    useAuthStore.persist.rehydrate();
  }, []);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
