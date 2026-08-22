"""
LangGraph agent with human-in-the-loop confirmation.

Important security properties:

1. AuthContext comes from the application, not the LLM.
2. Read tools enforce account scope in tools.py.
3. State-changing tools are marked write=True.
4. write=True tools NEVER execute directly from the agent node.
5. interrupt() pauses the graph before the write.
6. commit_escalation() runs only after explicit confirmation.
7. MemorySaver allows the graph to resume after confirmation.
"""

from __future__ import annotations

import json
from typing import Optional, TypedDict
import time

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .agent_tools import BY_NAME, schemas
from .auth import AccessDenied, AuthContext
from .llm import LLM, Decision, LLMServiceError


# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

MAX_STEPS = 6


SYSTEM = """
You are ParcelPilot's support agent.

You answer questions using ONLY the supplied ParcelPilot data.

Rules:

1. Use tools to retrieve facts. Never invent customer, order, ticket,
   policy, agreement, SLA, or service-credit information.

2. Prefer resolve_cancellation for cancellation questions.

3. Prefer resolve_service_credit for service-credit questions.

4. Prefer resolve_sla for SLA questions.

5. Use doc_search when supporting policy, SOP, product documentation,
   or customer-agreement evidence is needed.

6. Customer-specific agreements override applicable global policies.

7. Deprecated policies and historical ticket resolutions are context only.
   They may be wrong and must never override authoritative current sources.

8. If sources conflict or information is insufficient, explain the
   uncertainty and escalate rather than guessing.

9. Use the dataset snapshot time for time-based reasoning.

10. State-changing actions require explicit user confirmation.

11. Never claim that an escalation was created until the create_escalation
    tool has actually executed.

12. When an escalation or other action is warranted, CALL the create_escalation
   tool directly. Do NOT ask the user for permission in text first — the system
   enforces an explicit confirmation step before any action runs, and it will
   show the user a preview to approve or reject. Asking in prose skips that gate
   and leaves the action uncreated.

13. For a global outage affecting every user, do not ask the user for an
   account_id. Use "GLOBAL" as the account_id when calling create_escalation.
   The authenticated application context already determines the caller's
   authorization. The confirmation gate will ask for approval before writing.

14. When you have enough information to answer, respond concisely and
   explain which authoritative source governed the decision.
"""


# ---------------------------------------------------------------------------
# GRAPH STATE
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    """
    State persisted by LangGraph.

    messages:
        Conversation/tool transcript.

    ctx:
        Serialized AuthContext.

    steps:
        Number of tool/action steps performed.

    tool_log:
        Structured trace for the frontend.

    answer:
        Final assistant response.

    pending_write:
        State-changing action waiting for confirmation.

    _last_call:
        Most recent tool call emitted by the model.
    """

    messages: list[dict]
    ctx: dict
    steps: int
    tool_log: list[dict]
    answer: Optional[str]
    pending_write: Optional[dict]
    _last_call: Optional[dict]


# ---------------------------------------------------------------------------
# AUTH CONTEXT
# ---------------------------------------------------------------------------

def _ctx(state: AgentState) -> AuthContext:
    """
    Reconstruct the trusted AuthContext from graph state.

    The model never controls this information.
    """

    return AuthContext(**state["ctx"])


# ---------------------------------------------------------------------------
# AGENT NODE
# ---------------------------------------------------------------------------

def _build_agent_node(llm: LLM):

    def agent_node(state: AgentState) -> dict:
        try:
            decision: Decision = llm.decide(
                SYSTEM,
                state["messages"],
                schemas()
            )

        except LLMServiceError as exc:
            error = exc.as_dict()
            message = (
                "I'm temporarily unable to reach the AI service. "
                "Please try again or contact ParcelPilot support."
            )
            return {
                "answer": message,
                "messages": state["messages"] + [
                    {
                        "role": "assistant",
                        "content": message,
                }
            ],
            "tool_log": state.get("tool_log", []) + [
                {
                    "tool": "llm",
                    "ok": False,
                    "result": error,
                }
            ],
        }

        # ---------------------------------------------------------------
        # FINAL ANSWER
        # ---------------------------------------------------------------

        if decision.is_final:

            text = decision.text or ""

            return {
                "answer": text,
                "messages": state["messages"]
                + [
                    {
                        "role": "assistant",
                        "content": text,
                    }
                ],
            }

        # ---------------------------------------------------------------
        # TOOL CALL
        # ---------------------------------------------------------------

        call = decision.tool_call
        if (call.name == "create_escalation" and call.args.get("severity") == "P1"
            and "every user" in state["messages"][0]["content"].lower()
            ):
            call.args.setdefault("account_id", "GLOBAL")

        if call is None:

            text = (
                "I couldn't determine the appropriate next step "
                "from the available information."
            )

            return {
                "answer": text,
                "messages": state["messages"]
                + [
                    {
                        "role": "assistant",
                        "content": text,
                    }
                ],
            }

        # ---------------------------------------------------------------
        # SAFETY: UNKNOWN TOOL
        # ---------------------------------------------------------------

        tool = BY_NAME.get(call.name)

        if tool is None:

            text = (
                f"I attempted to use an unsupported tool "
                f"({call.name}). Please try the request again."
            )

            return {
                "answer": text,
                "messages": state["messages"]
                + [
                    {
                        "role": "assistant",
                        "content": text,
                    }
                ],
            }

        # ---------------------------------------------------------------
        # Record the model's tool call
        # ---------------------------------------------------------------

        tool_call_message = {
            "role": "assistant",
            "content": (
                f"[tool_call] {call.name}"
                f"({json.dumps(call.args)})"
            ),
        }

        pending_write = None

        if tool.write:

            pending_write = {
                "name": call.name,
                "args": call.args,
            }

        return {
            "messages": state["messages"]
            + [tool_call_message],

            "pending_write": pending_write,

            "_last_call": {
                "name": call.name,
                "args": call.args,
                "call_id": call.call_id,
            },
        }

    return agent_node


# ---------------------------------------------------------------------------
# ROUTING
# ---------------------------------------------------------------------------

def _route_after_agent(state: AgentState) -> str:

    # Final answer
    if state.get("answer") is not None:
        return END

    # Safety limit
    if state.get("steps", 0) >= MAX_STEPS:
        return "give_up"

    # State-changing action
    if state.get("pending_write"):
        return "confirm"

    # Normal read/resolve tool
    return "execute"


# ---------------------------------------------------------------------------
# READ / RESOLUTION TOOL EXECUTION
# ---------------------------------------------------------------------------

def _build_execute_node():

    def execute_node(state: AgentState) -> dict:

        call = state["_last_call"]
        tool = BY_NAME[call["name"]]

        # ---------------------------------------------------------------
        # Start latency measurement
        # ---------------------------------------------------------------

        started = time.perf_counter()

        try:

            result = tool.handler(
                _ctx(state),
                **call["args"]
            )

            ok = True

        except AccessDenied as exc:

            result = {
                "error": "access_denied",
                "detail": str(exc),
            }

            ok = False

        except Exception as exc:

            # Surface errors to the model instead of crashing the graph.
            result = {
                "error": type(exc).__name__,
                "detail": str(exc),
            }

            ok = False

        # ---------------------------------------------------------------
        # Finish latency measurement
        # ---------------------------------------------------------------

        duration_ms = round(
            (time.perf_counter() - started) * 1000,
            2,
        )

        # ---------------------------------------------------------------
        # Tool trace
        # ---------------------------------------------------------------

        entry = {
            "tool": call["name"],
            "args": call["args"],
            "ok": ok,
            "duration_ms": duration_ms,
            "result": result,
        }

        return {
            "steps": state.get("steps", 0) + 1,

            "tool_log": (
                state.get("tool_log", [])
                + [entry]
            ),

            "messages": (
                state["messages"]
                + [
                    {
                        "role": "user",
                        "content": (
                            f"[tool_result:{call['name']}] "
                            f"{json.dumps(result)[:1500]}"
                        ),
                    }
                ]
            ),
        }

    return execute_node


# ---------------------------------------------------------------------------
# CONFIRMATION NODE
# ---------------------------------------------------------------------------

def _build_confirm_node():

    def confirm_node(state: AgentState) -> dict:

        call = state.get("pending_write")

        if call is None:

            return {
                "answer": "There is no pending action."
            }

        ctx = _ctx(state)

        tool = BY_NAME.get(call["name"])

        if tool is None:

            return {
                "answer": (
                    f"Unsupported action: {call['name']}"
                )
            }

        # ---------------------------------------------------------------
        # Currently the only write action is create_escalation.
        #
        # Build a no-write preview first.
        # ---------------------------------------------------------------

        from .tools import (
            EscalationPlan,
            prepare_escalation,
        )

        args = call["args"]

        plan = EscalationPlan(
            account_id=args["account_id"],
            subject=args["subject"],
            severity=args["severity"],
            reason=args["reason"],
            linked_ticket_id=args.get(
                "linked_ticket_id"
            ),
            linked_order_id=args.get(
                "linked_order_id"
            ),
        )

        # IMPORTANT:
        #
        # prepare_escalation() performs validation but DOES NOT WRITE.
        #

        preview = prepare_escalation(
            ctx,
            plan,
        )

        # ---------------------------------------------------------------
        # HARD CONFIRMATION GATE
        #
        # The graph stops here.
        #
        # Nothing below this line executes until the caller resumes
        # the same graph thread.
        # ---------------------------------------------------------------

        approved = interrupt(
            {
                "type": "confirm_action",
                "tool": call["name"],
                "preview": preview["preview"],
                "plan": preview["plan"],
            }
        )

        # ---------------------------------------------------------------
        # USER REJECTED
        # ---------------------------------------------------------------

        if not approved:

            message = (
                "Action cancelled by user. "
                "No escalation was created."
            )

            entry = {
                "tool": call["name"],
                "confirmed": False,
                "result": message,
            }

            return {
                "pending_write": None,

                "steps": state.get("steps", 0) + 1,

                "tool_log": (
                    state.get("tool_log", [])
                    + [entry]
                ),

                "messages": (
                    state["messages"]
                    + [
                        {
                            "role": "tool",
                            "name": call["name"],
                            "content": message,
                        }
                    ]
                ),
            }

        # ---------------------------------------------------------------
        # USER CONFIRMED
        # ---------------------------------------------------------------

        # Start measuring the actual state-changing action.
        started = time.perf_counter()

        try:

            result = tool.handler(
                ctx,
                **args,
            )

            ok = True

        except AccessDenied as exc:

            result = {
                "error": "access_denied",
                "detail": str(exc),
            }

            ok = False

        except Exception as exc:

            result = {
                "error": type(exc).__name__,
                "detail": str(exc),
            }

            ok = False

        duration_ms = round(
            (time.perf_counter() - started) * 1000,
            2,
        )

        entry = {
            "tool": call["name"],
            "confirmed": True,
            "ok": ok,
            "duration_ms": duration_ms,
            "result": result,
        }

        return {
            "pending_write": None,

            "steps": state.get("steps", 0) + 1,

            "tool_log": (
                state.get("tool_log", [])
                + [entry]
            ),

            "messages": (
                state["messages"]
                + [
                    {
                        "role": "tool",
                        "name": call["name"],
                        "content": json.dumps(result)[:1500],
                    }
                ]
            ),
        }

    return confirm_node


# ---------------------------------------------------------------------------
# SAFETY FALLBACK
# ---------------------------------------------------------------------------

def _give_up_node(state: AgentState) -> dict:

    text = (
        "I couldn't resolve this confidently within the available "
        "evidence and step budget. This should be reviewed by a "
        "ParcelPilot support specialist."
    )

    return {
        "answer": text,

        "messages": (
            state["messages"]
            + [
                {
                    "role": "assistant",
                    "content": text,
                }
            ]
        ),
    }


# ---------------------------------------------------------------------------
# BUILD GRAPH
# ---------------------------------------------------------------------------

def build_agent(llm: LLM):

    graph = StateGraph(AgentState)

    graph.add_node(
        "agent",
        _build_agent_node(llm),
    )

    graph.add_node(
        "execute",
        _build_execute_node(),
    )

    graph.add_node(
        "confirm",
        _build_confirm_node(),
    )

    graph.add_node(
        "give_up",
        _give_up_node,
    )

    # ---------------------------------------------------------------
    # START
    # ---------------------------------------------------------------

    graph.add_edge(
        START,
        "agent",
    )

    # ---------------------------------------------------------------
    # Agent routing
    # ---------------------------------------------------------------

    graph.add_conditional_edges(
        "agent",
        _route_after_agent,
        {
            "execute": "execute",
            "confirm": "confirm",
            "give_up": "give_up",
            END: END,
        },
    )

    # ---------------------------------------------------------------
    # Tool → Agent
    # ---------------------------------------------------------------

    graph.add_edge(
        "execute",
        "agent",
    )

    # ---------------------------------------------------------------
    # Confirmation → Agent
    # ---------------------------------------------------------------

    graph.add_edge(
        "confirm",
        "agent",
    )

    # ---------------------------------------------------------------
    # Give-up → END
    # ---------------------------------------------------------------

    graph.add_edge(
        "give_up",
        END,
    )

    # ---------------------------------------------------------------
    # Checkpointer
    #
    # Required because interrupt/resume happens across requests.
    # ---------------------------------------------------------------

    return graph.compile(
        checkpointer=MemorySaver()
    )


# ---------------------------------------------------------------------------
# INITIAL STATE
# ---------------------------------------------------------------------------

def new_state(
    question: str,
    ctx: AuthContext,
) -> AgentState:

    return {
        "messages": [
            {
                "role": "user",
                "content": question,
            }
        ],

        "ctx": {
            "role": ctx.role,
            "account_id": ctx.account_id,
        },

        "steps": 0,

        "tool_log": [],

        "answer": None,

        "pending_write": None,

        "_last_call": None,
    }