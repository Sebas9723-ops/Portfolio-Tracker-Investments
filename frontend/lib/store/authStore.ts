"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AuthState {
  token: string | null;
  userId: string | null;
  email: string | null;
  isAuthenticated: boolean;
  login: (token: string, userId: string, email: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      userId: null,
      email: null,
      isAuthenticated: false,
      login: (token, userId, email) =>
        set({ token, userId, email, isAuthenticated: true }),
      logout: () =>
        set({ token: null, userId: null, email: null, isAuthenticated: false }),
    }),
    { name: "auth-storage" }
  )
);
