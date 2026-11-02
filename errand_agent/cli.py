"""Interactive Command-Line Interface for Errand Agent."""

import asyncio
import sys
from mcp_server.provider_api import MockProviderAPI
from errand_agent.agent import ErrandAgent
from errand_agent.memory import MemoryManager
from errand_agent.tracer import Tracer


BANNER = """
======================================================================
🏠 Orange Invest — Founding AI Engineer : Errand Agent
======================================================================
Autonomous home-service assistant with code-enforced approval gates,
bounded execution limits, and strict untrusted content sanitization.

Quick Commands:
  • "my bookings"        - View active & past bookings
  • "my memory"          - View persistent preferences
  • "forget <key>"       - Erase a stored preference permanently
  • "status"             - View current session info & trace location
  • "quit" or "exit"     - Exit the session
======================================================================
"""


async def main() -> None:
    print(BANNER)

    tracer = Tracer()
    api = MockProviderAPI()
    memory = MemoryManager()
    agent = ErrandAgent(api=api, memory_manager=memory, tracer=tracer)

    print(f"📊 Active Trace File: {tracer.trace_file}\n")
    print("Agent: Hello! I can book, reschedule, or cancel home services for you. How can I help today?\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting. Good day!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("\nThank you for using Errand Agent. Goodbye!")
            break

        if user_input.lower() == "status":
            print(f"\n[Status] Current Turn: {agent.limits.current_model_turns}/{agent.limits.max_model_turns}")
            print(f"[Status] Trace Log: {tracer.trace_file}\n")
            continue

        try:
            response = await agent.step(user_input)
            print(f"\nAgent: {response}\n")
        except Exception as e:
            print(f"\n❌ Error encountered: {e}\n")


if __name__ == "__main__":
    asyncio.run(main())
