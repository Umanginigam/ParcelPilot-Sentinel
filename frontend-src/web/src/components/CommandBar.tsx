"use client";

import { useState } from "react";

const EXAMPLES = [
  "Can Northstar cancel ORD-1001 without a cancellation fee?",
  "Should ORD-2002 receive a service credit?",
  "Escalate TKT-501 as a P1 outage.",
];

export function CommandBar({
  busy,
  onSubmit,
  showExamples,
}: {
  busy: boolean;
  onSubmit: (text: string) => void;
  showExamples: boolean;
}) {
  const [value, setValue] = useState("");

  function go() {
    const t = value.trim();
    if (!t || busy) return;
    onSubmit(t);
    setValue("");
  }

  return (
    <div>
      <div className="glow-focus flex items-center gap-3 border border-ink bg-card px-3 py-2.5 shadow-[3px_3px_0_0_var(--color-rule)] transition">
        <span className={`font-mono text-sm ${busy ? "text-accent-bright" : "text-accent"} ${busy ? "animate-pulse" : ""}`}>
          ›
        </span>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && go()}
          placeholder="Open a case — ask about a cancellation, credit, SLA, or escalation…"
          className="flex-1 bg-transparent font-sans text-sm text-ink placeholder:text-faint outline-none"
        />
        <button
          onClick={go}
          disabled={busy}
          className="px-4 py-1.5 font-mono text-[11px] uppercase tracking-widest text-paper transition hover:brightness-110 disabled:opacity-40"
          style={{
            backgroundImage:
              "linear-gradient(135deg, var(--color-accent), var(--color-accent-bright))",
          }}
        >
          {busy ? "Working" : "File case"}
        </button>
      </div>

      {showExamples && (
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((ex, i) => (
            <button
              key={ex}
              onClick={() => onSubmit(ex)}
              style={{ animationDelay: `${i * 70}ms` }}
              className="animate-rise border border-rule bg-card px-2.5 py-1 text-xs text-ink-soft transition hover:-translate-y-0.5 hover:border-accent-bright hover:text-ink"
            >
              {ex}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}