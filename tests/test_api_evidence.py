"""Full API test suite for api.py (Step 8) — no GROQ_API_KEY needed.

Every test injects a scripted StubLLM via default_llm() and reloads the api
module so the shared agent is driven deterministically. This exercises the real
FastAPI app end to end: routing, auth/scoping, the interrupt/resume confirmation
gate, the proactive Ops endpoint, and the aggregated evidence/decision blocks.
"""
import importlib

import src.llm as L
from src.llm import StubLLM, Decision, ToolCall


def _client(script):
    """Build a TestClient whose agent is driven by the given scripted decisions.
    Reloading api rebuilds its module-level _AGENT against our stub."""
    L.default_llm = lambda: StubLLM(script=script)
    import api
    importlib.reload(api)
    from fastapi.testclient import TestClient
    return TestClient(api.app)


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------
def test_health_ok():
    c = _client([Decision(text="hi")])
    assert c.get("/health").json() == {"ok": True}


# ---------------------------------------------------------------------------
# /chat — resolver ruling + evidence surfacing
# ---------------------------------------------------------------------------
def test_chat_resolver_returns_answer_and_evidence():
    c = _client([
        Decision(tool_call=ToolCall("resolve_cancellation", {"order_id": "ORD-1001"})),
        Decision(text="No fee — the Northstar agreement governs."),
    ])
    r = c.post("/chat", json={"message": "cancel ORD-1001?", "role": "internal"}).json()
    assert r["status"] == "done"
    assert r["answer"].startswith("No fee")
    assert r["tool_log"][0]["tool"] == "resolve_cancellation"

    ev = r["evidence"]
    assert "05_Northstar_Logistics_Enterprise_Agreement.pdf" in ev["sources_used"]
    assert ev["sources_overridden"]                       # SOP recorded as overridden
    assert any("TKT-450" in h for h in ev["historical_conflicts"])
    assert r["decision"] == {"escalate": False, "confidence": "high",
                             "escalate_reason": None}


def test_chat_escalation_sets_decision_badge():
    c = _client([
        Decision(tool_call=ToolCall("resolve_service_credit", {"order_id": "ORD-2001"})),
        Decision(text="Escalating for human review."),
    ])
    r = c.post("/chat", json={"message": "credit ORD-2001?", "role": "internal"}).json()
    assert r["decision"]["escalate"] is True
    assert r["decision"]["confidence"] == "low"
    assert r["decision"]["escalate_reason"]


def test_chat_non_ruling_turn_has_valid_empty_evidence():
    c = _client([
        Decision(tool_call=ToolCall("lookup_order", {"order_id": "ORD-1001"})),
        Decision(text="Cannot access that account."),
    ])
    r = c.post("/chat", json={"message": "show ORD-1001", "role": "customer",
                              "account_id": "ACCT-002"}).json()
    assert r["evidence"]["rulings"] == []
    assert r["decision"] == {"escalate": False, "confidence": "high",
                             "escalate_reason": None}


# ---------------------------------------------------------------------------
# /chat — access control + validation
# ---------------------------------------------------------------------------
def test_chat_customer_cannot_read_other_account_order():
    c = _client([
        Decision(tool_call=ToolCall("lookup_order", {"order_id": "ORD-1001"})),
        Decision(text="I can only access your own account."),
    ])
    r = c.post("/chat", json={"message": "show ORD-1001", "role": "customer",
                              "account_id": "ACCT-002"}).json()
    assert r["tool_log"][0]["ok"] is False
    assert r["tool_log"][0]["result"]["error"] == "access_denied"


def test_chat_customer_without_account_id_is_400():
    c = _client([Decision(text="x")])
    resp = c.post("/chat", json={"message": "hi", "role": "customer"})
    assert resp.status_code == 400


def test_chat_rejects_unknown_role_via_schema():
    c = _client([Decision(text="x")])
    resp = c.post("/chat", json={"message": "hi", "role": "admin"})
    assert resp.status_code == 422        # pydantic Literal validation


# ---------------------------------------------------------------------------
# /chat + /confirm — the confirmation gate over HTTP
# ---------------------------------------------------------------------------
def test_write_action_pauses_then_commits_on_confirm():
    c = _client([
        Decision(tool_call=ToolCall("create_escalation", {
            "account_id": "ACCT-001", "subject": "All shipment creation failing",
            "severity": "P1", "reason": "P1 outage", "linked_ticket_id": "TKT-501"})),
        Decision(text="Escalation created."),
    ])
    r = c.post("/chat", json={"message": "escalate TKT-501", "role": "internal"}).json()
    assert r["status"] == "needs_confirmation"
    assert "P1" in r["preview"]
    tid = r["thread_id"]

    r2 = c.post("/confirm", json={"thread_id": tid, "approved": True}).json()
    assert r2["status"] == "done"
    committed = [e for e in r2["tool_log"] if e.get("confirmed")]
    assert committed and committed[0]["result"]["status"] == "created"


def test_write_action_not_committed_on_reject():
    c = _client([
        Decision(tool_call=ToolCall("create_escalation", {
            "account_id": "ACCT-001", "subject": "x", "severity": "P2",
            "reason": "y"})),
        Decision(text="Okay, cancelled."),
    ])
    r = c.post("/chat", json={"message": "maybe escalate", "role": "internal"}).json()
    tid = r["thread_id"]
    r2 = c.post("/confirm", json={"thread_id": tid, "approved": False}).json()
    assert all(not e.get("confirmed", False) for e in r2["tool_log"])


def test_confirm_unknown_thread_is_400():
    c = _client([Decision(text="x")])
    resp = c.post("/confirm", json={"thread_id": "does-not-exist", "approved": True})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /ops/alerts — proactive view + gating
# ---------------------------------------------------------------------------
def test_ops_internal_returns_breaches_and_clusters():
    c = _client([Decision(text="x")])
    ops = c.get("/ops/alerts?role=internal").json()
    breaches = {b["ticket_id"] for b in ops["sla_breaches"]}
    assert {"TKT-501", "TKT-505"} <= breaches
    high = {h["ticket_id"] for h in ops["high_severity"]}
    assert {"TKT-501", "TKT-505"} <= high
    bulk = [x for x in ops["clusters"] if x["theme"] == "Bulk upload failures"][0]
    assert "TKT-451" in bulk["historical_ticket_ids"]


def test_ops_customer_is_forbidden():
    c = _client([Decision(text="x")])
    assert c.get("/ops/alerts?role=customer").status_code == 403