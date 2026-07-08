"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Reveals `text` progressively to create a streaming/typewriter effect.
 * When `enabled` is false, the full text is shown immediately (e.g. for
 * historical messages that were already "typed", or reduced-motion users).
 *
 * Returns the visible slice and whether it is still animating.
 */
export function useTypewriter(
  text: string,
  enabled: boolean = true,
  charsPerTick: number = 3,
  tickMs: number = 16,
): { shown: string; done: boolean } {
  const [count, setCount] = useState(enabled ? 0 : text.length);
  const frame = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Respect reduced-motion: reveal instantly.
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

    if (!enabled || reduce) {
      setCount(text.length);
      return;
    }

    setCount(0);
    frame.current = setInterval(() => {
      setCount((c) => {
        if (c >= text.length) {
          if (frame.current) clearInterval(frame.current);
          return c;
        }
        return Math.min(c + charsPerTick, text.length);
      });
    }, tickMs);

    return () => {
      if (frame.current) clearInterval(frame.current);
    };
  }, [text, enabled, charsPerTick, tickMs]);

  return { shown: text.slice(0, count), done: count >= text.length };
}
