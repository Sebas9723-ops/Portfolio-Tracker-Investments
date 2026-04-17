"use client";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { X, RotateCcw, Send, Bot } from "lucide-react";
import { usePathname } from "next/navigation";
import type { ChatMessage } from "./useGroqChat";
import { getContextChips, type ContextChip } from "./contextChips";
import type { ProactiveAlert } from "./proactiveAlerts";

// ── Simple Markdown renderer (bold + lists only) ────────────────────────────

function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) =>
    part.startsWith("**") && part.endsWith("**")
      ? <strong key={i}>{part.slice(2, -2)}</strong>
      : <span key={i}>{part}</span>
  );
}

function MarkdownMessage({ content }: { content: string }) {
  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let listItems: string[] = [];
  let listType: "ul" | "ol" = "ul";

  const flushList = (key: number) => {
    if (listItems.length === 0) return;
    const Tag = listType;
    elements.push(
      <Tag key={key} className={Tag === "ul" ? "list-disc list-inside space-y-0.5 my-1" : "list-decimal list-inside space-y-0.5 my-1"}>
        {listItems.map((item, i) => (
          <li key={i} className="text-[12px] leading-relaxed">{renderInline(item)}</li>
        ))}
      </Tag>
    );
    listItems = [];
  };

  lines.forEach((line, i) => {
    const ulMatch = line.match(/^[-*]\s+(.*)/);
    const olMatch = line.match(/^\d+\.\s+(.*)/);
    if (ulMatch) {
      if (listType !== "ul" && listItems.length) { flushList(i); }
      listType = "ul";
      listItems.push(ulMatch[1]);
    } else if (olMatch) {
      if (listType !== "ol" && listItems.length) { flushList(i); }
      listType = "ol";
      listItems.push(olMatch[1]);
    } else {
      flushList(i);
      if (line.trim()) {
        elements.push(
          <p key={i} className="text-[12px] leading-relaxed my-0.5">{renderInline(line)}</p>
        );
      }
    }
  });
  flushList(lines.length);

  return <div className="space-y-0.5">{elements}</div>;
}

// ── Typing dots ─────────────────────────────────────────────────────────────

function TypingDots() {
  return (
    <div className="flex items-center gap-1 px-3 py-2">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  );
}

// ── Props ───────────────────────────────────────────────────────────────────

interface ChatPanelProps {
  messages: ChatMessage[];
  streaming: boolean;
  streamingContent: string;
  isConfigured: boolean;
  alerts: ProactiveAlert[];
  onSend: (msg: string) => void;
  onClear: () => void;
  onClose: () => void;
}

// ── Panel ───────────────────────────────────────────────────────────────────

export function ChatPanel({
  messages, streaming, streamingContent, isConfigured,
  alerts, onSend, onClear, onClose,
}: ChatPanelProps) {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pathname = usePathname();

  const chips: ContextChip[] = [
    ...alerts.filter((a) => a.chip).map((a) => a.chip!),
    ...getContextChips(pathname),
  ].slice(0, 6);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  // Auto-resize textarea
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = "auto";
      ta.style.height = Math.min(ta.scrollHeight, 72) + "px";
    }
  };

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || streaming || !isConfigured) return;
    onSend(trimmed);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const showChips = messages.length === 0 && !streaming;

  return (
    <div
      className="flex flex-col bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden"
      style={{ width: 380, height: 520 }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 bg-white shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full bg-[#f3a712]/15 flex items-center justify-center">
            <Bot size={14} className="text-[#f3a712]" />
          </div>
          <div>
            <p className="text-[13px] font-semibold text-slate-800 leading-none">Portfolio AI</p>
            <p className="text-[10px] text-slate-400 mt-0.5">Llama 3.3 70B</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onClear}
            title="Nueva conversación"
            className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <RotateCcw size={13} />
          </button>
          <button
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 bg-slate-50/50">
        {!isConfigured && (
          <div className="text-center text-[11px] text-slate-400 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mx-2">
            Configura <code className="font-mono bg-amber-100 px-1 rounded">NEXT_PUBLIC_GROQ_API_KEY</code> en tu <code className="font-mono">.env.local</code> para activar el AI
          </div>
        )}

        {/* Alert messages */}
        {messages.length === 0 && alerts.map((alert) => (
          <div key={alert.id} className={`text-[11px] px-3 py-2 rounded-lg border ${
            alert.severity === "red"
              ? "bg-red-50 border-red-200 text-red-700"
              : "bg-orange-50 border-orange-200 text-orange-700"
          }`}>
            {alert.message}
          </div>
        ))}

        {/* Chat messages */}
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[85%] px-3 py-2 rounded-2xl ${
                msg.role === "user"
                  ? "bg-[#f3a712] text-white rounded-br-md text-[12px] leading-relaxed"
                  : "bg-white border border-slate-200 text-slate-800 rounded-bl-md shadow-sm"
              }`}
            >
              {msg.role === "assistant" ? (
                <MarkdownMessage content={msg.content} />
              ) : (
                <p className="text-[12px]">{msg.content}</p>
              )}
            </div>
          </div>
        ))}

        {/* Streaming message */}
        {streaming && (
          <div className="flex justify-start">
            <div className="max-w-[85%] bg-white border border-slate-200 text-slate-800 rounded-2xl rounded-bl-md shadow-sm px-3 py-2">
              {streamingContent ? (
                <MarkdownMessage content={streamingContent} />
              ) : (
                <TypingDots />
              )}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Context chips */}
      {showChips && chips.length > 0 && (
        <div className="px-3 py-2 border-t border-slate-100 bg-white shrink-0">
          <div className="flex gap-1.5 overflow-x-auto scrollbar-none pb-0.5">
            {chips.map((chip) => (
              <button
                key={chip.label}
                onClick={() => isConfigured && onSend(chip.prompt)}
                disabled={!isConfigured}
                className="shrink-0 px-2.5 py-1 text-[10px] bg-slate-100 hover:bg-[#f3a712]/15 hover:text-[#f3a712] text-slate-600 rounded-full transition-colors whitespace-nowrap disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {chip.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="px-3 py-2.5 border-t border-slate-100 bg-white shrink-0">
        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder="Pregunta sobre tu portfolio..."
            disabled={!isConfigured || streaming}
            className="flex-1 resize-none bg-slate-100 rounded-xl px-3 py-2 text-[12px] text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#f3a712]/30 disabled:opacity-50 leading-relaxed"
            style={{ maxHeight: 72, minHeight: 36 }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || streaming || !isConfigured}
            className="w-8 h-8 shrink-0 flex items-center justify-center rounded-xl bg-[#f3a712] text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#f3a712]/90 transition-colors"
          >
            <Send size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}
