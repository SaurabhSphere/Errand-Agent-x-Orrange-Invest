"""Verify booking node for authoritative status checks following a timeout."""

from typing import Any
from langchain_core.messages import AIMessage
from mcp_server.provider_api import MockProviderAPI
from errand_agent.models import WorkflowState
from errand_agent.state import ErrandState
from errand_agent.tracer import Tracer


def verify_booking_node(
    state: ErrandState,
    api: MockProviderAPI,
    tracer: Tracer | None = None,
) -> dict[str, Any]:
    """Query authoritative get_booking_status after timeout before reporting."""
    idem_key = state.get("idempotency_key", "")
    provider = state.get("selected_provider", {})
    provider_name = provider.get("name", "Provider")
    slot = state.get("selected_slot", "")
    price = state.get("quoted_price", 0)

    tool_count = state.get("tool_call_count", 0) + 1

    # Authoritative status check
    status_res = api.get_booking_status(idempotency_key=idem_key)

    if tracer:
        tracer.record_tool_call(
            tool="get_booking_status",
            args={"idempotency_key": idem_key},
            result=status_res,
        )

    authoritative_status = status_res.get("status")

    if authoritative_status == "booked":
        booking_id = status_res.get("booking_id")
        msg = (
            f"✅ Verification Confirmed! Although the initial call timed out, your booking was successfully confirmed.\n"
            f"• Booking ID: **{booking_id}**\n"
            f"• Provider: **{provider_name}**\n"
            f"• Slot: **{slot}**\n"
            f"• Price: **₹{price}**\n"
            f"(Verified via authoritative idempotency ledger)"
        )
        return {
            "last_booking_id": booking_id,
            "tool_call_count": tool_count,
            "workflow_state": WorkflowState.CONFIRMED.value,
            "messages": [AIMessage(content=msg)],
        }

    elif authoritative_status == "failed":
        return {
            "tool_call_count": tool_count,
            "workflow_state": WorkflowState.ERROR.value,
            "error": "booking_failed_after_timeout",
            "messages": [
                AIMessage(
                    content="❌ The booking timed out and could not be completed on the provider side. No charge or booking was made. Would you like to try again?"
                )
            ],
        }

    else:  # not_found
        return {
            "tool_call_count": tool_count,
            "workflow_state": WorkflowState.ERROR.value,
            "error": "booking_not_found_after_timeout",
            "messages": [
                AIMessage(
                    content="⚠️ The booking timed out and was not found in the provider records. Please retry."
                )
            ],
        }
