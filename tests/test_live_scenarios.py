from dotenv import load_dotenv

load_dotenv()

from src.agent import build_agent, new_state
from src.auth import internal
from src.llm import GroqLLM


def run(question: str, thread_id: str):

    print("\n" + "=" * 70)
    print("QUESTION")
    print("=" * 70)
    print(question)

    agent = build_agent(GroqLLM())

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    result = agent.invoke(
        new_state(question, internal()),
        config=config,
    )

    print("\n" + "=" * 70)
    print("ANSWER")
    print("=" * 70)

    print(result.get("answer"))

    print("\n" + "=" * 70)
    print("TOOL TRACE")
    print("=" * 70)

    for item in result.get("tool_log", []):

        print("\nTool:", item["tool"])
        print("Success:", item.get("ok"))

        # ----------------------------------------------------------
        # Tool latency
        # ----------------------------------------------------------

        print(
            "Duration:",
            item.get("duration_ms", "N/A"),
            "ms"
        )

        result_data = item.get("result", {})

        print("Result:", result_data)


# ------------------------------------------------------------------
# Scenario 1 — Northstar cancellation
# ------------------------------------------------------------------

run(
    "Can Northstar cancel ORD-1001 without a cancellation fee? Explain why.",
    "live-northstar",
)


# ------------------------------------------------------------------
# Scenario 2 — LumenWorks service credit
# ------------------------------------------------------------------

run(
    "Should ORD-2002 receive a service credit? Explain why.",
    "live-lumenworks",
)


# ------------------------------------------------------------------
# Scenario 3 — Standard account cancellation
# ------------------------------------------------------------------

run(
    "Can ORD-3001 be cancelled without a fee?",
    "live-standard",
)