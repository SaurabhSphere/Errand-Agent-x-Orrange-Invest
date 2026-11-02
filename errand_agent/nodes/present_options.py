"""Present options node for formatting search results."""

from typing import Any
from langchain_core.messages import AIMessage
from errand_agent.models import WorkflowState
from errand_agent.state import ErrandState


def present_options_node(state: ErrandState) -> dict[str, Any]:
    """Format matching providers and their free slots into a clear list."""
    providers = state.get("providers", [])

    if not providers:
        msg = (
            "I couldn't find any available providers matching your exact criteria. "
            "Would you like to expand the budget or check neighboring areas?"
        )
        return {
            "workflow_state": WorkflowState.IDLE.value,
            "messages": [AIMessage(content=msg)],
        }

    lines = [f"I found {len(providers)} matching provider(s):"]
    for idx, p in enumerate(providers[:4], 1):
        name = p.get("name", p["id"])
        price = p.get("price", "N/A")
        rating = p.get("rating", "N/A")
        slots = p.get("free_slots", [])
        slots_str = ", ".join(slots[:2]) if slots else "Contact for slots"
        badge = p.get("attributes", {}).get("badge", "")
        badge_str = f" [{badge}]" if badge else ""

        lines.append(
            f"Option {idx}: **{name}**{badge_str} — ₹{price} (Rating: {rating}★)\n"
            f"   Available slots: {slots_str}"
        )

    lines.append("\nPlease reply with the option number you would like to select (e.g. 'Option 1').")

    return {
        "workflow_state": WorkflowState.AWAITING_SELECTION.value,
        "messages": [AIMessage(content="\n\n".join(lines))],
    }
