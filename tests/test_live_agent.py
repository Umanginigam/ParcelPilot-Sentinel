from dotenv import load_dotenv

load_dotenv()

from src.agent import build_agent, new_state
from src.auth import internal
from src.llm import GroqLLM
from src import auth

llm = GroqLLM()

agent = build_agent(llm)

state = new_state(
    "Show me the details of ORD-1001.",
    auth.customer("ACCT-002"),
)

config = {
    "configurable": {
        "thread_id": "live-test-1"
    }
}

result = agent.invoke(
    state,
    config=config,
)

print("\n================ ANSWER ================\n")
print(result.get("answer"))

print("\n================ TOOL TRACE ================\n")

for item in result.get("tool_log", []):
    print(
        f"\nTool: {item['tool']}"
    )

    print(
        f"Success: {item.get('ok', item.get('confirmed'))}"
    )

    print(
        "Result:",
        item.get("result")
    )