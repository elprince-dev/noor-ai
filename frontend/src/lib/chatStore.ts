"use client";

import { School } from "@/lib/api";
import { Message } from "@/lib/types";

/**
 * Lightweight client-side conversation persistence (localStorage).
 * Gives the app a SaaS-like "chat history" experience without a backend
 * account system. Swap this for an API-backed store once auth lands.
 */

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  school: School;
  sessionId: string;
  messages: Message[];
}

const STORE_KEY = "noor.chats.v1";
const MAX_CONVERSATIONS = 50;

export function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function loadConversations(): Conversation[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Conversation[];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((c) => c && typeof c.id === "string")
      .sort((a, b) => b.updatedAt - a.updatedAt);
  } catch {
    return [];
  }
}

export function saveConversations(conversations: Conversation[]): void {
  if (typeof window === "undefined") return;
  try {
    const trimmed = [...conversations]
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, MAX_CONVERSATIONS)
      // Never persist mid-stream state.
      .map((c) => ({
        ...c,
        messages: c.messages.map((m) => ({ ...m, stream: false })),
      }));
    localStorage.setItem(STORE_KEY, JSON.stringify(trimmed));
  } catch {
    /* storage full / unavailable — history is best-effort */
  }
}

/** Derive a short title from the first user message. */
export function titleFrom(text: string): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > 48 ? `${clean.slice(0, 48)}…` : clean;
}

export type DateGroup = "today" | "yesterday" | "week" | "older";

export function groupOf(timestamp: number): DateGroup {
  const now = new Date();
  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  ).getTime();
  const day = 24 * 60 * 60 * 1000;
  if (timestamp >= startOfToday) return "today";
  if (timestamp >= startOfToday - day) return "yesterday";
  if (timestamp >= startOfToday - 7 * day) return "week";
  return "older";
}
