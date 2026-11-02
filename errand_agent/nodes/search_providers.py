"""Search providers node for Errand Agent."""

from typing import Any
from langchain_core.messages import AIMessage
from mcp_server.provider_api import MockProviderAPI
from errand_agent.models import WorkflowState
from errand_agent.sanitizer import Sanitizer
from errand_agent.state import ErrandState
from errand_agent.tracer import Tracer


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

    # Filter by budget if specified
    filtered = results
    if budget_max:
        under_budget = [p for p in filtered if p["price"] <= budget_max]
        if under_budget:
            filtered = under_budget

    # Filter / rank by preferred provider
    if preferred_id:
        filtered.sort(key=lambda p: (0 if p["id"] == preferred_id else 1, -p["rating"]))
    else:
        filtered.sort(key=lambda p: (-p["rating"], p["price"]))

    # Filter slots by time preference if specified
    for p in filtered:
        slots = p.get("free_slots", [])
        if time_pref == "morning":
            # 8:00 to 12:00
            m_slots = [s for s in slots if "T08" in s or "T09" in s or "T10" in s or "T11" in s]
            if m_slots:
                p["free_slots"] = m_slots
        elif time_pref and "after_10am" in time_pref:
            # Not before 10 AM
            late_slots = [s for s in slots if "T08" not in s and "T09" not in s]
            if late_slots:
                p["free_slots"] = late_slots

    return {
        "providers": filtered,
        "tool_call_count": tool_count,
        "workflow_state": WorkflowState.PRESENTING_OPTIONS.value,
    }
