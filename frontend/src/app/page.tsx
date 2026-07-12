"use client";

import { useState, useEffect, useRef } from "react";
import { apiClient, School } from "@/lib/api";
import { ChatWindow } from "@/components/ChatWindow";
import { SchoolSelector } from "@/components/SchoolSelector";
import { AuroraBackground } from "@/components/AuroraBackground";
import { useSettings } from "@/components/SettingsProvider";

export interface Message {
  role: "user" | "assistant";
  content: string;
  error?: boolean;
  /** true only for a freshly received answer so it plays the typewriter effect */
  stream?: boolean;
}

export default function Home() {
  const { t, dir, theme, toggleTheme, toggleLang } = useSettings();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string>("");
  const [school, setSchool] = useState<School>("general");
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    apiClient.createSession().then((res) => setSessionId(res.session_id));
  }, []);

  // Auto-grow the composer textarea up to a max height.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || !sessionId || loading) return;

    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setInput("");
    setLoading(true);

    // Add a placeholder assistant message that we'll stream into
    setMessages((prev) => [
      ...prev,
      { role: "assistant", content: "", stream: true },
    ]);

    try {
      await apiClient.ask(
        { question, session_id: sessionId, school },
        (chunk) => {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                content: last.content + chunk,
              };
            }
            return updated;
          });
        },
      );
    } catch {
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        // If the placeholder is still empty, replace it with the error
        if (last && last.role === "assistant" && !last.content) {
          updated[updated.length - 1] = {
            role: "assistant",
            content: t.disclaimer,
            error: true,
          };
        } else {
          updated.push({
            role: "assistant",
            content: t.disclaimer,
            error: true,
          });
        }
        return updated;
      });
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleSend = () => send(input);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleNewSession = async () => {
    const res = await apiClient.createSession();
    setSessionId(res.session_id);
    setMessages([]);
    inputRef.current?.focus();
  };

  const hasMessages = messages.length > 0;

  return (
    <>
      <AuroraBackground />

      <main
        dir={dir}
        className="relative z-10 mx-auto flex h-[100dvh] max-w-3xl flex-col px-4 sm:px-6"
      >
        {/* ── Header ─────────────────────────────────────────────── */}
        <header className="flex items-center justify-between gap-4 pb-4 pt-6">
          <div className="flex items-center gap-3">
            {/* Crescent mark */}
            <div className="relative grid h-11 w-11 place-items-center rounded-2xl bg-gold-gradient shadow-gold-sm">
              <div className="absolute inset-0 rounded-2xl bg-gold-gradient opacity-60 blur-md" />
              <span className="relative text-xl leading-none text-ink-950">
                ☾
              </span>
            </div>
            <div className="leading-tight">
              <h1 className="font-display text-2xl font-extrabold tracking-tight">
                <span className="text-gold-gradient">Noor</span>{" "}
                <span className="text-ink-800 dark:text-slate-100">
                  {t.brandSuffix}
                </span>
              </h1>
              <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
                {t.tagline}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Language toggle */}
            <button
              onClick={toggleLang}
              aria-label={t.toggleLang}
              title={t.toggleLang}
              className="flex h-9 items-center gap-1.5 rounded-full border border-black/10 bg-black/[0.03] px-3 text-xs font-semibold text-slate-600 transition-all hover:border-royal-400/40 hover:text-royal-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-300 dark:hover:text-white"
            >
              <svg
                className="h-3.5 w-3.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="12" cy="12" r="10" />
                <path d="M2 12h20" />
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10Z" />
              </svg>
              {t.langName}
            </button>

            {/* Theme toggle */}
            <button
              onClick={toggleTheme}
              aria-label={t.toggleTheme}
              title={t.toggleTheme}
              className="grid h-9 w-9 place-items-center rounded-full border border-black/10 bg-black/[0.03] text-slate-600 transition-all hover:border-gold-400/50 hover:text-gold-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-300 dark:hover:text-gold-300"
            >
              {theme === "dark" ? (
                <svg
                  className="h-4 w-4"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <circle cx="12" cy="12" r="4" />
                  <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
                </svg>
              ) : (
                <svg
                  className="h-4 w-4"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
                </svg>
              )}
            </button>

            {hasMessages && (
              <button
                onClick={handleNewSession}
                className="group flex h-9 items-center gap-1.5 rounded-full border border-black/10 bg-black/[0.03] px-3.5 text-xs font-medium text-slate-600 transition-all hover:border-royal-400/40 hover:text-royal-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-300 dark:hover:bg-royal-500/10 dark:hover:text-white"
              >
                <svg
                  className="h-3.5 w-3.5 transition-transform group-hover:rotate-180"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                  <path d="M3 3v5h5" />
                </svg>
                <span className="hidden sm:inline">{t.newChat}</span>
              </button>
            )}
          </div>
        </header>

        {/* ── School selector ────────────────────────────────────── */}
        <div className="flex items-center justify-between gap-3 pb-4">
          <SchoolSelector value={school} onChange={setSchool} />
          <span className="hidden items-center gap-1.5 text-[11px] font-medium text-slate-500 sm:flex">
            <span className="h-1.5 w-1.5 animate-glow-pulse rounded-full bg-emerald-400" />
            {t.status}
          </span>
        </div>

        {/* ── Chat ───────────────────────────────────────────────── */}
        <ChatWindow
          messages={messages}
          loading={loading}
          onPickSuggestion={send}
        />

        {/* ── Composer ───────────────────────────────────────────── */}
        <div className="pb-5 pt-4">
          <div className="glass group flex items-end gap-2 rounded-2xl p-2 shadow-glass transition-shadow focus-within:shadow-glow">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              placeholder={t.placeholder}
              disabled={loading}
              className="max-h-40 flex-1 resize-none bg-transparent px-3 py-2.5 text-sm text-ink-800 placeholder:text-slate-400 focus:outline-none disabled:opacity-50 dark:text-slate-100 dark:placeholder:text-slate-500"
            />
            <button
              onClick={handleSend}
              disabled={loading || !input.trim()}
              aria-label={t.send}
              className="relative grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-xl bg-gold-gradient text-ink-950 shadow-gold-sm transition-all hover:scale-105 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:scale-100"
            >
              {loading ? (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-950/40 border-t-ink-950" />
              ) : (
                <svg
                  className="h-5 w-5 rtl:-scale-x-100"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="m22 2-7 20-4-9-9-4Z" />
                  <path d="M22 2 11 13" />
                </svg>
              )}
            </button>
          </div>
          <p className="mt-2.5 text-center text-[11px] text-slate-400 dark:text-slate-500">
            {t.disclaimer}
          </p>
        </div>
      </main>
    </>
  );
}