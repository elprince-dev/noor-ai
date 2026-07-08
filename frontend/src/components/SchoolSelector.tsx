"use client";

import { useEffect, useRef, useState } from "react";
import { School } from "@/lib/api";
import { useSettings } from "./SettingsProvider";

interface SchoolSelectorProps {
  value: School;
  onChange: (school: School) => void;
}

export function SchoolSelector({ value, onChange }: SchoolSelectorProps) {
  const { t } = useSettings();
  const schools = t.schools;
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const active = schools.find((s) => s.value === value) ?? schools[0];

  // Close on outside click / Escape
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="group flex items-center gap-2 rounded-full border border-black/10 bg-black/[0.03] py-2 pe-2.5 ps-3 text-sm font-medium text-slate-600 transition-all hover:border-gold-400/40 dark:border-white/10 dark:bg-white/[0.04] dark:text-slate-200 dark:hover:bg-white/[0.07]"
      >
        <svg
          className="h-4 w-4 text-gold-500 dark:text-gold-300"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="m3 6 9-4 9 4-9 4-9-4Z" />
          <path d="M3 6v6c0 1.5 4 3 9 3s9-1.5 9-3V6" />
          <path d="M12 10v8" />
        </svg>
        <span className="hidden text-slate-400 sm:inline">{t.madhab}</span>
        <span className="text-ink-800 dark:text-slate-100">{active.label}</span>
        <svg
          className={`h-4 w-4 text-slate-400 transition-transform ${
            open ? "rotate-180" : ""
          }`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {open && (
        <ul
          role="listbox"
          className="glass absolute top-full z-30 mt-2 w-60 animate-fade-up overflow-hidden rounded-2xl p-1.5 shadow-glass start-0"
        >
          {schools.map((s) => {
            const selected = s.value === value;
            return (
              <li key={s.value} role="option" aria-selected={selected}>
                <button
                  type="button"
                  onClick={() => {
                    onChange(s.value);
                    setOpen(false);
                  }}
                  className={`flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-start transition-colors ${
                    selected
                      ? "bg-gold-400/10 text-gold-600 dark:text-gold-200"
                      : "text-slate-600 hover:bg-black/[0.04] hover:text-ink-800 dark:text-slate-300 dark:hover:bg-white/[0.06] dark:hover:text-white"
                  }`}
                >
                  <span className="flex flex-col">
                    <span className="text-sm font-semibold">{s.label}</span>
                    <span className="text-[11px] text-slate-400 dark:text-slate-500">
                      {s.hint}
                    </span>
                  </span>
                  {selected && (
                    <svg
                      className="h-4 w-4 shrink-0 text-gold-500 dark:text-gold-300"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.4"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M20 6 9 17l-5-5" />
                    </svg>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}