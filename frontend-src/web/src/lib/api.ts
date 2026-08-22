import type { AuthCtx, ChatResponse, OpsSummary } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(
      (detail as { detail?: string })?.detail ?? `${path} failed (${res.status})`,
    );
  }
  return res.json() as Promise<T>;
}

export function sendChat(message: string, ctx: AuthCtx): Promise<ChatResponse> {
  return post<ChatResponse>("/chat", {
    message,
    role: ctx.role,
    account_id: ctx.account_id ?? null,
  });
}

export function confirmAction(
  threadId: string,
  approved: boolean,
): Promise<ChatResponse> {
  return post<ChatResponse>("/confirm", {
    thread_id: threadId,
    approved,
  });
}

export async function fetchOps(): Promise<OpsSummary> {
  const res = await fetch(`${BASE}/ops/alerts?role=internal`);
  if (!res.ok) throw new Error(`ops fetch failed (${res.status})`);
  return res.json() as Promise<OpsSummary>;
}
