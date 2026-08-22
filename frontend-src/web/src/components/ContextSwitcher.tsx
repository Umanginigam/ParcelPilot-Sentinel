"use client";

import type { AuthCtx } from "@/lib/types";

const ACCOUNTS = [
  { id: "ACCT-001", name: "Northstar" },
  { id: "ACCT-002", name: "LumenWorks" },
  { id: "ACCT-003", name: "Beacon" },
  { id: "ACCT-004", name: "Axis Labs" },
];

export function ContextSwitcher({
  ctx,
  onChange,
}: {
  ctx: AuthCtx;
  onChange: (ctx: AuthCtx) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="font-mono text-[10px] uppercase tracking-widest text-faint">Acting as</span>
      <div className="flex overflow-hidden rounded-sm border border-rule text-[11px]">
        {(["customer", "internal"] as const).map((role) => (
          <button
            key={role}
            onClick={() =>
              onChange(
                role === "internal"
                  ? { role: "internal", account_id: null }
                  : { role: "customer", account_id: ctx.account_id ?? "ACCT-001" },
              )
            }
            className={`px-2.5 py-1 font-medium transition ${
              ctx.role === role ? "bg-ink text-paper" : "bg-card text-ink-soft hover:bg-paper"
            }`}
          >
            {role === "customer" ? "Customer" : "Ops"}
          </button>
        ))}
      </div>
      {ctx.role === "customer" && (
        <select
          value={ctx.account_id ?? "ACCT-001"}
          onChange={(e) => onChange({ role: "customer", account_id: e.target.value })}
          className="rounded-sm border border-rule bg-card px-2 py-1 font-mono text-[11px] text-ink outline-none focus:border-accent"
        >
          {ACCOUNTS.map((a) => (
            <option key={a.id} value={a.id}>
              {a.id} · {a.name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
