"""High-level ErrandAgent orchestrator managing execution limits, memory, and LangGraph."""

import asyncio
from datetime import datetime, timezone
from typing import Any
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from mcp_server.provider_api import MockProviderAPI
from errand_agent.approval import ApprovalController, ApprovalDeclinedError, NoApprovalPendingError
from errand_agent.graph import build_errand_graph
from errand_agent.jev_guardrail import JEVGuardrail
from errand_agent.memory import MemoryManager
from errand_agent.models import ExecutionLimits, MemorySource, WorkflowState
from errand_agent.tracer import Tracer


class ErrandAgent:
    """Orchestrator for the home-service errand agent.

    Integrates:
    - LangGraph StateGraph with interrupt-before code approval gates
    - MockProviderAPI with reproducible failure modes
    - Code-enforced ApprovalController
    - Cross-session persistent MemoryManager
    - ExecutionLimits bounded execution guard
    - Structured Tracer
    """

    def __init__(
        self,
        api: MockProviderAPI | None = None,
        memory_manager: MemoryManager | None = None,
        tracer: Tracer | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        limits: ExecutionLimits | None = None,
        user_id: str = "user_default",
        thread_id: str = "session_default",
    ):
        self.api = api or MockProviderAPI()
        self.approval = ApprovalController()
        self.memory = memory_manager or MemoryManager()
        self.tracer = tracer or Tracer()
        self.checkpointer = checkpointer or MemorySaver()
        self.limits = limits or ExecutionLimits()
        self.user_id = user_id
        self.thread_id = thread_id
        self.guardrail = JEVGuardrail()

        # Compile the LangGraph
        self.graph = build_errand_graph(
            api=self.api,
            approval_controller=self.approval,
            memory_manager=self.memory,
            tracer=self.tracer,
            checkpointer=self.checkpointer,
        )

        self.config = {
            "configurable": {
                "thread_id": self.thread_id,
                "user_id": self.user_id,
            }
        }

    def reset_session(self) -> None:
        """Reset limits, approval records, and thread configuration for a fresh session."""
        import uuid
        self.limits.reset()
        self.approval.clear()
        self.thread_id = f"session_{uuid.uuid4().hex[:8]}"
        self.config = {
            "configurable": {
                "thread_id": self.thread_id,
                "user_id": self.user_id,
            }
        }
        self.tracer.record("session_reset", thread_id=self.thread_id)

    def _extract_last_assistant_message(self, state_values: dict[str, Any]) -> str:
        """Extract the most recent assistant message content from state values."""
        messages = state_values.get("messages", [])
        for m in reversed(messages):
            if hasattr(m, "content") and m.content:
                return m.content
            elif isinstance(m, dict) and m.get("content"):
                return m["content"]
        return "I am ready to help. What errand would you like to arrange?"

    async def step(self, user_input: str) -> str:
        """Execute one conversational step, checking execution limits and approval state."""
        # 0. JEV Safety Guardrail (Jailbreak and Prompt Injection Screening - evaluated first)
        guard_decision = self.guardrail.check_input(user_input)
        if guard_decision.blocked:
            self.tracer.record(
                "guardrail_blocked",
                input=user_input,
                reason=guard_decision.reason,
                source=guard_decision.source,
            )
            return (
                f"🛡️ Guardrail Alert: Your message was flagged by the JEV safety guardrail as a potential "
                f"system prompt injection or jailbreak attempt ({guard_decision.reason}). "
                f"This request has been blocked to ensure agent security."
            )

        # 1. Manual Session Reset Commands
        if user_input.strip().lower() in ("reset", "new session", "start over", "clear session"):
            self.reset_session()
            return "🔄 Session reset. How can I help you today?"

        # 2. Bounded Execution Guard (Must-Have 5)
        within_limits, reason = self.limits.check_limits()
        if not within_limits:
            self.tracer.record("limit_exhaustion", reason=reason)
            return (
                f"⚠️ Execution Limit Reached: {reason}.\n"
                f"To protect your session, no further unverified actions will be executed.\n"
                f"Type **'reset'** to start a fresh session, or tell me what service you would like to arrange."
            )

        self.limits.touch()
        self.tracer.record("user_input", content=user_input, thread_id=self.thread_id)
        self.limits.current_model_turns += 1

        # 2. Check if the graph is paused at an approval interrupt gate (Must-Have 2)
        snapshot = self.graph.get_state(self.config)

        if snapshot.next:
            # We are paused at an interrupt_before gate (execute_booking, execute_cancel, or execute_reschedule)
            try:
                approved, explain_msg = self.approval.process_user_confirmation(user_input)
                if approved:
                    self.tracer.record("approval_granted", user_input=user_input)
                    # User approved! Resume graph execution past the breakpoint
                    result = await self.graph.ainvoke(None, self.config)
                    final_snapshot = self.graph.get_state(self.config)

                    # If booking was confirmed, record technician preference if applicable
                    if final_snapshot.values.get("workflow_state") == WorkflowState.CONFIRMED.value:
                        selected_p = final_snapshot.values.get("selected_provider", {})
                        if selected_p:
                            p_id = selected_p.get("id")
                            service = selected_p.get("service")
                            if p_id and service:
                                self.memory.remember(
                                    self.user_id,
                                    f"preferred_{service}_technician",
                                    p_id,
                                    source=MemorySource.AGENT_INFERRED,
                                )

                    return self._extract_last_assistant_message(final_snapshot.values)
                else:
                    return explain_msg

            except ApprovalDeclinedError:
                self.tracer.record("approval_declined", user_input=user_input)
                self.graph.update_state(self.config, {
                    "workflow_state": WorkflowState.IDLE.value,
                    "approval": None,
                    "approval_confirmed": False,
                })
                return "Understood. The action has been cancelled and no changes were made. What else can I assist you with?"

        # 3. Standard graph invocation
        input_data = {
            "messages": [HumanMessage(content=user_input)],
            "user_id": self.user_id,
            "thread_id": self.thread_id,
        }

        # Check if user mentioned an area they live in and remember it
        lowered = user_input.lower()
        for loc in ["koramangala", "indiranagar", "hsr_layout", "whitefield", "jayanagar"]:
            if f"in {loc}" in lowered or f"at {loc}" in lowered:
                self.memory.remember(self.user_id, "preferred_area", loc, source=MemorySource.USER_STATED)

        result = await self.graph.ainvoke(input_data, self.config)
        final_snapshot = self.graph.get_state(self.config)
        return self._extract_last_assistant_message(final_snapshot.values)
