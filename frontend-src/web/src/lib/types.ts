// Types mirroring the FastAPI backend (api.py) responses.

export type Role = "customer" | "internal";

export interface AuthCtx {
  role: Role;
  account_id?: string | null;
}

export interface ToolLogEntry {
  tool?: string;
  args?: Record<string, unknown>;
  ok?: boolean;
  confirmed?: boolean;
  result?: unknown;
}

export interface Ruling {
  tool: string;
  question_type: string;
  rule_applied: string;
  answer: string;
}

export interface Evidence {
  sources_used: string[];
  sources_overridden: string[];
  historical_conflicts: string[];
  confidence: "high" | "medium" | "low";
  escalate: boolean;
  escalate_reason: string | null;
  rulings: Ruling[];
}

export interface Decision {
  escalate: boolean;
  confidence: "high" | "medium" | "low";
  escalate_reason: string | null;
}

interface BaseResponse {
  thread_id: string;
  tool_log: ToolLogEntry[];
  evidence: Evidence;
  decision: Decision;
}

export interface DoneResponse extends BaseResponse {
  status: "done";
  answer: string;
}

export interface ConfirmNeededResponse extends BaseResponse {
  status: "needs_confirmation";
  preview: string;
  plan: Record<string, unknown>;
}

export type ChatResponse = DoneResponse | ConfirmNeededResponse;

// --- proactive ops -----------------------------------------------------------
export interface SLAAlert {
  ticket_id: string;
  account_id: string;
  subject: string;
  severity: string;
  target_min: number;
  elapsed_min: number;
  basis: string;
  status: "breached" | "approaching" | "ok";
  sources: string[];
}

export interface Cluster {
  theme: string;
  open_ticket_ids: string[];
  accounts: string[];
  historical_ticket_ids: string[];
  known_issue: string | null;
  multi_account: boolean;
}

export interface HighSeverity {
  ticket_id: string;
  account_id: string;
  subject: string;
  reason: string;
}

export interface OpsSummary {
  snapshot: string;
  sla_breaches: SLAAlert[];
  sla_approaching: SLAAlert[];
  clusters: Cluster[];
  high_severity: HighSeverity[];
}
