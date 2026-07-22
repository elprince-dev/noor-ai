"use client";

import { useMemo, useState } from "react";
import { Conversation, DateGroup, groupOf } from "@/lib/chatStore";
import { useSettings } from "./SettingsProvider";

interface SidebarProps {
  open: boolean;
  onClose: () => void;
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onClearAll: () => void;
}

const GROUP_ORDER: DateGroup[] = ["today", "yesterday", "week", "older"];

export function Sidebar({
  open,
  onClose,
  conversations,
  activeId,
  onSelect,
  onNewChat,
  onDelete,
  onRename,
  onClearAll,
}: SidebarProps) {
  const { t } = useSettings();
  const [query, setQuery] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");

  const groupLabels: Record<DateGroup, string> = {
    today: t.today,
    yesterday: t.yesterday,
    week: t.last7Days,
    older: t.older,
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter(
      (c) =>
        c.title.toLowerCase().includes(q) ||
        c.messages.some((m) => m.content.toLowerCase().includes(q)),
    );
  }, [conversations, query]);

  const grouped = useMemo(() => {
    const map = new Map<DateGroup, Conversation[]>();
    for (const c of filtered) {
      const g = groupOf(c.updatedAt);
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(c);
    }
    return map;
  }, [filtered]);

  const commitRename = (id: string) => {
    const title = draftTitle.trim();
    if (title) onRename(id, title);
    setRenamingId(null);
  };

  return (
    <>
      {/* Mobile scrim */}
      <div
        onClick={onClose}
        aria-hidden
        className={`fixed inset-0 z-30 bg-ink-950/60 backdrop-blur-sm transition-opacity duration-300 lg:hidden ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />

      <aside
        aria-label={t.history}
        className={`fixed inset-y-0 start-0 z-40 flex w-72 flex-col border-e border-black/[0.06] bg-white/80 backdrop-blur-2xl transition-transform duration-300 ease-out dark:border-white/[0.06] dark:bg-ink-900/80 lg:static lg:z-auto lg:translate-x-0 lg:transition-[margin] ${
          open
            ? "translate-x-0 rtl:translate-x-0"
            : "-translate-x-full rtl:translate-x-full lg:-ms-72"
        }`}
      >
        {/* ── Brand ── */}
        <div className="flex items-center justify-between gap-2 px-4 pb-2 pt-5">
          <div className="flex items-center gap-2.5">
            <div className="relative grid h-9 w-9 place-items-center rounded-xl bg-gold-gradient shadow-gold-sm">
              <div className="absolute inset-0 rounded-xl bg-gold-gradient opacity-50 blur-md" />
              <span className="relative text-base leading-none text-ink-950">☾</span>
            </div>
            <div className="leading-tight">
              <span className="font-display text-lg font-extrabold tracking-tight">
                <span className="text-gold-gradient">Noor</span>{" "}
                <span className="text-ink-800 dark:text-slate-100">
                  {t.brandSuffix}
                </span>
              </span>
              <span className="ms-1.5 rounded-full border border-gold-400/30 bg-gold-400/10 px-1.5 py-0.5 align-middle text-[9px] font-bold uppercase tracking-wider text-gold-600 dark:text-gold-300">
                {t.freePlan}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label={t.closeSidebar}
            title={t.collapseSidebar}
            className="grid h-8 w-8 place-items-center rounded-lg text-slate-400 transition-colors hover:bg-black/[0.05] hover:text-ink-800 dark:hover:bg-white/[0.06] dark:hover:text-white"
          >
            <svg className="h-4 w-4 rtl:-scale-x-100" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect width="18" height="18" x="3" y="3" rx="2" />
              <path d="M9 3v18" />
              <path d="m14 9-3 3 3 3" />
            </svg>
          </button>
        </div>

        {/* ── New chat ── */}
        <div className="px-3 pt-3">
          <button
            onClick={onNewChat}
            className="group flex w-full items-center justify-between rounded-xl bg-gold-gradient px-3.5 py-2.5 text-sm font-semibold text-ink-950 shadow-gold-sm transition-all hover:shadow-gold active:scale-[0.98]"
          >
            <span className="flex items-center gap-2">
              <svg className="h-4 w-4 transition-transform group-hover:rotate-90" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 5v14M5 12h14" />
              </svg>
              {t.newChat}
            </span>
            <kbd className="hidden rounded-md bg-ink-950/10 px-1.5 py-0.5 font-sans text-[10px] font-bold sm:inline">
              Ctrl K
            </kbd>
          </button>
        </div>

        {/* ── Search ── */}
        <div className="px-3 pt-3">
          <div className="relative">
            <svg
              className="pointer-events-none absolute start-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400"
              viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
            >
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.3-4.3" />
            </svg>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t.searchChats}
              className="w-full rounded-xl border border-black/[0.07] bg-black/[0.03] py-2 pe-3 ps-9 text-xs text-ink-800 placeholder:text-slate-400 transition-colors focus:border-gold-400/50 focus:outline-none dark:border-white/[0.07] dark:bg-white/[0.04] dark:text-slate-100 dark:placeholder:text-slate-500"
            />
          </div>
        </div>

        {/* ── Conversation list ── */}
        <nav className="mt-3 flex-1 space-y-4 overflow-y-auto px-3 pb-3">
          {filtered.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-2 py-10 text-center">
              <div className="grid h-11 w-11 place-items-center rounded-2xl border border-black/[0.06] bg-black/[0.03] text-xl dark:border-white/[0.07] dark:bg-white/[0.04]">
                {query ? "🔍" : "💬"}
              </div>
              <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
                {query ? t.noResults : t.noChats}
              </p>
              {!query && (
                <p className="text-[11px] text-slate-400 dark:text-slate-500">
                  {t.noChatsHint}
                </p>
              )}
            </div>
          )}

          {GROUP_ORDER.map((g) => {
            const items = grouped.get(g);
            if (!items?.length) return null;
            return (
              <div key={g}>
                <h3 className="px-2 pb-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">
                  {groupLabels[g]}
                </h3>
                <ul className="space-y-0.5">
                  {items.map((c) => {
                    const active = c.id === activeId;
                    const renaming = renamingId === c.id;
                    return (
                      <li key={c.id} className="group/item relative">
                        {renaming ? (
                          <input
                            autoFocus
                            value={draftTitle}
                            onChange={(e) => setDraftTitle(e.target.value)}
                            onBlur={() => commitRename(c.id)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") commitRename(c.id);
                              if (e.key === "Escape") setRenamingId(null);
                            }}
                            className="w-full rounded-lg border border-gold-400/50 bg-white px-2.5 py-2 text-xs font-medium text-ink-800 focus:outline-none dark:bg-ink-800 dark:text-slate-100"
                          />
                        ) : (
                          <button
                            onClick={() => onSelect(c.id)}
                            className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-start transition-colors ${
                              active
                                ? "bg-gold-400/[0.12] text-ink-800 dark:bg-gold-400/[0.09] dark:text-slate-50"
                                : "text-slate-600 hover:bg-black/[0.04] dark:text-slate-300 dark:hover:bg-white/[0.05]"
                            }`}
                          >
                            {active && (
                              <span className="absolute inset-y-1.5 start-0 w-0.5 rounded-full bg-gold-400" />
                            )}
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-xs font-medium leading-5">
                                {c.title}
                              </span>
                              <span className="block truncate text-[10px] text-slate-400 dark:text-slate-500">
                                {t.messagesCount(c.messages.length)}
                              </span>
                            </span>
                          </button>
                        )}

                        {/* Row actions */}
                        {!renaming && (
                          <div className="absolute end-1.5 top-1/2 flex -translate-y-1/2 items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover/item:opacity-100">
                            <button
                              onClick={() => {
                                setRenamingId(c.id);
                                setDraftTitle(c.title);
                              }}
                              aria-label={t.renameChat}
                              title={t.renameChat}
                              className="grid h-6 w-6 place-items-center rounded-md bg-white/80 text-slate-400 shadow-sm transition-colors hover:text-royal-500 dark:bg-ink-700/90 dark:hover:text-royal-300"
                            >
                              <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
                              </svg>
                            </button>
                            <button
                              onClick={() => onDelete(c.id)}
                              aria-label={t.deleteChat}
                              title={t.deleteChat}
                              className="grid h-6 w-6 place-items-center rounded-md bg-white/80 text-slate-400 shadow-sm transition-colors hover:text-crimson-500 dark:bg-ink-700/90 dark:hover:text-crimson-400"
                            >
                              <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M3 6h18" />
                                <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
                                <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
                              </svg>
                            </button>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </nav>

        {/* ── Footer ── */}
        <div className="border-t border-black/[0.06] p-3 dark:border-white/[0.06]">
          {conversations.length > 0 && (
            <button
              onClick={() => {
                if (window.confirm(t.clearAllConfirm)) onClearAll();
              }}
              className="mb-2 flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-xs font-medium text-slate-400 transition-colors hover:bg-crimson-500/[0.07] hover:text-crimson-500 dark:text-slate-500 dark:hover:text-crimson-400"
            >
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 6h18" />
                <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
              </svg>
              {t.clearAll}
            </button>
          )}
          <div className="flex items-center gap-2.5 rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-2.5 dark:border-white/[0.06] dark:bg-white/[0.03]">
            <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-royal-gradient text-xs font-bold text-white">
              {t.guestUser.slice(0, 1)}
            </div>
            <div className="min-w-0 leading-tight">
              <p className="truncate text-xs font-semibold text-ink-800 dark:text-slate-100">
                {t.guestUser}
              </p>
              <p className="truncate text-[10px] text-slate-400 dark:text-slate-500">
                {t.keyboardShortcut}
              </p>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
