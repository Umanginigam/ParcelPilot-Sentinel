"use client";

import { useEffect, useState } from "react";
import { fetchOps } from "@/lib/api";
import type { OpsSummary } from "@/lib/types";

export function OpsBoard() {
  const [data, setData] = useState<OpsSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetchOps().then(setData).catch((e) => setErr(String(e)));
  }, []);

  if (err)
    return (
      <p className="text-sm text-blocked">
        Couldn&apos;t load the board. Confirm the backend is running. ({err})
      </p>
    );
  if (!data) return <p className="font-mono text-xs text-faint">Scanning support activity…</p>;

  return (
    <div className="animate-rise space-y-8">
      <div className="grid grid-cols-3 gap-4">
        
<Tile n={data.sla_breaches.length} label="SLA breaches" tone="text-blocked" bar="var(--color-blocked)" />
<Tile n={data.high_severity.length} label="High severity" tone="text-held" bar="var(--color-held)" />
<Tile n={data.clusters.length} label="Issue clusters" tone="text-accent" bar="linear-gradient(90deg,var(--color-accent),var(--color-accent-bright))" />
      </div>

      <Block title="SLA breaches">
        {data.sla_breaches.map((a) => (
          <Card key={a.ticket_id} id={a.ticket_id} stamp="BREACHED" stampCls="border-blocked text-blocked">
            <p className="text-sm text-ink">{a.subject}</p>
            <p className="mt-1 font-mono text-[11px] text-faint">
              {a.account_id} · {a.severity} · target {a.target_min}m · elapsed {a.elapsed_min}m ({a.basis})
            </p>
          </Card>
        ))}
        {!data.sla_breaches.length && <Empty />}
      </Block>

      <Block title="High severity">
        {data.high_severity.map((h) => (
          <Card key={h.ticket_id} id={h.ticket_id} stamp="P1" stampCls="border-held text-held">
            <p className="text-sm text-ink">{h.subject}</p>
            <p className="mt-1 font-mono text-[11px] text-held">{h.reason}</p>
          </Card>
        ))}
        {!data.high_severity.length && <Empty />}
      </Block>

      <Block title="Issue clusters">
        {data.clusters.map((c) => (
          <div key={c.theme} className="border border-rule bg-card p-3">
            <div className="flex items-center justify-between">
              <span className="font-head text-sm font-medium text-ink">{c.theme}</span>
              {c.multi_account && (
                <span className="border border-held px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-widest text-held">
                  multi-account
                </span>
              )}
            </div>
            <p className="mt-1 font-mono text-[11px] text-faint">
              open: {c.open_ticket_ids.join(", ") || "—"} · accounts: {c.accounts.join(", ")}
            </p>
            {c.historical_ticket_ids.length > 0 && (
              <p className="mt-1 text-xs text-held">↺ recurring — history: {c.historical_ticket_ids.join(", ")}</p>
            )}
            {c.known_issue && <p className="mt-1 text-xs text-accent">↳ {c.known_issue}</p>}
          </div>
        ))}
      </Block>
    </div>
  );
}


// the Tile component:
function Tile({ n, label, tone, bar }: { n: number; label: string; tone: string; bar: string }) {
  return (
    <div className="lift border border-rule bg-card p-4">
      <div className="mb-2 h-1 w-8" style={{ background: bar }} />
      <div className={`count-pop font-head text-4xl font-bold tabular-nums ${tone}`}>{n}</div>
      <div className="mt-1 font-mono text-[10px] uppercase tracking-widest text-faint">{label}</div>
    </div>
  );
}
function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-3 border-b border-rule pb-1 font-mono text-[10px] uppercase tracking-widest text-faint">
        {title}
      </h3>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function Card({
  id,
  stamp,
  stampCls,
  children,
}: {
  id: string;
  stamp: string;
  stampCls: string;
  children: React.ReactNode;
}) {
  return (
    <div className="border border-rule bg-card p-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm font-semibold text-ink">{id}</span>
        <span className={`border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-widest ${stampCls}`}>
          {stamp}
        </span>
      </div>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function Empty() {
  return <p className="font-mono text-xs text-faint">Nothing flagged.</p>;
}
