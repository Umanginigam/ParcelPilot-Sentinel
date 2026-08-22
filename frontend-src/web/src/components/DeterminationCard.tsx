"use client";

import type { ChatResponse, ToolLogEntry } from "@/lib/types";

export interface CaseRecord {
  id: number;
  question: string;
  res: ChatResponse | null;
  loading: boolean;
}

type Verdict = { label: string; color: string; ring: string; accent: string };

function verdictOf(res: ChatResponse | null): Verdict {
  if (!res) return { label: "PROCESSING", color: "text-faint", ring: "border-faint", accent: "var(--color-faint)" };
  if (res.status === "needs_confirmation")
    return { label: "HELD FOR SIGN-OFF", color: "text-held", ring: "border-held", accent: "var(--color-held)" };
  const denied = res.tool_log.some(
    (e) => e.ok === false && (e.result as { error?: string })?.error === "access_denied",
  );
  if (denied) return { label: "ACCESS DENIED", color: "text-blocked", ring: "border-blocked", accent: "var(--color-blocked)" };
  if (res.decision.escalate)
    return { label: "ESCALATED", color: "text-held", ring: "border-held", accent: "var(--color-held)" };
  if (res.evidence.rulings.length || res.evidence.sources_used.length)
    return { label: "DETERMINED", color: "text-cleared", ring: "border-cleared", accent: "var(--color-cleared)" };
  return { label: "NOTED", color: "text-ink-soft", ring: "border-rule", accent: "var(--color-rule)" };
}

function Stamp({ v }: { v: Verdict }) {
  return (
    <div
      className={`animate-stamp select-none border-2 ${v.ring} ${v.color} px-2.5 py-1 font-head text-[11px] font-bold uppercase tracking-[0.15em]`}
      style={{ transform: "rotate(-4deg)" }}
    >
      {v.label}
    </div>
  );
}

function Confidence({ level }: { level: "high" | "medium" | "low" }) {
  const bars = level === "high" ? 3 : level === "medium" ? 2 : 1;
  const color = level === "high" ? "text-cleared" : level === "medium" ? "text-held" : "text-blocked";
  return (
    <span className={`inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-widest ${color}`}>
      <span className="flex items-end gap-0.5">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className={`bar-fill w-1 ${i < bars ? "bg-current" : "bg-rule"}`}
            style={{ height: `${8 + i * 3}px`, animationDelay: `${i * 90}ms` }}
          />
        ))}
      </span>
      {level} confidence
    </span>
  );
}

function ChainOfAuthority({ res }: { res: ChatResponse }) {
  const { sources_used, sources_overridden, historical_conflicts } = res.evidence;
  if (!sources_used.length && !sources_overridden.length && !historical_conflicts.length) return null;

  const rows = [
    ...sources_used.map((s) => ({ s, tag: "Governs", tagCls: "text-cleared", dot: "before:border-cleared before:bg-cleared", text: "text-ink" })),
    ...sources_overridden.map((s) => ({ s, tag: "Overridden", tagCls: "text-faint", dot: "before:border-faint before:bg-paper", text: "text-ink-soft line-through decoration-faint/50" })),
    ...historical_conflicts.map((s) => ({ s, tag: "Ignored — conflicting history", tagCls: "text-held", dot: "before:border-held before:bg-paper", text: "text-ink-soft" })),
  ];

  return (
    <div className="mt-4 border-t border-rule pt-3">
      <p className="mb-2 font-mono text-[10px] uppercase tracking-widest text-faint">Chain of authority</p>
      <div className="ml-1 space-y-2.5 border-l border-rule pl-3">
        {rows.map((r, i) => (
          <div
            key={i}
            style={{ animationDelay: `${i * 110}ms` }}
            className={`node-in relative pl-5 before:absolute before:left-0 before:top-1.5 before:h-2.5 before:w-2.5 before:rounded-full before:border-2 ${r.dot}`}
          >
            <span className={`font-mono text-[9px] uppercase tracking-widest ${r.tagCls}`}>{r.tag}</span>
            <p className={`text-sm ${r.text}`}>{r.s}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function TraceLog({ log }: { log: ToolLogEntry[] }) {
  if (!log.length) return null;
  return (
    <details className="mt-3 border-t border-rule pt-3">
      <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-widest text-faint hover:text-ink-soft">
        Dispatch log · {log.length} step{log.length > 1 ? "s" : ""}
      </summary>
      <ol className="mt-2 space-y-1 font-mono text-[11px]">
        {log.map((e, i) => {
          const status =
            e.confirmed === true ? "committed"
            : e.confirmed === false ? "cancelled"
            : e.ok === false ? "blocked" : "ok";
          const dot = status === "blocked" ? "bg-blocked" : status === "cancelled" ? "bg-faint" : "bg-cleared";
          return (
            <li key={i} className="flex items-center gap-2 text-ink-soft">
              <span className="text-faint">{String(i + 1).padStart(2, "0")}</span>
              <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
              <span className="text-ink">{e.tool}</span>
              <span className="text-faint">{status}</span>
            </li>
          );
        })}
      </ol>
    </details>
  );
}

export function DeterminationCard({
  record,
  busy,
  onDecision,
  index = 0,
}: {
  record: CaseRecord;
  busy: boolean;
  onDecision: (threadId: string, approved: boolean) => void;
  index?: number;
}) {
  const v = verdictOf(record.res);
  const res = record.res;
  const rule = res && res.status === "done" ? res.evidence.rulings[0]?.rule_applied : undefined;

  return (
    <article
      style={{ animationDelay: `${index * 60}ms`, borderLeft: `3px solid ${v.accent}` }}
      className="lift animate-rise border border-rule bg-card p-5 shadow-[2px_2px_0_0_var(--color-rule)]"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <span className="font-mono text-[10px] uppercase tracking-widest text-faint">
            Case {String(record.id).padStart(4, "0")}
          </span>
          <p className="mt-1 font-head text-[15px] font-medium leading-snug text-ink">
            {record.question}
          </p>
        </div>
        <Stamp v={v} />
      </div>

      <div className="mt-4">
        {record.loading && <p className="font-mono text-xs text-faint">Reasoning over sources…</p>}

                {res && res.status === "done" && (
          <div className="overflow-hidden rounded-sm border border-rule">
            <div
              className="px-4 py-3"
              style={{
                borderLeft: `3px solid ${v.accent}`,
                background: `color-mix(in srgb, ${v.accent} 5%, var(--color-card))`,
              }}
            >
              <p
                className="mb-1.5 font-mono text-[9px] font-semibold uppercase tracking-[0.2em]"
                style={{ color: v.accent }}
              >
                Ruling
              </p>
              <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-ink">
                {res.answer}
              </p>
            </div>
            {rule && (
              <div className="border-t border-rule bg-paper/50 px-4 py-2">
                <span className="font-mono text-[9px] uppercase tracking-widest text-faint">
                  Rule applied ·{" "}
                </span>
                <span className="font-mono text-[11px] text-ink-soft">{rule}</span>
              </div>
            )}
          </div>
        )}

        {res && res.status === "needs_confirmation" && (
          <div className="border border-held/40 bg-held/[0.06] p-3">
            <p className="font-mono text-[10px] uppercase tracking-widest text-held">Awaiting your sign-off</p>
            <pre className="mt-2 whitespace-pre-wrap font-mono text-xs text-ink">{res.preview}</pre>
            <div className="mt-3 flex gap-2">
              <button
                disabled={busy}
                onClick={() => onDecision(res.thread_id, true)}
                className="bg-cleared px-3 py-1.5 font-mono text-[11px] uppercase tracking-widest text-paper transition hover:brightness-110 disabled:opacity-40"
              >
                Approve
              </button>
              <button
                disabled={busy}
                onClick={() => onDecision(res.thread_id, false)}
                className="border border-rule px-3 py-1.5 font-mono text-[11px] uppercase tracking-widest text-ink-soft transition hover:bg-paper disabled:opacity-40"
              >
                Reject
              </button>
            </div>
          </div>
        )}
      </div>

      {res && res.status === "done" && <ChainOfAuthority res={res} />}

      {res && (
        <div className="mt-4 flex items-center justify-between border-t border-rule pt-3">
          <Confidence level={res.decision.confidence} />
          {res.decision.escalate && (
            <span className="font-mono text-[10px] uppercase tracking-widest text-held">
              routed to a human{res.decision.escalate_reason ? ` · ${res.decision.escalate_reason}` : ""}
            </span>
          )}
        </div>
      )}

      {res && <TraceLog log={res.tool_log} />}
    </article>
  );
}