"""STEP 3 — secure structured-data tools + guarded action tool.

These are the functions the agent is allowed to call. Access control is enforced
HERE (in code, against the AuthContext), not in the system prompt. A customer
context physically cannot retrieve another account's rows: the account_id is
derived from the context, and any cross-account read raises AccessDenied.

The action tool is two-phase: prepare_escalation() returns a plan and NEVER
mutates state; commit_escalation() performs the (mocked) write and is only
reached after explicit user confirmation in the orchestration layer.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

from . import db
from .auth import AuthContext
from . import config as C


# --- read tools (scoped) -----------------------------------------------------
def lookup_order(ctx: AuthContext, order_id: str) -> dict:
    order = db.get_order(order_id)
    if not order:
        raise KeyError(f"order {order_id} not found")
    ctx.assert_can_read_account(order["account_id"])   # <-- enforcement
    return order


def lookup_account(ctx: AuthContext, account_id: str) -> dict:
    ctx.assert_can_read_account(account_id)            # <-- enforcement
    acct = db.get_account(account_id)
    if not acct:
        raise KeyError(f"account {account_id} not found")
    return acct


def lookup_ticket(ctx: AuthContext, ticket_id: str) -> dict:
    tkt = db.get_ticket(ticket_id)
    if not tkt:
        raise KeyError(f"ticket {ticket_id} not found")
    ctx.assert_can_read_account(tkt["account_id"])     # <-- enforcement
    return tkt


def list_my_orders(ctx: AuthContext, account_id: Optional[str] = None) -> list[dict]:
    """Customers list their own orders; internal staff may pass any account_id."""
    target = account_id or ctx.account_id
    if target is None:
        raise ValueError("internal context must specify account_id")
    ctx.assert_can_read_account(target)
    return db.orders_for_account(target)


# --- action tool (state-changing, two-phase, confirmation-gated) -------------
@dataclass
class EscalationPlan:
    account_id: str
    subject: str
    severity: str                    # P1 | P2 | P3
    reason: str
    linked_ticket_id: Optional[str] = None
    linked_order_id: Optional[str] = None

    def summary(self) -> str:
        parts = [f"[{self.severity}] {self.subject} for {self.account_id}"]
        if self.linked_ticket_id:
            parts.append(f"ticket={self.linked_ticket_id}")
        if self.linked_order_id:
            parts.append(f"order={self.linked_order_id}")
        parts.append(f"— {self.reason}")
        return " ".join(parts)


def prepare_escalation(ctx: AuthContext, plan: EscalationPlan) -> dict:
    """Phase 1: validate + return the plan for confirmation. No writes.

    GLOBAL escalations represent incidents affecting all users and are
    restricted to internal users.
    """

    if plan.account_id == "GLOBAL":
        if ctx.role != "internal":
            raise PermissionError(
                "only internal users can create GLOBAL escalations"
            )
    else:
        ctx.assert_can_read_account(plan.account_id)

    return {
        "action": "create_escalation",
        "requires_confirmation": True,
        "plan": asdict(plan),
        "preview": plan.summary(),
    }


def commit_escalation(ctx: AuthContext, plan: EscalationPlan) -> dict:
    """Phase 2: perform the (mocked) write. Call ONLY after user confirms."""

    if plan.account_id == "GLOBAL":
        if ctx.role != "internal":
            raise PermissionError(
                "only internal users can create GLOBAL escalations"
            )
    else:
        ctx.assert_can_read_account(plan.account_id)

    C.BUILD_DIR.mkdir(exist_ok=True)

    record = {
        "escalation_id": f"ESC-{uuid.uuid4().hex[:8]}",
        "created_at": datetime.now(C.IST).isoformat(),
        "created_by_role": ctx.role,
        **asdict(plan),
    }

    log = C.BUILD_DIR / "escalations.jsonl"

    with log.open("a") as fh:
        fh.write(json.dumps(record) + "\n")

    return {
        "status": "created",
        **record,
    }