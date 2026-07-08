"use client";

/**
 * Ambient animated backdrop.
 * Layered radial gradients (royal blue · gold · faint crimson) drifting slowly
 * over the canvas, plus a subtle dotted grid for depth. Purely decorative —
 * sits behind all content and ignores pointer events. Tones down in light mode.
 */
export function AuroraBackground() {
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 z-0 overflow-hidden bg-slate-50 dark:bg-ink-950"
    >
      {/* Base radial wash */}
      <div className="absolute inset-0 bg-ink-radial opacity-40 dark:opacity-100" />

      {/* Drifting gold bloom */}
      <div className="absolute -left-24 top-[-10%] h-[38rem] w-[38rem] animate-aurora rounded-full bg-gold-500/10 blur-[120px] dark:bg-gold-500/20" />

      {/* Drifting royal-blue bloom */}
      <div
        className="absolute -right-32 top-[20%] h-[42rem] w-[42rem] animate-aurora rounded-full bg-royal-500/10 blur-[130px] dark:bg-royal-500/20"
        style={{ animationDelay: "-6s" }}
      />

      {/* Faint crimson accent bloom */}
      <div
        className="absolute bottom-[-15%] left-1/3 h-[34rem] w-[34rem] animate-aurora rounded-full bg-crimson-500/[0.06] blur-[120px] dark:bg-crimson-500/10"
        style={{ animationDelay: "-11s" }}
      />

      {/* Fine dotted grid */}
      <div
        className="absolute inset-0 opacity-[0.03] dark:opacity-[0.04]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, currentColor 1px, transparent 0)",
          backgroundSize: "32px 32px",
        }}
      />

      {/* Vignette to keep edges grounded (dark only) */}
      <div className="absolute inset-0 hidden bg-[radial-gradient(ellipse_at_center,transparent_55%,rgba(4,6,13,0.9)_100%)] dark:block" />
    </div>
  );
}