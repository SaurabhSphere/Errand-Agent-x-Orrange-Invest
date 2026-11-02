"""Hold slot node for reserving a temporary provider slot."""

from typing import Any
from langchain_core.messages import AIMessage
from mcp_server.provider_api import MockProviderAPI, SlotUnavailableError
from errand_agent.models import WorkflowState
from errand_agent.state import ErrandState
from errand_agent.tracer import Tracer


def hold_slot_node(
    state: ErrandState,
    api: MockProviderAPI,
    tracer: Tracer | None = None,
) -> dict[str, Any]:
    """Place a temporary 10-minute hold on the selected slot."""
    provider = state.get("selected_provider")
    if not provider:
        providers = state.get("providers", [])
        if providers:
            provider = providers[0]
        else:
            return {
                "workflow_state": WorkflowState.ERROR.value,
                "error": "No provider selected for holding",
                "messages": [AIMessage(content="No provider was selected. Please choose a provider first.")],
            }

    provider_id = provider["id"]
    slot = state.get("selected_slot")
    if not slot:
        free_slots = provider.get("free_slots", [])
        slot = free_slots[0] if free_slots else "2026-11-02T10:00"

    tool_count = state.get("tool_call_count", 0) + 1

    try:
        hold_result = api.hold_slot(provider_id, slot)
    except SlotUnavailableError as e:
        if tracer:
            tracer.record_tool_call("hold_slot", {"provider_id": provider_id, "slot": slot}, str(e))
        return {
            "tool_call_count": tool_count,
            "workflow_state": WorkflowState.PRESENTING_OPTIONS.value,
            "error": "slot_unavailable",
            "messages": [AIMessage(content=f"Sorry, slot {slot} is no longer available. Please select another slot or provider.")],
        }

    hold_id = hold_result["hold_id"]
    quoted_price = hold_result["quoted_price"]
    expires_at = hold_result["expires_at"]

    if tracer:
        tracer.record_tool_call(
            tool="hold_slot",
            args={"provider_id": provider_id, "slot": slot},
            result=hold_result,
        )

    # Check for price drift between search price and quoted price
    search_price = provider.get("price", quoted_price)
    price_drift_note = None
    if quoted_price != search_price:
        price_drift_note = (
            f"⚠️ Notice: The quoted price is ₹{quoted_price} (differs from search price of ₹{search_price})."
        )

    return {
        "hold_id": hold_id,
        "quoted_price": quoted_price,
        "hold_expires_at": expires_at,
        "selected_slot": slot,
        "selected_provider": provider,
        "selected_provider_id": provider_id,
        "price_drift_note": price_drift_note,
        "tool_call_count": tool_count,
        "workflow_state": WorkflowState.AWAITING_APPROVAL.value,
    }
