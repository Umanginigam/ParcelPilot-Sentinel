"use client";

import { useState } from "react";
import { Masthead } from "@/components/Masthead";
import { CommandBar } from "@/components/CommandBar";
import { DeterminationCard, type CaseRecord } from "@/components/DeterminationCard";
import { OpsBoard } from "@/components/OpsBoard";
import { sendChat, confirmAction } from "@/lib/api";
import type { AuthCtx, ChatResponse } from "@/lib/types";

export default function Home() {
  const [tab, setTab] = useState<"desk" | "board">("desk");
  const [ctx, setCtx] = useState<AuthCtx>({ role: "customer", account_id: "ACCT-001" });
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nextId, setNextId] = useState(1);

  function patch(id: number, res: ChatResponse) {
    setCases((cs) => cs.map((c) => (c.id === id ? { ...c, res, loading: false } : c)));
  }

  async function handleSubmit(text: string) {
    setError(null);
    setBusy(true);
    const id = nextId;
    setNextId((n) => n + 1);
    setCases((cs) => [{ id, question: text, res: null, loading: true }, ...cs]);
    try {
      patch(id, await sendChat(text, ctx));
    } catch (e) {
      setError(String(e));
      setCases((cs) => cs.filter((c) => c.id !== id));
    } finally {
      setBusy(false);
    }
  }

  async function handleDecision(threadId: string, approved: boolean) {
    const target = cases.find(
      (c) => c.res?.status === "needs_confirmation" && c.res.thread_id === threadId,
    );
    if (!target) return;
    setBusy(true);
    try {
      patch(target.id, await confirmAction(threadId, approved));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const onBoard = tab === "board" && ctx.role === "internal";

  return (
    <div className="min-h-screen">
      <Masthead ctx={ctx} onChange={setCtx} tab={tab} onTab={setTab} />

      <main className="mx-auto max-w-5xl px-6 py-6">
        {error && (
          <div className="mb-4 border border-blocked/40 bg-blocked/[0.06] px-3 py-2 text-sm text-blocked">
            {error}
          </div>
        )}

        {onBoard ? (
          <OpsBoard />
        ) : (
          <>
            <CommandBar busy={busy} onSubmit={handleSubmit} showExamples={cases.length === 0} />

            {cases.length === 0 ? (
              <div className="mt-16 text-center">
                <p className="font-head text-lg text-ink-soft">No cases yet.</p>
                <p className="mt-1 text-sm text-faint">
                  File a case above. Every determination shows the sources that governed it.
                </p>
              </div>
            ) : (
              <div className="mt-6 space-y-4">
                {cases.map((c,i) => (
                  <DeterminationCard
                    key={c.id}
                    record={c}
                    busy={busy}
                    onDecision={handleDecision}
                    index={i}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
