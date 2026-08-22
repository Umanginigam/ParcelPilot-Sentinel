"use client";

import type { AuthCtx } from "@/lib/types";
import { ContextSwitcher } from "./ContextSwitcher";

export function Masthead({
  ctx,
  onChange,
  tab,
  onTab,
}: {
  ctx: AuthCtx;
  onChange: (c: AuthCtx) => void;
  tab: "desk" | "board";
  onTab: (t: "desk" | "board") => void;
}) {
  return (
    <header>
      <div className="mx-auto flex max-w-5xl items-end justify-between px-6 pt-6 pb-3">
        <div>
          <div className="flex items-center gap-2.5">
            <span
              className="grid h-8 w-8 place-items-center rounded-sm font-head text-sm font-bold text-paper shadow-sm"
              style={{
                backgroundImage:
                  "linear-gradient(135deg, var(--color-accent), var(--color-accent-bright))",
              }}
            >
              S
            </span>
            <h1 className="font-head text-xl font-bold tracking-tight text-ink">
              ParcelPilot Sentinel
            </h1>
          </div>
          <p className="mt-1.5 font-mono text-[10px] uppercase tracking-[0.2em] text-faint">
            Clearance desk · sourced determinations for support
          </p>
        </div>

        <div className="flex items-center gap-3">
          <ContextSwitcher ctx={ctx} onChange={onChange} />
          <nav className="flex gap-4 font-mono text-[11px] uppercase tracking-widest">
            {(["desk", "board"] as const).map((t) => (
              <button
                key={t}
                onClick={() => onTab(t)}
                disabled={t === "board" && ctx.role !== "internal"}
                title={t === "board" && ctx.role !== "internal" ? "Internal Ops only" : ""}
                className={`pb-1 transition disabled:opacity-30 ${
                  tab === t
                    ? "border-b-2 border-accent-bright text-ink"
                    : "border-b-2 border-transparent text-faint hover:text-ink-soft"
                }`}
              >
                {t}
              </button>
            ))}
          </nav>
        </div>
      </div>

      {/* animated dispatch tracking line */}
      <div className="signal-line h-[3px] w-full" />
    </header>
  );
}