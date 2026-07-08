"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { Lang, Dictionary, translations } from "@/lib/i18n";

type Theme = "dark" | "light";

interface SettingsContextValue {
  theme: Theme;
  lang: Lang;
  dir: "ltr" | "rtl";
  t: Dictionary;
  toggleTheme: () => void;
  toggleLang: () => void;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

const THEME_KEY = "noor.theme";
const LANG_KEY = "noor.lang";

function applyToDocument(theme: Theme, lang: Lang) {
  const html = document.documentElement;
  html.classList.toggle("dark", theme === "dark");
  html.classList.toggle("light", theme === "light");
  html.setAttribute("lang", lang);
  html.setAttribute("dir", lang === "ar" ? "rtl" : "ltr");
}

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  // Default to the values the server rendered (dark / en) to avoid hydration
  // mismatches; real preferences are applied in the effect below.
  const [theme, setTheme] = useState<Theme>("dark");
  const [lang, setLang] = useState<Lang>("en");

  useEffect(() => {
    const storedTheme = (localStorage.getItem(THEME_KEY) as Theme | null) ?? null;
    const storedLang = (localStorage.getItem(LANG_KEY) as Lang | null) ?? null;

    const prefersLight =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-color-scheme: light)").matches;

    const nextTheme: Theme = storedTheme ?? (prefersLight ? "light" : "dark");
    const nextLang: Lang = storedLang ?? "en";

    setTheme(nextTheme);
    setLang(nextLang);
    applyToDocument(nextTheme, nextLang);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      localStorage.setItem(THEME_KEY, next);
      applyToDocument(next, lang);
      return next;
    });
  }, [lang]);

  const toggleLang = useCallback(() => {
    setLang((prev) => {
      const next = prev === "en" ? "ar" : "en";
      localStorage.setItem(LANG_KEY, next);
      applyToDocument(theme, next);
      return next;
    });
  }, [theme]);

  const value: SettingsContextValue = {
    theme,
    lang,
    dir: lang === "ar" ? "rtl" : "ltr",
    t: translations[lang],
    toggleTheme,
    toggleLang,
  };

  return (
    <SettingsContext.Provider value={value}>
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettings() {
  const ctx = useContext(SettingsContext);
  if (!ctx) {
    throw new Error("useSettings must be used within a SettingsProvider");
  }
  return ctx;
}