"use client";
import { useState, useCallback, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { groqClient, GROQ_MODEL, isGroqConfigured } from "@/lib/groq";
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
      if (!isGroqConfigured || streaming) return;

      const userMsg: ChatMessage = { role: "user", content };
      const newHistory = [...messages, userMsg].slice(-MAX_HISTORY);
      setMessages(newHistory);
      setStreaming(true);
      setStreamingContent("");

      abortRef.current = new AbortController();

      try {
        const systemPrompt = getSystemPrompt();

        const stream = await groqClient.chat.completions.create({
          model: GROQ_MODEL,
          messages: [
            { role: "system", content: systemPrompt },
            ...newHistory.map((m) => ({ role: m.role, content: m.content })),
          ],
          temperature: 0.3,
          max_tokens: 1024,
          stream: true,
        });

        let fullContent = "";
        for await (const chunk of stream) {
          const delta = chunk.choices[0]?.delta?.content ?? "";
          if (delta) {
            fullContent += delta;
            setStreamingContent(fullContent);
          }
        }

        const assistantMsg: ChatMessage = { role: "assistant", content: fullContent };
        setMessages((prev) => [...prev, assistantMsg].slice(-MAX_HISTORY));
      } catch (err: unknown) {
        if ((err as Error)?.name !== "AbortError") {
          const errMsg: ChatMessage = {
            role: "assistant",
            content: "⚠️ Error al conectar con Groq. Verifica tu API key o intenta de nuevo.",
          };
          setMessages((prev) => [...prev, errMsg]);
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
