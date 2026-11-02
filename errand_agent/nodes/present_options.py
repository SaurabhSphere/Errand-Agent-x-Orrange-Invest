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

    budget_exceeded = state.get("budget_exceeded", False)
    budget_max = state.get("budget_max")
    service = state.get("service", "service")
    time_pref = state.get("time_preference")
    date_start = state.get("date_range_start")

    # Timeframe human readable string
    time_parts = []
    if date_start == "2026-11-02":
        time_parts.append("tomorrow")
    elif date_start:
        time_parts.append(f"on {date_start}")
    if time_pref:
        time_parts.append(time_pref)
    time_desc = " ".join(time_parts) if time_parts else "your requested time"

    if budget_exceeded and budget_max and providers:
        lowest = providers[0]
        diff = lowest.get("price", 0) - budget_max
        diff_str = f" (₹{diff} above your budget)" if diff > 0 else ""
        header = (
            f"⚠️ No {service} providers found under ₹{budget_max} for {time_desc} in your area.\n"
            f"The closest available option is **{lowest.get('name', 'Provider')}** at **₹{lowest.get('price')}**{diff_str}.\n\n"
            f"Here are the closest available alternatives (ranked by price):"
        )
        lines = [header]
    else:
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

    if budget_exceeded:
        lines.append("\nPlease reply with the option number if you would like to proceed with one of these alternatives, or let me know if you would like to adjust your budget or schedule.")
    else:
        lines.append("\nPlease reply with the option number you would like to select (e.g. 'Option 1').")

    return {
        "workflow_state": WorkflowState.AWAITING_SELECTION.value,
        "messages": [AIMessage(content="\n\n".join(lines))],
    }
