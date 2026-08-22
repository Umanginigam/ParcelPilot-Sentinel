"""Agent tool registry — the bridge between the LLM and the deterministic core.

Every tool the model can call is declared here with a JSON schema (what the LLM
sees) and a handler (what actually runs). Handlers receive the AuthContext, so
scoping is enforced no matter what the model asks for.

Tools are grouped by the three required kinds:
  1. document retrieval        -> doc_search
  2. structured lookup/calc    -> lookup_*, resolve_* (the resolution engine)
  3. state-changing action     -> create_escalation  (marked write=True)

`write=True` tools are NOT executed inline; the graph routes them through an
interrupt() confirmation gate first.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable

from . import tools as T
from . import resolution_engine as E
from .auth import AuthContext
from .retriever import BM25Retriever

_RETRIEVER: BM25Retriever | None = None


def _retriever() -> BM25Retriever:
    global _RETRIEVER
    if _RETRIEVER is None:
        _RETRIEVER = BM25Retriever.from_build()
    return _RETRIEVER


@dataclass
class AgentTool:
    name: str
    description: str
    parameters: dict          # JSON schema
    handler: Callable         # (ctx, **args) -> dict
    write: bool = False       # True => confirmation-gated

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description,
                "parameters": self.parameters}


def _obj(props: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


# --- handlers ----------------------------------------------------------------
def _doc_search(ctx, query: str, k: int = 5) -> dict:
    hits = _retriever().retrieve(
        query=query,
        account_id=ctx.account_id,
        include_all_accounts=ctx.is_internal,
        k=k,
    )

    return {
        "results": [
            {
                "doc_id": h.section.doc_id,
                "heading": h.section.heading,
                "text": h.section.text[:600],
                "score": round(h.score, 2),
                "context_only": h.context_only,
            }
            for h in hits
        ]
    }

def _lookup_order(ctx, order_id: str) -> dict:
    return T.lookup_order(ctx, order_id)


def _lookup_account(ctx, account_id: str) -> dict:
    return T.lookup_account(ctx, account_id)


def _lookup_ticket(ctx, ticket_id: str) -> dict:
    return T.lookup_ticket(ctx, ticket_id)


def _resolve_cancellation(ctx, order_id: str) -> dict:
    T.lookup_order(ctx, order_id)             # enforce scope before ruling
    return asdict(E.resolve_cancellation(order_id))


def _resolve_service_credit(ctx, order_id: str) -> dict:
    T.lookup_order(ctx, order_id)
    return asdict(E.resolve_service_credit(order_id))


def _resolve_sla(ctx, account_id: str, severity: str) -> dict:
    T.lookup_account(ctx, account_id)
    return asdict(E.resolve_sla(account_id, severity))


def _classify_escalation(ctx, subject: str, description: str) -> dict:
    return asdict(E.classify_escalation(subject, description))


def _create_escalation(ctx, account_id: str, subject: str, severity: str,
                       reason: str, linked_ticket_id: str | None = None,
                       linked_order_id: str | None = None) -> dict:
    """Write handler. The graph calls prepare_escalation for the confirmation
    preview and commit_escalation only after the user confirms."""
    plan = T.EscalationPlan(account_id=account_id, subject=subject,
                            severity=severity, reason=reason,
                            linked_ticket_id=linked_ticket_id,
                            linked_order_id=linked_order_id)
    return T.commit_escalation(ctx, plan)


# --- registry ----------------------------------------------------------------
TOOLS: list[AgentTool] = [
    AgentTool("doc_search",
              "Search ParcelPilot policies, SOPs, product docs and customer "
              "agreements for relevant passages. Results tagged context_only=true "
              "are deprecated or historical and must NOT be treated as authoritative.",
              _obj({"query": {"type": "string"},
                    "k": {"type": "integer"}}, ["query"]), _doc_search),
    AgentTool("lookup_order", "Get an order row by id (scoped to the caller).",
              _obj({"order_id": {"type": "string"}}, ["order_id"]), _lookup_order),
    AgentTool("lookup_account", "Get an account row by id (scoped to the caller).",
              _obj({"account_id": {"type": "string"}}, ["account_id"]), _lookup_account),
    AgentTool("lookup_ticket", "Get a ticket row by id (scoped to the caller).",
              _obj({"ticket_id": {"type": "string"}}, ["ticket_id"]), _lookup_ticket),
    AgentTool("resolve_cancellation",
              "Authoritative ruling on whether an order can be cancelled and any "
              "fee, applying agreement-over-SOP precedence. Prefer this over "
              "reading policy text yourself.",
              _obj({"order_id": {"type": "string"}}, ["order_id"]),
              _resolve_cancellation),
    AgentTool("resolve_service_credit",
              "Authoritative ruling on failed-pickup service-credit eligibility "
              "and amount for an order, applying account-specific overrides.",
              _obj({"order_id": {"type": "string"}}, ["order_id"]),
              _resolve_service_credit),
    AgentTool("resolve_sla",
              "Authoritative first-response SLA target for an account + severity "
              "(P1/P2/P3), applying agreement overrides.",
              _obj({"account_id": {"type": "string"},
                    "severity": {"type": "string"}}, ["account_id", "severity"]),
              _resolve_sla),
    AgentTool("classify_escalation",
              "Classify a described issue for P1 triggers (security exposure, full "
              "outage). Use before deciding whether to escalate.",
              _obj({"subject": {"type": "string"},
                    "description": {"type": "string"}}, ["subject", "description"]),
              _classify_escalation),
    AgentTool("create_escalation",
              "Create an escalation. STATE-CHANGING: requires explicit user "
              "confirmation, which the system enforces before it runs.",
              _obj({"account_id": {"type": "string"}, "subject": {"type": "string"},
                    "severity": {"type": "string"}, "reason": {"type": "string"},
                    "linked_ticket_id": {"type": "string"},
                    "linked_order_id": {"type": "string"}},
                   ["account_id", "subject", "severity", "reason"]),
              _create_escalation, write=True),
]

BY_NAME: dict[str, AgentTool] = {t.name: t for t in TOOLS}


def schemas() -> list[dict]:
    return [t.schema() for t in TOOLS]
