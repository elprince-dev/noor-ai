"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient, School } from "@/lib/api";
import { Message } from "@/lib/types";
import {
  Conversation,
  loadConversations,
  newId,
  saveConversations,
  titleFrom,
} from "@/lib/chatStore";
import { ChatWindow } from "@/components/ChatWindow";
import { SchoolSelector } from "@/components/SchoolSelector";
import { AuroraBackground } from "@/components/AuroraBackground";
import { Sidebar } from "@/components/Sidebar";
import { useSettings } from "@/components/SettingsProvider";

export type { Message, ToolStep } from "@/lib/types";

const SIDEBAR_KEY = "noor.sidebar";

export default function Home() {
  const { t, dir, theme, toggleTheme, toggleLang } = useSettings();

  // ── Conversations ──
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  // ── Chat state ──
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string>("");
  const [school, setSchool] = useState<School>("general");
  const [loading, setLoading] = useState(false);

  // ── UI state ──
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const lastQuestionRef = useRef<string>("");

  /* ── Hydrate persisted state ─────────────────────────────────── */
  useEffect(() => {
    setConversations(loadConversations());
    const stored = localStorage.getItem(SIDEBAR_KEY);
    // Default: open on desktop, closed on mobile.
    const isDesktop = window.matchMedia("(min-width: 1024px)").matches;
    setSidebarOpen(stored !== null ? stored === "1" : isDesktop);
    setHydrated(true);
  }, []);

  useEffect(() => {
    apiClient.createSession().then((res) => setSessionId(res.session_id));
  }, []);

  // Persist conversations whenever they change (post-hydration).
  useEffect(() => {
    if (hydrated) saveConversations(conversations);
  }, [conversations, hydrated]);

  const setSidebar = (open: boolean) => {
    setSidebarOpen(open);
    localStorage.setItem(SIDEBAR_KEY, open ? "1" : "0");
  };

  /* ── Composer auto-grow ──────────────────────────────────────── */
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  /* ── Sync messages into the active conversation ──────────────── */
  const syncConversation = useCallback(
    (id: string, msgs: Message[], convSchool: School, convSession: string) => {
      setConversations((prev) => {
        const idx = prev.findIndex((c) => c.id === id);
        const firstUser = msgs.find((m) => m.role === "user");
        const title = firstUser ? titleFrom(firstUser.content) : t.newChat;
        const now = Date.now();
        if (idx === -1) {
          return [
            {
              id,
              title,
              createdAt: now,
              updatedAt: now,
              school: convSchool,
              sessionId: convSession,
              messages: msgs,
            },
            ...prev,
          ];
        }
        const next = [...prev];
        next[idx] = {
          ...next[idx],
          title: next[idx].title === t.newChat ? title : next[idx].title,
          updatedAt: now,
          school: convSchool,
          messages: msgs,
        };
        return next;
      });
    },
    [t.newChat],
  );

  /* ── Send / stream ───────────────────────────────────────────── */
  const send = async (text: string) => {
    const question = text.trim();
    if (!question || !sessionId || loading) return;

    lastQuestionRef.current = question;
    const convId = activeId ?? newId();
    if (!activeId) setActiveId(convId);

    const base: Message[] = [
      ...messages,
      { role: "user", content: question },
      { role: "assistant", content: "", stream: true, steps: [] },
    ];
    setMessages(base);
    setInput("");
    setLoading(true);

    const controller = new AbortController();
    abortRef.current = controller;

    let working = base;
    const update = (mutate: (last: Message) => Message) => {
      working = [...working];
      working[working.length - 1] = mutate({ ...working[working.length - 1] });
      setMessages(working);
    };

    try {
      await apiClient.ask(
        { question, session_id: sessionId, school },
        (ev) => {
          switch (ev.type) {
            case "meta":
              // Stamp the backend Request_ID onto the in-flight answer so
              // feedback can reference it once streaming completes.
              update((last) => ({ ...last, requestId: ev.request_id }));
              break;
            case "token":
              update((last) => ({ ...last, content: last.content + ev.text }));
              break;
            case "tool_start":
              update((last) => ({
                ...last,
                content: "", // text before a tool call is preamble — discard
                steps: [
                  ...(last.steps ?? []),
                  { id: ev.id, tool: ev.tool, query: ev.query, done: false },
                ],
              }));
              break;
            case "tool_end":
              update((last) => ({
                ...last,
                steps: (last.steps ?? []).map((s) =>
                  s.id === ev.id
                    ? { ...s, done: true, ms: ev.ms, count: ev.count }
                    : s,
                ),
              }));
              break;
            case "done":
              update((last) => ({
                ...last,
                stream: false,
                requestId: ev.request_id ?? last.requestId,
              }));
              break;
            case "error":
              update((last) => ({
                ...last,
                error: true,
                content: t.disclaimer,
                stream: false,
              }));
              break;
          }
        },
        controller.signal,
      );
    } catch (err) {
      if ((err as Error)?.name === "AbortError") {
        // User stopped generation — keep whatever streamed in.
        update((last) => ({ ...last, stream: false }));
      } else {
        update(() => ({
          role: "assistant",
          content: t.disclaimer,
          error: true,
        }));
      }
    } finally {
      abortRef.current = null;
      setLoading(false);
      syncConversation(convId, working, school, sessionId);
      inputRef.current?.focus();
    }
  };

  const stopGenerating = () => abortRef.current?.abort();

  /* ── Feedback ────────────────────────────────────────────────── */
  const handleFeedbackChange = (
    index: number,
    feedback: NonNullable<Message["feedback"]>,
  ) => {
    const next = messages.map((m, i) =>
      i === index ? { ...m, feedback } : m,
    );
    setMessages(next);
    // Persist so the feedback state (and requestId) survive reloads.
    if (activeId) syncConversation(activeId, next, school, sessionId);
  };

  const regenerate = () => {
    if (loading || !lastQuestionRef.current) return;
    // Drop the last assistant answer, re-ask the same question.
    setMessages((prev) => {
      const trimmed = [...prev];
      while (
        trimmed.length &&
        trimmed[trimmed.length - 1].role === "assistant"
      ) {
        trimmed.pop();
      }
      if (trimmed.length && trimmed[trimmed.length - 1].role === "user") {
        trimmed.pop();
      }
      return trimmed;
    });
    // Let state settle before re-sending.
    setTimeout(() => send(lastQuestionRef.current), 0);
  };

  const handleSend = () => send(input);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  /* ── Conversation management ─────────────────────────────────── */
  const startNewChat = useCallback(async () => {
    abortRef.current?.abort();
    setActiveId(null);
    setMessages([]);
    lastQuestionRef.current = "";
    const res = await apiClient.createSession();
    setSessionId(res.session_id);
    inputRef.current?.focus();
  }, []);

  const selectConversation = (id: string) => {
    if (id === activeId) return;
    abortRef.current?.abort();
    const conv = conversations.find((c) => c.id === id);
    if (!conv) return;
    setActiveId(id);
    setMessages(conv.messages);
    setSchool(conv.school);
    setSessionId(conv.sessionId);
    lastQuestionRef.current =
      [...conv.messages].reverse().find((m) => m.role === "user")?.content ??
      "";
    // Close the drawer on mobile after picking a chat.
    if (!window.matchMedia("(min-width: 1024px)").matches) setSidebar(false);
  };

  const deleteConversation = (id: string) => {
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (id === activeId) {
      setActiveId(null);
      setMessages([]);
    }
  };

  const renameConversation = (id: string, title: string) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title } : c)),
    );
  };

  const clearAll = () => {
    setConversations([]);
    setActiveId(null);
    setMessages([]);
  };

  /* ── Export current chat as Markdown ─────────────────────────── */
  const exportChat = () => {
    if (!messages.length) return;
    const lines = messages
      .filter((m) => m.content)
      .map((m) =>
        m.role === "user" ? `**${t.you}:** ${m.content}` : `**Noor AI:**\n\n${m.content}`,
      );
    const md = `# Noor AI\n\n${lines.join("\n\n---\n\n")}\n\n> ${t.disclaimer}\n`;
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `noor-chat-${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  /* ── Global shortcuts ────────────────────────────────────────── */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        startNewChat();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [startNewChat]);

  const hasMessages = messages.length > 0;

  return (
    <>
      <AuroraBackground />

      <div dir={dir} className="relative z-10 flex h-[100dvh] overflow-hidden">
        <Sidebar
          open={sidebarOpen}
          onClose={() => setSidebar(false)}
          conversations={conversations}
          activeId={activeId}
          onSelect={selectConversation}
          onNewChat={startNewChat}
          onDelete={deleteConversation}
          onRename={renameConversation}
          onClearAll={clearAll}
        />

        {/* ── Main column ─────────────────────────────────────────── */}
        <main className="flex min-w-0 flex-1 flex-col">
          {/* Header */}
          <header className="relative flex items-center justify-between gap-3 border-b border-black/[0.05] bg-white/40 px-4 py-3 backdrop-blur-xl dark:border-white/[0.05] dark:bg-ink-950/40 sm:px-6">
            {loading && (
              <div
                aria-hidden
                className="absolute inset-x-0 -bottom-px h-px animate-shimmer bg-gradient-to-r from-transparent via-gold-400 to-transparent"
                style={{ backgroundSize: "200% 100%" }}
              />
            )}
            <div className="flex min-w-0 items-center gap-2.5">
              {!sidebarOpen && (
                <button
                  onClick={() => setSidebar(true)}
                  aria-label={t.openSidebar}
                  title={t.openSidebar}
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-black/10 bg-black/[0.03] text-slate-500 transition-colors hover:border-gold-400/40 hover:text-gold-500 dark:border-white/10 dark:bg-white/[0.04] dark:text-slate-300 dark:hover:text-gold-300"
                >
                  <svg className="h-4 w-4 rtl:-scale-x-100" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect width="18" height="18" x="3" y="3" rx="2" />
                    <path d="M9 3v18" />
                    <path d="m13 9 3 3-3 3" />
                  </svg>
                </button>
              )}
              <SchoolSelector value={school} onChange={setSchool} />
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <span className="hidden items-center gap-1.5 text-[11px] font-medium text-slate-500 md:flex">
                <span className="h-1.5 w-1.5 animate-glow-pulse rounded-full bg-emerald-400" />
                {t.status}
              </span>

              {hasMessages && (
                <button
                  onClick={exportChat}
                  aria-label={t.exportChat}
                  title={t.exportChat}
                  className="grid h-9 w-9 place-items-center rounded-full border border-black/10 bg-black/[0.03] text-slate-600 transition-all hover:border-royal-400/40 hover:text-royal-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-300 dark:hover:text-white"
                >
                  <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <path d="M7 10l5 5 5-5" />
                    <path d="M12 15V3" />
                  </svg>
                </button>
              )}

              <button
                onClick={toggleLang}
                aria-label={t.toggleLang}
                title={t.toggleLang}
                className="flex h-9 items-center gap-1.5 rounded-full border border-black/10 bg-black/[0.03] px-3 text-xs font-semibold text-slate-600 transition-all hover:border-royal-400/40 hover:text-royal-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-300 dark:hover:text-white"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M2 12h20" />
                  <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10Z" />
                </svg>
                {t.langName}
              </button>

              <button
                onClick={toggleTheme}
                aria-label={t.toggleTheme}
                title={t.toggleTheme}
                className="grid h-9 w-9 place-items-center rounded-full border border-black/10 bg-black/[0.03] text-slate-600 transition-all hover:border-gold-400/50 hover:text-gold-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-300 dark:hover:text-gold-300"
              >
                {theme === "dark" ? (
                  <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="4" />
                    <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
                  </svg>
                ) : (
                  <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
                  </svg>
                )}
              </button>
            </div>
          </header>

          {/* Chat area */}
          <div className="mx-auto flex w-full max-w-3xl min-h-0 flex-1 flex-col px-4 sm:px-6">
            <ChatWindow
              messages={messages}
              loading={loading}
              onPickSuggestion={send}
              onRegenerate={regenerate}
              onFeedbackChange={handleFeedbackChange}
            />

            {/* ── Composer ── */}
            <div className="pb-4 pt-3">
              {loading && (
                <div className="mb-2.5 flex justify-center">
                  <button
                    onClick={stopGenerating}
                    className="flex items-center gap-2 rounded-full border border-black/10 bg-white/80 px-4 py-1.5 text-xs font-semibold text-slate-600 shadow-sm backdrop-blur transition-all hover:border-crimson-500/40 hover:text-crimson-500 dark:border-white/10 dark:bg-ink-800/80 dark:text-slate-300 dark:hover:text-crimson-400"
                  >
                    <span className="grid h-3.5 w-3.5 place-items-center">
                      <span className="h-2.5 w-2.5 rounded-[3px] bg-current" />
                    </span>
                    {t.stop}
                  </button>
                </div>
              )}

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
                    <svg className="h-5 w-5 rtl:-scale-x-100" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="m22 2-7 20-4-9-9-4Z" />
                      <path d="M22 2 11 13" />
                    </svg>
                  )}
                </button>
              </div>

              <div className="mt-2 flex items-center justify-between gap-2 px-1">
                <p className="hidden text-[10px] text-slate-400 dark:text-slate-500 sm:block">
                  <kbd className="rounded border border-black/10 bg-black/[0.03] px-1 py-px font-sans dark:border-white/10 dark:bg-white/[0.04]">
                    Enter
                  </kbd>{" "}
                  {t.enterHint} ·{" "}
                  <kbd className="rounded border border-black/10 bg-black/[0.03] px-1 py-px font-sans dark:border-white/10 dark:bg-white/[0.04]">
                    Shift+Enter
                  </kbd>{" "}
                  {t.shiftEnterHint}
                </p>
                <p className="flex-1 text-center text-[11px] text-slate-400 dark:text-slate-500 sm:text-end">
                  {t.disclaimer}
                </p>
              </div>
            </div>
          </div>
        </main>
      </div>
    </>
  );
}
