"use client";

import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Message } from "@/lib/types";
import { useSettings } from "./SettingsProvider";

type Rating = "up" | "down";

interface FeedbackControlsProps {
  /** Request_ID from the stream's meta/done events — links feedback to the trace. */
  requestId: string;
  /** Current feedback state stored on the message. */
  feedback?: Message["feedback"];
  /** Persist the new feedback state on the message (and into the chat store). */
  onFeedbackChange?: (feedback: NonNullable<Message["feedback"]>) => void;
}

/**
 * Thumbs up/down controls for an assistant answer. Submission goes to
 * POST /api/feedback via `apiClient.submitFeedback` (10 s timeout):
 * - success → brief confirmation, then the controls disappear for good
 * - error/timeout → a "not saved" indicator; controls stay for retry and
 *   the chat itself is never affected
 */
export function FeedbackControls({
  requestId,
  feedback,
  onFeedbackChange,
}: FeedbackControlsProps) {
  const { t } = useSettings();
  const [submitting, setSubmitting] = useState<Rating | null>(null);
  const [justConfirmed, setJustConfirmed] = useState(false);

  // Auto-dismiss the confirmation after a moment.
  useEffect(() => {
    if (!justConfirmed) return;
    const id = setTimeout(() => setJustConfirmed(false), 1800);
    return () => clearTimeout(id);
  }, [justConfirmed]);

  const submit = async (rating: Rating) => {
    if (submitting) return;
    setSubmitting(rating);
    try {
      await apiClient.submitFeedback(requestId, rating);
      setJustConfirmed(true);
      onFeedbackChange?.(rating);
    } catch {
      // Timeout / network / server error — keep the controls for retry.
      onFeedbackChange?.("error");
    } finally {
      setSubmitting(null);
    }
  };

  const saved = feedback === "up" || feedback === "down";

  // Feedback recorded and confirmation shown → nothing to render anymore.
  if (saved && !justConfirmed) return null;

  // Brief confirmation right after a successful submission.
  if (saved) {
    return (
      <span
        role="status"
        className="flex items-center gap-1.5 text-[11px] font-medium text-emerald-500"
      >
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
        {t.feedbackThanks}
      </span>
    );
  }

  const buttonClass =
    "flex items-center text-slate-400 transition-colors hover:text-gold-500 disabled:cursor-not-allowed disabled:opacity-50 dark:text-slate-500 dark:hover:text-gold-300";

  return (
    <span className="flex items-center gap-2.5">
      <button
        onClick={() => submit("up")}
        disabled={submitting !== null}
        aria-label={t.feedbackUp}
        title={t.feedbackUp}
        className={buttonClass}
      >
        {submitting === "up" ? (
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-gold-400/30 border-t-gold-500" />
        ) : (
          <svg
            className="h-3.5 w-3.5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M7 10v12" />
            <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
          </svg>
        )}
      </button>

      <button
        onClick={() => submit("down")}
        disabled={submitting !== null}
        aria-label={t.feedbackDown}
        title={t.feedbackDown}
        className={buttonClass}
      >
        {submitting === "down" ? (
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-gold-400/30 border-t-gold-500" />
        ) : (
          <svg
            className="h-3.5 w-3.5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M17 14V2" />
            <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
          </svg>
        )}
      </button>

      {feedback === "error" && (
        <span
          role="status"
          className="text-[11px] font-medium text-crimson-500 dark:text-crimson-400"
        >
          {t.feedbackNotSaved}
        </span>
      )}
    </span>
  );
}
