"use client";
import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

interface AIChatContextValue {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  openWith: (prompt: string) => void;
  pendingPrompt: string | null;
  clearPendingPrompt: () => void;
}

const AIChatContext = createContext<AIChatContextValue | null>(null);

export function AIChatProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);

  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => setIsOpen(false), []);
  const openWith = useCallback((prompt: string) => {
    setIsOpen(true);
    setPendingPrompt(prompt);
  }, []);
  const clearPendingPrompt = useCallback(() => setPendingPrompt(null), []);

  return (
    <AIChatContext.Provider value={{ isOpen, open, close, openWith, pendingPrompt, clearPendingPrompt }}>
      {children}
    </AIChatContext.Provider>
  );
}

export function useAIChat() {
  const ctx = useContext(AIChatContext);
  if (!ctx) throw new Error("useAIChat must be used inside AIChatProvider");
  return ctx;
}
