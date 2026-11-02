"""Information gathering node. Asks only for missing errand details."""

from typing import Any
from langchain_core.messages import AIMessage
from errand_agent.memory import MemoryManager
from errand_agent.models import WorkflowState
from errand_agent.state import ErrandState


def gather_info(state: ErrandState, memory_manager: MemoryManager | None = None) -> dict[str, Any]:
    """Inspects required slots and asks ONLY for what is currently missing.

    Never re-asks for known facts. Consults memory for stated or inferred preferences.
    """
    user_id = state.get("user_id", "user_default")
    updates: dict[str, Any] = {}

    service = state.get("service")
    area = state.get("area")
    budget_max = state.get("budget_max")
    time_preference = state.get("time_preference")

    # If memory manager provided, check if area can be populated from memory
    if not area and memory_manager:
        fact = memory_manager.recall(user_id, "preferred_area")
        if fact:
            if fact.source.value == "user_stated":
                # Stated preference can be used directly
                area = fact.value
                updates["area"] = area
                updates.setdefault("slot_sources", {})["area"] = "memory_user_stated"

    # Identify missing mandatory fields for provider search
    missing_fields = []
    if not service:
        missing_fields.append("the service you need (e.g. plumbing, electrician, AC servicing, cleaning)")
    if not area:
        missing_fields.append("your area/locality (e.g. Koramangala, Indiranagar)")

    if missing_fields:
        prev_wstate = state.get("workflow_state")
        if not service and prev_wstate == WorkflowState.GATHERING_INFO.value:
            prompt = (
                "I couldn't match your response to our available trades. "
                "Our platform currently supports: **plumbing**, **electrician**, **AC servicing**, and **cleaning**.\n\n"
                "Please let me know which of these 4 services you need help with."
            )
        else:
            prompt = (
                "To find the best provider for you, could you please provide "
                + " and ".join(missing_fields)
                + "?"
            )
        return {
            **updates,
            "workflow_state": WorkflowState.GATHERING_INFO.value,
            "messages": [AIMessage(content=prompt)],
        }

    # All necessary information is gathered, transition to searching
    updates["workflow_state"] = WorkflowState.SEARCHING.value
    return updates
