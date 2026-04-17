import axios from "axios";
import { useAuthStore } from "@/lib/store/authStore";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: API_URL,
  timeout: 30_000,
});

apiClient.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = useAuthStore.getState().token;
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

apiClient.interceptors.response.use(
  (res) => res,
  async (err) => {
    const config = err.config as typeof err.config & { _retryCount?: number };

    if (err.response?.status === 503 && config && !config._retryCount) {
      config._retryCount = 0;
    }

    if (err.response?.status === 503 && config && config._retryCount! < 3) {
      config._retryCount = (config._retryCount ?? 0) + 1;
      const delay = 2000 * Math.pow(2, config._retryCount - 1); // 2s, 4s, 8s
      await sleep(delay);
      return apiClient(config);
    }

    if (err.response?.status === 401 && typeof window !== "undefined") {
      useAuthStore.getState().logout();
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);
