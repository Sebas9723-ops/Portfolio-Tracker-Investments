"use client";
import { useEffect, useRef } from "react";
import { MessageCircle } from "lucide-react";
import { useAIChat } from "@/lib/context/aiChatContext";
import { useGroqChat } from "./useGroqChat";
import { ChatPanel } from "./ChatPanel";
import { useProactiveAlerts } from "./proactiveAlerts";

export function AIChatWidget() {
  const { isOpen, open, close, pendingPrompt, clearPendingPrompt } = useAIChat();
  const { messages, streaming, streamingContent, send, clear, isConfigured } = useGroqChat();
  const { alerts, hasBadge, badgeSeverity } = useProactiveAlerts();
  const pendingHandled = useRef(false);

  // Auto-send pending prompt when panel opens
  useEffect(() => {
    if (isOpen && pendingPrompt && !pendingHandled.current) {
      pendingHandled.current = true;
      send(pendingPrompt);
      clearPendingPrompt();
    }
    if (!isOpen) {
      pendingHandled.current = false;
    }
  }, [isOpen, pendingPrompt, send, clearPendingPrompt]);

  const badgeColor =
    badgeSeverity === "red" ? "bg-red-500" :
    badgeSeverity === "orange" ? "bg-orange-400" :
    null;

  return (
    <>
      {/* Floating button */}
      <button
        onClick={() => (isOpen ? close() : open())}
        aria-label="Abrir Portfolio AI"
        className="fixed bottom-20 right-4 lg:bottom-6 lg:right-6 z-50 w-14 h-14 rounded-full bg-[#f3a712] text-white shadow-lg flex items-center justify-center transition-transform hover:scale-105 active:scale-95"
        style={{ boxShadow: "0 4px 20px rgba(243,167,18,0.4)" }}
      >
        <MessageCircle size={22} fill="white" stroke="none" />

        {/* Badge */}
        {hasBadge && !isOpen && badgeColor && (
          <span
            className={`absolute top-1 right-1 w-3 h-3 rounded-full border-2 border-white ${badgeColor} ${
              badgeSeverity === "red" ? "animate-pulse" : ""
            }`}
          />
        )}
      </button>

      {/* Panel */}
      {isOpen && (
        <div
          className="fixed z-50 bottom-36 right-4 lg:bottom-24 lg:right-6"
          style={{
            animation: "slideUp 0.2s ease-out",
          }}
        >
          <ChatPanel
            messages={messages}
            streaming={streaming}
            streamingContent={streamingContent}
            isConfigured={isConfigured}
            alerts={alerts}
            onSend={send}
            onClear={clear}
            onClose={close}
          />
        </div>
      )}

      <style>{`
        @keyframes slideUp {
          from { opacity: 0; transform: translateY(12px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </>
  );
}
