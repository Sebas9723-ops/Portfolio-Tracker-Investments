import { useEffect } from "react";
import { apiClient } from "@/lib/api/client";

const PING_INTERVAL_MS = 14 * 60 * 1000; // 14 minutes

export function useKeepAlive() {
  useEffect(() => {
    const ping = () => apiClient.get("/health").catch(() => {});
    ping();
    const id = setInterval(ping, PING_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);
}
