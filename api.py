from __future__ import annotations

import json
import uuid
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langgraph.types import Command

from src.agent import build_agent, new_state
from src.auth import AuthContext
from src.llm import default_llm
from src import proactive as P

app = FastAPI(title="ParcelPilot Sentinel API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

_AGENT = build_agent(default_llm())      # one instance -> shared checkpointer


# --- schemas -----------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    role: Literal["customer", "internal"]
    account_id: Optional[str] = None      # required for customer


class ConfirmRequest(BaseModel):
    thread_id: str
    approved: bool


def _auth(role: str, account_id: Optional[str]) -> AuthContext:
    if role == "customer" and not account_id:
        raise HTTPException(400, "customer role requires account_id")
    return AuthContext(role=role, account_id=account_id)


_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def _is_ruling(result: Any) -> bool:
    return isinstance(result, dict) and "rule_applied" in result and "question_type" in result


def _dedup(seq: list) -> list:
    seen, out = set(), []
    for x in seq:
        key = json.dumps(x, sort_keys=True) if isinstance(x, (dict, list)) else x
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


def _evidence(tool_log: list[dict]) -> dict:
    """Aggregate the ruling metadata already present in the tool trace into a
    single evidence block the UI can render, plus a conservative top-level
    decision (lowest confidence wins; escalate if any ruling escalated)."""
    used, overridden, conflicts, rulings = [], [], [], []
    confidence = "high"
    escalate = False
    escalate_reason = None

    for entry in tool_log:
        r = entry.get("result")
        if not _is_ruling(r):
            continue
        used += r.get("sources_used", [])
        overridden += r.get("sources_overridden", [])
        conflicts += r.get("historical_conflicts", [])
        if _CONFIDENCE_RANK.get(r.get("confidence", "high"), 2) < _CONFIDENCE_RANK[confidence]:
            confidence = r["confidence"]
        if r.get("escalate"):
            escalate = True
            escalate_reason = escalate_reason or r.get("escalate_reason")
        rulings.append({"tool": entry.get("tool"),
                        "question_type": r.get("question_type"),
                        "rule_applied": r.get("rule_applied"),
                        "answer": r.get("answer")})

    return {
        "sources_used": _dedup(used),
        "sources_overridden": _dedup(overridden),
        "historical_conflicts": _dedup(conflicts),
        "confidence": confidence,
        "escalate": escalate,
        "escalate_reason": escalate_reason,
        "rulings": rulings,
    }


def _shape(result: dict, thread_id: str) -> dict:
    """Normalise a graph result into a stable API response."""
    tool_log = result.get("tool_log", [])
    evidence = _evidence(tool_log)
    decision = {"escalate": evidence["escalate"],
                "confidence": evidence["confidence"],
                "escalate_reason": evidence["escalate_reason"]}

    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        return {"status": "needs_confirmation", "thread_id": thread_id,
                "preview": payload.get("preview"), "plan": payload.get("plan"),
                "tool_log": tool_log, "evidence": evidence, "decision": decision}
    return {"status": "done", "thread_id": thread_id,
            "answer": result.get("answer"),
            "tool_log": tool_log, "evidence": evidence, "decision": decision}


# --- endpoints ---------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    ctx = _auth(req.role, req.account_id)
    thread_id = uuid.uuid4().hex
    cfg = {"configurable": {"thread_id": thread_id}}
    result = _AGENT.invoke(new_state(req.message, ctx), config=cfg)
    return _shape(result, thread_id)


@app.post("/confirm")
def confirm(req: ConfirmRequest) -> dict:
    cfg = {"configurable": {"thread_id": req.thread_id}}
    try:
        result = _AGENT.invoke(Command(resume=req.approved), config=cfg)
    except Exception:
        raise HTTPException(
            400,
            "Could not resume confirmation request."
        )
    return _shape(result, req.thread_id)

@app.get("/ops/alerts")
def ops_alerts(role: str = "internal") -> dict:
    """Proactive Ops view — authorised internal users only."""
    if role != "internal":
        raise HTTPException(403, "ops view is restricted to internal users")
    return P.ops_summary()