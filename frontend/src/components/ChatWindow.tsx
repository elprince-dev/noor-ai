"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Message } from "@/lib/types";
import { MessageBubble } from "./MessageBubble";
import { useSettings } from "./SettingsProvider";

interface ChatWindowProps {
  messages: Message[];
  loading: boolean;
  onPickSuggestion: (text: string) => void;
  onRegenerate?: () => void;
}

export function ChatWindow({
  messages,
  loading,
  onPickSuggestion,
  onRegenerate,
}: ChatWindowProps) {
  const { t } = useSettings();
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true); // is the user at (or near) the bottom?
  const [showJump, setShowJump] = useState(false);

  const scrollToBottom = useCallback((smooth = true) => {
    bottomRef.current?.scrollIntoView({
      behavior: smooth ? "smooth" : "auto",
    });
  }, []);

  // Track whether the user has scrolled away from the bottom.
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    const pinned = distance < 80;
    pinnedRef.current = pinned;
    setShowJump(!pinned);
  };

  // Auto-follow new content only while pinned — never fight the user.
  useEffect(() => {
    if (pinnedRef.current) scrollToBottom();
  }, [messages, loading, scrollToBottom]);

  const isStreaming = messages[messages.length - 1]?.stream === true;
  // Show the standalone typing indicator only before any answer text arrives.
  const showTyping =
    loading &&
    isStreaming &&
    !messages[messages.length - 1]?.content &&
    !(messages[messages.length - 1]?.steps?.length ?? 0);

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

          {/* Source trust chips */}
          <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
            {t.sourceChips.map((chip, i) => (
              <span
                key={chip}
                style={{ animationDelay: `${150 + i * 80}ms` }}
                className="animate-fade-up rounded-full border border-gold-400/25 bg-gold-400/[0.07] px-3 py-1 text-[11px] font-semibold text-gold-700 dark:text-gold-200"
              >
                {chip}
              </span>
            ))}
          </div>

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
                  <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-slate-100 to-slate-200 text-lg ring-1 ring-black/5 transition-transform group-hover:scale-110 dark:from-ink-600 dark:to-ink-800 dark:ring-white/10">
                    {s.icon}
                  </span>
                  <span className="text-sm font-semibold text-ink-800 dark:text-slate-100">
                    {s.title}
                  </span>
                  <svg
                    className="ms-auto h-3.5 w-3.5 shrink-0 -translate-x-1 text-gold-500 opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100 rtl:rotate-180 rtl:translate-x-1 rtl:group-hover:translate-x-0"
                    viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"
                  >
                    <path d="M5 12h14M12 5l7 7-7 7" />
                  </svg>
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
    <div className="relative min-h-0 flex-1">
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="h-full space-y-5 overflow-y-auto px-1 py-4"
      >
        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            message={msg}
            isLast={i === messages.length - 1}
            onRegenerate={onRegenerate}
            onGrow={() => {
              if (pinnedRef.current) scrollToBottom();
            }}
          />
        ))}

        {showTyping && <TypingIndicator label={t.thinking} />}

        <div ref={bottomRef} />
      </div>

      {/* Jump-to-latest pill */}
      {showJump && (
        <button
          onClick={() => scrollToBottom()}
          aria-label={t.scrollToBottom}
          className="absolute bottom-3 left-1/2 z-10 flex -translate-x-1/2 animate-fade-up items-center gap-1.5 rounded-full border border-black/10 bg-white/90 px-3.5 py-1.5 text-[11px] font-semibold text-slate-600 shadow-lg backdrop-blur transition-all hover:border-gold-400/50 hover:text-gold-600 dark:border-white/10 dark:bg-ink-800/90 dark:text-slate-300 dark:hover:text-gold-300"
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 5v14M19 12l-7 7-7-7" />
          </svg>
          {t.scrollToBottom}
        </button>
      )}
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
