"use client";

import { useEffect, useRef } from "react";
import { Message } from "@/app/page";
import { MessageBubble } from "./MessageBubble";
import { useSettings } from "./SettingsProvider";

interface ChatWindowProps {
  messages: Message[];
  loading: boolean;
  onPickSuggestion: (text: string) => void;
}

export function ChatWindow({
  messages,
  loading,
  onPickSuggestion,
}: ChatWindowProps) {
  const { t } = useSettings();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  /* ── Empty state ──────────────────────────────────────────────── */
  if (messages.length === 0 && !loading) {
    return (
      <div className="flex-1 overflow-y-auto">
        <div className="flex min-h-full flex-col items-center justify-center py-8 text-center">
          {/* Glowing crescent */}
          <div className="relative mb-6 animate-float">
            <div className="absolute inset-0 rounded-full bg-gold-400/30 blur-2xl" />
            <div className="relative grid h-20 w-20 place-items-center rounded-3xl border border-black/5 bg-gradient-to-br from-white to-slate-100 shadow-glass dark:border-white/10 dark:from-ink-700 dark:to-ink-900">
              <span className="text-4xl">🌙</span>
            </div>
          </div>

          <h2 className="font-display text-3xl font-bold tracking-tight text-ink-800 dark:text-slate-50">
            {t.greetingPre}{" "}
            <span className="text-gold-gradient">{t.greetingHi}</span>
          </h2>
          <p className="mt-2 max-w-md text-sm leading-relaxed text-slate-500 dark:text-slate-400">
            {t.emptySubtitle}
          </p>

          {/* Suggested prompts */}
          <div className="mt-8 grid w-full max-w-xl grid-cols-1 gap-3 sm:grid-cols-2">
            {t.suggestions.map((s, i) => (
              <button
                key={s.title}
                onClick={() => onPickSuggestion(s.prompt)}
                style={{ animationDelay: `${i * 70}ms` }}
                className="group animate-fade-up rounded-2xl border border-black/[0.06] bg-white/70 p-4 text-start transition-all hover:-translate-y-0.5 hover:border-gold-400/40 hover:shadow-gold-sm dark:border-white/[0.07] dark:bg-white/[0.03] dark:hover:bg-white/[0.06]"
              >
                <div className="flex items-center gap-2">
                  <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-slate-100 to-slate-200 text-lg ring-1 ring-black/5 dark:from-ink-600 dark:to-ink-800 dark:ring-white/10">
                    {s.icon}
                  </span>
                  <span className="text-sm font-semibold text-ink-800 dark:text-slate-100">
                    {s.title}
                  </span>
                </div>
                <p className="mt-2 text-xs leading-relaxed text-slate-500 group-hover:text-slate-600 dark:text-slate-400 dark:group-hover:text-slate-300">
                  {s.prompt}
                </p>
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  /* ── Conversation ─────────────────────────────────────────────── */
  return (
    <div className="flex-1 space-y-5 overflow-y-auto px-1 py-2">
      {messages.map((msg, i) => (
        <MessageBubble
          key={i}
          message={msg}
          onGrow={() => bottomRef.current?.scrollIntoView({ behavior: "smooth" })}
        />
      ))}

      {loading && <TypingIndicator label={t.thinking} />}

      <div ref={bottomRef} />
    </div>
  );
}

/* Animated "Noor is thinking" indicator */
function TypingIndicator({ label }: { label: string }) {
  return (
    <div className="flex animate-fade-up items-start gap-3">
      <div className="relative grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gold-gradient shadow-gold-sm">
        <span className="text-base leading-none text-ink-950">☾</span>
      </div>
      <div className="glass flex items-center gap-2 rounded-2xl rounded-tl-md px-4 py-3.5">
        <div className="flex gap-1.5">
          <span className="h-2 w-2 animate-bounce-dot rounded-full bg-gold-300" />
          <span
            className="h-2 w-2 animate-bounce-dot rounded-full bg-gold-400"
            style={{ animationDelay: "0.2s" }}
          />
          <span
            className="h-2 w-2 animate-bounce-dot rounded-full bg-royal-400"
            style={{ animationDelay: "0.4s" }}
          />
        </div>
        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
          {label}
        </span>
      </div>
    </div>
  );
}