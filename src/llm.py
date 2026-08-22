"""
Swappable LLM layer.

The agent depends only on the LLM protocol.

GroqLLM:
    Real Groq API with local function/tool calling.

StubLLM:
    Deterministic offline implementation used by tests.

Architecture:

    User
      ↓
    Groq
      ↓
    Tool call
      ↓
    Local ParcelPilot tool
      ↓
    Tool result
      ↓
    Groq
      ↓
    Final answer

The LLM never directly accesses SQLite, PDFs, or escalation state.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# NORMALIZED LLM TYPES
# ============================================================================
class LLMServiceError(Exception):
    """Safe, structured error exposed by the LLM layer."""

    def __init__(
        self,
        code: str,
        message: str,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def as_dict(self) -> dict:
        return {
            "error": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    call_id: Optional[str] = None


@dataclass
class Decision:
    tool_call: Optional[ToolCall] = None
    text: Optional[str] = None

    @property
    def is_final(self) -> bool:
        return self.tool_call is None


class LLM(Protocol):

    def decide(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> Decision:
        ...


# ============================================================================
# GROQ
# ============================================================================

class GroqLLM:
    """
    Groq adapter using local function/tool calling.

    Groq decides WHICH tool should be called.

    Our application executes the tool.

    This keeps business logic outside the model.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):

        from groq import Groq

        key = (
            api_key
            or os.environ.get("GROQ_API_KEY")
        )

        if not key:
            raise RuntimeError(
                "GROQ_API_KEY is not set."
            )

        self._client = Groq(
            api_key=key,
            timeout=20.0,
            max_retries=1,
        )

        self._model = (
            model
            or os.environ.get(
                "GROQ_MODEL",
                "openai/gpt-oss-120b",
            )
        )

    # ------------------------------------------------------------------------
    # Convert our internal messages into Groq messages
    # ------------------------------------------------------------------------

    def _convert_messages(
        self,
        system: str,
        messages: list[dict],
    ) -> list[dict]:

        groq_messages = [
            {
                "role": "system",
                "content": system,
            }
        ]

        for message in messages:

            role = message.get("role")

            # ------------------------------------------------------------
            # Normal user message
            # ------------------------------------------------------------

            if role == "user":

                groq_messages.append(
                    {
                        "role": "user",
                        "content": message.get(
                            "content",
                            "",
                        ),
                    }
                )

            # ------------------------------------------------------------
            # Assistant message
            #
            # Our graph stores tool calls as text:
            #
            # [tool_call] resolve_cancellation(...)
            #
            # This is mainly useful for trace/debugging.
            # ------------------------------------------------------------

            elif role == "assistant":

                groq_messages.append(
                    {
                        "role": "assistant",
                        "content": message.get(
                            "content",
                            "",
                        ),
                    }
                )

            # ------------------------------------------------------------
            # Tool result
            # ------------------------------------------------------------

            elif role == "tool":
                groq_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.get(
                            "tool_call_id",
                            "local-tool-call",
                        ),
                        "name": message.get(
                            "name",
                            "unknown_tool",
                            ),
            "content": message.get(
                "content",
                "",
            ),
        }
    )

            else:

                # Defensive fallback.
                groq_messages.append(
                    {
                        "role": "user",
                        "content": str(
                            message.get(
                                "content",
                                "",
                            )
                        ),
                    }
                )

        return groq_messages

    # ------------------------------------------------------------------------
    # Convert our tool schema to Groq format
    # ------------------------------------------------------------------------

    def _convert_tools(
        self,
        tools: list[dict],
    ) -> list[dict]:

        groq_tools = []

        for tool in tools:

            groq_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["parameters"],
                    },
                }
            )

        return groq_tools

    # ------------------------------------------------------------------------
    # Main decision function
    # ------------------------------------------------------------------------

    def decide(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> Decision:

        groq_messages = self._convert_messages(
            system,
            messages,
        )

        groq_tools = self._convert_tools(
            tools
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=groq_messages,
                tools=self._convert_tools(tools),
                tool_choice="auto",
                temperature=0,
            )

        except Exception as exc:
            # Import SDK errors lazily so StubLLM remains dependency-light.
            from groq import (
                APITimeoutError,
                APIConnectionError,
                RateLimitError,
                AuthenticationError,
                BadRequestError,
            )

            if isinstance(exc, APITimeoutError):
                raise LLMServiceError(
                    code="llm_timeout",
                    message="The AI service timed out. Please try again.",
                    retryable=True,
                ) from exc

            if isinstance(exc, RateLimitError):
                raise LLMServiceError(
            code="llm_rate_limited",
            message="The AI service is temporarily rate-limited. Please try again shortly.",
            retryable=True,
        ) from exc

            if isinstance(exc, APIConnectionError):
                raise LLMServiceError(
                    code="llm_connection_error",
            message="The AI service could not be reached.",
            retryable=True,
        ) from exc

            if isinstance(exc, AuthenticationError):
                raise LLMServiceError(
            code="llm_authentication_error",
            message="The AI service is not configured correctly.",
            retryable=False,
        ) from exc

            if isinstance(exc, BadRequestError):
                raise LLMServiceError(
            code="llm_bad_request",
            message="The AI request could not be processed.",
            retryable=False,
        ) from exc

            raise LLMServiceError(
        code="llm_error",
        message="The AI service encountered an unexpected error.",
        retryable=False,
    ) from exc

        if not response.choices:

            return Decision(
                text=(
                    "I couldn't get a response from "
                    "the AI model."
                )
            )

        message = response.choices[0].message

        # ----------------------------------------------------------------
        # TOOL CALL
        # ----------------------------------------------------------------

        if message.tool_calls:

            # We currently support one tool decision
            # per agent iteration.
            call = message.tool_calls[0]

            arguments = (
                call.function.arguments
                or "{}"
            )

            try:

                parsed_args = json.loads(
                    arguments
                )

            except json.JSONDecodeError:

                return Decision(
                    text=(
                        "The model returned invalid "
                        "tool arguments."
                    )
                )

            return Decision(
                tool_call=ToolCall(
                    name=call.function.name,
                    args=parsed_args,
                    call_id=call.id,
                )
            )

        # ----------------------------------------------------------------
        # FINAL ANSWER
        # ----------------------------------------------------------------

        return Decision(
            text=message.content or ""
        )


# ============================================================================
# STUB LLM
# ============================================================================

@dataclass
class StubLLM:
    """
    Deterministic fake model.

    Used by tests so the entire LangGraph system can be tested without:

        - API key
        - internet
        - model variability
        - API cost
    """

    script: list[Decision] = field(
        default_factory=list
    )

    _i: int = 0

    def decide(
        self,
        system,
        messages,
        tools,
    ) -> Decision:

        if self._i >= len(self.script):

            return Decision(
                text=(
                    "(stub: no more "
                    "scripted decisions)"
                )
            )

        decision = self.script[self._i]

        self._i += 1

        return decision


# ============================================================================
# DEFAULT LLM
# ============================================================================

def default_llm() -> LLM:

    if os.environ.get("GROQ_API_KEY"):

        return GroqLLM()

    return StubLLM(
        script=[
            Decision(
                text=(
                    "(no GROQ_API_KEY set)"
                )
            )
        ]
    )