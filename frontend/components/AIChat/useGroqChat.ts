"use client";
import { useState, useCallback, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { isGroqConfigured } from "@/lib/groq";
import { buildSystemPrompt } from "./systemPrompt";
import { useSettingsStore } from "@/lib/store/settingsStore";
import type { PortfolioSummary, AnalyticsResponse, RebalancingRow } from "@/lib/types";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

const MAX_HISTORY = 20;

export function useGroqChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const qc = useQueryClient();
  const settings = useSettingsStore();
  const costBasisUsd = useSettingsStore((s) => s.cost_basis_usd ?? null);

  const getSystemPrompt = useCallback(() => {
    const portfolio = qc.getQueryData<PortfolioSummary>(["portfolio"]);
    const analytics = qc.getQueryData<AnalyticsResponse>(["analytics", "2y"]);
    const rebalancing = qc.getQueryData<RebalancingRow[]>(["rebalancing", 0, "broker"]);
    return buildSystemPrompt({
      portfolio: portfolio ?? null,
      metrics: analytics?.metrics ?? null,
      settings,
      rebalancing: rebalancing ?? null,
      costBasisUsd,
    });
  }, [qc, settings, costBasisUsd]);

  const send = useCallback(
    async (content: string) => {
      if (streaming) return;

      const userMsg: ChatMessage = { role: "user", content };
      const newHistory = [...messages, userMsg].slice(-MAX_HISTORY);
      setMessages(newHistory);
      setStreaming(true);
      setStreamingContent("");

      abortRef.current = new AbortController();

      try {
        const systemPrompt = getSystemPrompt();

        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: [
              { role: "system", content: systemPrompt },
              ...newHistory.map((m) => ({ role: m.role, content: m.content })),
            ],
          }),
          signal: abortRef.current.signal,
        });

        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.error ?? `HTTP ${res.status}`);
        }

        const reader = res.body!.getReader();
        const decoder = new TextDecoder();
        let fullContent = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          fullContent += chunk;
          setStreamingContent(fullContent);
        }

        setMessages((prev) => [...prev, { role: "assistant" as const, content: fullContent }].slice(-MAX_HISTORY));
      } catch (err: unknown) {
        if ((err as Error)?.name !== "AbortError") {
          const detail = err instanceof Error ? err.message : "Unknown error";
          setMessages((prev) => [...prev, { role: "assistant", content: `⚠️ ${detail}` }]);
        }
      } finally {
        setStreaming(false);
        setStreamingContent("");
      }
    },
    [messages, streaming, getSystemPrompt],
  );

  const clear = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setStreaming(false);
    setStreamingContent("");
  }, []);

  return { messages, streaming, streamingContent, send, clear, isConfigured: isGroqConfigured };
}
