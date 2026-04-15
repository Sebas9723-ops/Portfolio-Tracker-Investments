import { apiClient } from "./client";
import type { AuthResponse } from "@/lib/types";

export const login = (email: string, password: string) =>
  apiClient.post<AuthResponse>("/api/auth/login", { email, password }).then((r) => r.data);

export const register = (email: string, password: string) =>
  apiClient.post<AuthResponse>("/api/auth/register", { email, password }).then((r) => r.data);
