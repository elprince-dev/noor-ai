"use client";

import { useEffect, useState } from "react";
import { Message } from "@/app/page";
import { useSettings } from "./SettingsProvider";
import { useTypewriter } from "@/lib/useTypewriter";

interface MessageBubbleProps {
  message: Message;
  onGrow?: () => void;
}

export function MessageBubble({ message, onGrow }: MessageBubbleProps) {
  const { t } = useSettings();
  const isUser = message.role === "user";
  const isError = !!message.error;
  const [copied, setCopied] = useState(false);

  // Only assistant answers flagged `stream` animate; everything else is instant.
  const { shown, done } = useTypewriter(
    message.content,
    !isUser && !isError && !!message.stream,
  );
  const text = isUser || isError ? message.content : shown;

  // Keep the view pinned to the bottom while the answer types out.
  useEffect(() => {
    if (!done) onGrow?.();
  }, [shown, done, onGrow]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable — silently ignore */
    }
  };

  /* ── User message ─────────────────────────────────────────────── */
  if (isUser) {
    return (
      <div className="flex animate-fade-up items-start justify-end gap-3">
        <div className="max-w-[82%] rounded-2xl rounded-tr-md bg-royal-gradient px-4 py-3 text-sm leading-relaxed text-white shadow-[0_8px_30px_-8px_rgba(47,107,255,0.6)]">
          <p className="whitespace-pre-wrap">{text}</p>
        </div>
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-black/10 bg-black/[0.04] text-slate-600 dark:border-white/10 dark:bg-white/[0.06] dark:text-slate-200">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ width: "1.05rem", height: "1.05rem" }}
          >
            <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
            <circle cx="12" cy="7" r="4" />
          </svg>
        </div>
      </div>
    );
  }

  /* ── Assistant / error message ───────────────────────────────── */
  return (
    <div className="group flex animate-fade-up items-start gap-3">
      {/* Avatar */}
      <div
        className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl shadow-gold-sm ${
          isError ? "bg-crimson-500" : "bg-gold-gradient"
        }`}
      >
        <span className="text-base leading-none text-ink-950">
          {isError ? "!" : "☾"}
        </span>
      </div>

      <div className="min-w-0 max-w-[82%]">
        <div
          className={`rounded-2xl rounded-tl-md px-4 py-3 text-sm leading-relaxed ${
            isError
              ? "border border-crimson-500/40 bg-crimson-500/10 text-crimson-600 dark:text-crimson-100"
              : "glass text-ink-800 dark:text-slate-100"
          }`}
        >
          <p className={`whitespace-pre-wrap ${!done ? "caret" : ""}`}>{text}</p>
        </div>

        {/* Actions (assistant only, once fully typed) */}
        {!isError && done && (
          <div className="mt-1.5 flex items-center gap-3 px-1 opacity-0 transition-opacity group-hover:opacity-100">
            <button
              onClick={copy}
              className="flex items-center gap-1.5 text-[11px] font-medium text-slate-400 transition-colors hover:text-gold-500 dark:text-slate-500 dark:hover:text-gold-300"
            >
              {copied ? (
                <>
                  <svg
                    className="h-3.5 w-3.5"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M20 6 9 17l-5-5" />
                  </svg>
                  {t.copied}
                </>
              ) : (
                <>
                  <svg
                    className="h-3.5 w-3.5"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
                    <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
                  </svg>
                  {t.copy}
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}