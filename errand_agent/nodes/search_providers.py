"""Search providers node for Errand Agent."""

from typing import Any
from langchain_core.messages import AIMessage
from mcp_server.provider_api import MockProviderAPI
from errand_agent.models import WorkflowState
from errand_agent.sanitizer import Sanitizer
from errand_agent.state import ErrandState
from errand_agent.tracer import Tracer


def is_slot_in_window(
    slot: str,
    date_start: str | None,
    date_end: str | None,
    time_pref: str | None,
) -> bool:
    """Check if a slot timestamp string satisfies date range and time preference."""
    # 1. Date match
    slot_date = slot[:10]
    if date_start and slot_date < date_start:
        return False
    if date_end and slot_date > date_end:
        return False

    # 2. Time-of-day match
    try:
        hour = int(slot[11:13])
    except (ValueError, IndexError):
        return True

    if time_pref == "morning" and not (8 <= hour < 12):
        return False
    elif time_pref == "afternoon" and not (12 <= hour < 17):
        return False
    elif time_pref == "evening" and not (17 <= hour < 22):
        return False
    elif time_pref and "after_10am" in time_pref and hour < 10:
        return False

    return True


def search_providers_node(
    state: ErrandState,
    api: MockProviderAPI,
    tracer: Tracer | None = None,
) -> dict[str, Any]:
    """Execute search_providers tool and filter by budget / time preference."""
    service = state.get("service", "plumbing")
    area = state.get("area", "koramangala")
    date_start = state.get("date_range_start")
    date_end = state.get("date_range_end")
    budget_max = state.get("budget_max")
    time_pref = state.get("time_preference")
    preferred_id = state.get("preferred_provider_id")

    tool_count = state.get("tool_call_count", 0) + 1
    date_range = (date_start, date_end) if date_start else None

    # Call provider API
    results = api.search_providers(service, area, date_range)

    if tracer:
        tracer.record_tool_call(
            tool="search_providers",
            args={"service": service, "area": area, "date_range": date_range},
            result=[{"id": p["id"], "price": p["price"], "rating": p["rating"]} for p in results],
        )

    # 1. Filter slots by exact date range and time preference
    if date_start or date_end or time_pref:
        for p in results:
            slots = p.get("free_slots", [])
            valid_slots = [s for s in slots if is_slot_in_window(s, date_start, date_end, time_pref)]
            p["free_slots"] = valid_slots

    # 2. Filter by budget if specified
    budget_exceeded = False
    closest_budget_provider = None

    if budget_max:
        exact_budget = [p for p in results if p.get("price", 99999) <= budget_max]
        if exact_budget:
            filtered = exact_budget
            budget_exceeded = False
        else:
            # No provider meets budget! Sort by price ASCENDING so lowest alternative is first
            budget_exceeded = True
            results.sort(key=lambda p: (p.get("price", 99999), -p.get("rating", 0)))
            filtered = results
            closest_budget_provider = results[0] if results else None
    else:
        filtered = results
        budget_exceeded = False

    # 3. Sort / Rank
    if budget_exceeded:
        # Keep price ascending order so the closest option to the user's budget is Option 1
        filtered.sort(key=lambda p: (p.get("price", 99999), -p.get("rating", 0)))
    elif preferred_id:
        filtered.sort(key=lambda p: (0 if p["id"] == preferred_id else 1, -p.get("rating", 0), p.get("price", 99999)))
    elif date_start or date_end or time_pref:
        # Prioritize providers who have at least one free slot in the requested window
        filtered.sort(key=lambda p: (0 if p.get("free_slots") else 1, -p.get("rating", 0), p.get("price", 99999)))
    else:
        filtered.sort(key=lambda p: (-p.get("rating", 0), p.get("price", 99999)))

    return {
        "providers": filtered,
        "budget_exceeded": budget_exceeded,
        "closest_budget_provider": closest_budget_provider,
        "tool_call_count": tool_count,
        "workflow_state": WorkflowState.PRESENTING_OPTIONS.value,
    }
