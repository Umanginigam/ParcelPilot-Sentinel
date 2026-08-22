"""Agent-graph tests (Step 7) — no API key required.

Uses StubLLM to script the model's tool calls, so we exercise the REAL graph:
routing, scoped tool execution, and the interrupt()/resume confirmation gate.
"""
import json

from src.agent import build_agent, new_state
from src import auth
from src.llm import StubLLM, Decision, ToolCall

CONFIG = {"configurable": {"thread_id": "t1"}}


def _run(agent, state, config=CONFIG):
    return agent.invoke(state, config=config)


def test_agent_calls_resolver_then_answers():
    """Scripted: call resolve_cancellation, then give a final answer that
    references the ruling. Confirms routing execute -> agent -> END."""
    llm = StubLLM(script=[
        Decision(tool_call=ToolCall("resolve_cancellation", {"order_id": "ORD-1001"})),
        Decision(text="No cancellation fee — the Northstar agreement governs."),
    ])
    agent = build_agent(llm)
    out = _run(agent, new_state("Can Northstar cancel ORD-1001?",
                                auth.internal()))
    assert out["answer"].startswith("No cancellation fee")
    assert out["tool_log"][0]["tool"] == "resolve_cancellation"
    assert out["tool_log"][0]["ok"] is True
    # the resolver result was fed back into the transcript
    assert any("resolve_cancellation" in m["content"] for m in out["messages"])


def test_access_denied_is_surfaced_not_raised():
    """A customer scoped to ACCT-002 asking about ACCT-001's order: the graph
    must capture AccessDenied as a tool error, not crash."""
    llm = StubLLM(script=[
        Decision(tool_call=ToolCall("lookup_order", {"order_id": "ORD-1001"})),
        Decision(text="I can only access your own account's orders."),
    ])
    agent = build_agent(llm)
    out = _run(agent, new_state("Show me ORD-1001", auth.customer("ACCT-002")),
               {"configurable": {"thread_id": "t-acl"}})
    assert out["tool_log"][0]["ok"] is False
    assert out["tool_log"][0]["result"]["error"] == "access_denied"


def test_write_action_pauses_for_confirmation_then_commits():
    """create_escalation must interrupt; resume(True) commits."""
    llm = StubLLM(script=[
        Decision(tool_call=ToolCall("create_escalation", {
            "account_id": "ACCT-001", "subject": "All shipment creation failing",
            "severity": "P1", "reason": "P1 outage", "linked_ticket_id": "TKT-501"})),
        Decision(text="Escalation created."),
    ])
    agent = build_agent(llm)
    cfg = {"configurable": {"thread_id": "t-commit"}}
    result = agent.invoke(new_state("Escalate TKT-501", auth.internal()), config=cfg)

    # graph is paused at the interrupt, not finished
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["type"] == "confirm_action"
    assert "P1" in payload["preview"]

    # user confirms -> resume
    from langgraph.types import Command
    final = agent.invoke(Command(resume=True), config=cfg)
    committed = [e for e in final["tool_log"] if e.get("confirmed")]
    assert committed and committed[0]["result"]["status"] == "created"


def test_write_action_can_be_rejected():
    """resume(False) must NOT commit."""
    llm = StubLLM(script=[
        Decision(tool_call=ToolCall("create_escalation", {
            "account_id": "ACCT-001", "subject": "x", "severity": "P2",
            "reason": "y"})),
        Decision(text="Okay, I won't escalate."),
    ])
    agent = build_agent(llm)
    cfg = {"configurable": {"thread_id": "t-reject"}}
    agent.invoke(new_state("maybe escalate", auth.internal()), config=cfg)

    from langgraph.types import Command
    final = agent.invoke(Command(resume=False), config=cfg)
    assert all(not e.get("confirmed", False) for e in final["tool_log"])
    assert any("cancelled" in str(e.get("result", "")).lower()
               for e in final["tool_log"])
def test_global_p1_escalation_uses_global_account():
    llm = StubLLM(script=[
        Decision(tool_call=ToolCall(
            "create_escalation",
            {
                "subject": "All shipment creation failing",
                "severity": "P1",
                "reason": "P1 production outage",
            }
        )),
        Decision(text="Escalation created."),
    ])

    agent = build_agent(llm)

    cfg = {
        "configurable": {
            "thread_id": "global-p1-test"
        }
    }

    result = agent.invoke(
        new_state(
            "All shipment creation is failing for every user.",
            auth.internal(),
        ),
        config=cfg,
    )

    assert "__interrupt__" in result

    payload = result["__interrupt__"][0].value

    assert payload["type"] == "confirm_action"
    assert payload["plan"]["account_id"] == "GLOBAL"
    assert payload["plan"]["severity"] == "P1"