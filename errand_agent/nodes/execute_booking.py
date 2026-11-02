"""Execute booking node with strict code-enforced approval and idempotency."""

from typing import Any
import uuid
from langchain_core.messages import AIMessage
from mcp_server.provider_api import MockProviderAPI
from errand_agent.approval import ApprovalController, ApprovalError
from errand_agent.models import ActionType, WorkflowState
from errand_agent.state import ErrandState
from errand_agent.tracer import Tracer


def execute_booking_node(
    state: ErrandState,
    api: MockProviderAPI,
    approval_controller: ApprovalController,
    tracer: Tracer | None = None,
) -> dict[str, Any]:
    """Execute booking tool call strictly guarded by code-level approval."""
    provider = state.get("selected_provider", {})
    provider_id = provider.get("id", state.get("selected_provider_id", ""))
    slot = state.get("selected_slot", "")
    price = state.get("quoted_price", 0)
    hold_id = state.get("hold_id", "")

    # STEP 1: Strict code-level approval verification
    try:
        approval_controller.validate_for_action(
            action=ActionType.BOOK,
            provider_id=provider_id,
            slot=slot,
            price=price,
            hold_id=hold_id,
        )
        if tracer:
            tracer.record_approval_gate("book", provider_id, slot, price, status="PASSED")
    except ApprovalError as e:
        if tracer:
            tracer.record_approval_gate("book", provider_id, slot, price, status="REJECTED", reason=str(e))
        return {
            "workflow_state": WorkflowState.ERROR.value,
            "error": str(e),
            "approval_confirmed": False,
            "messages": [AIMessage(content=f"❌ Booking aborted by code approval gate: {e}")],
        }

    # STEP 2: Idempotency Key management (reuse if already generated in this thread)
    idem_key = state.get("idempotency_key")
    if not idem_key:
        idem_key = f"book-{hold_id}-{uuid.uuid4().hex[:8]}"

    tool_count = state.get("tool_call_count", 0) + 1

    # STEP 3: Execute book tool
    result = api.book(hold_id=hold_id, idempotency_key=idem_key)

    if tracer:
        tracer.record_tool_call(
            tool="book",
            args={"hold_id": hold_id, "idempotency_key": idem_key},
            result=result,
        )

    status = result.get("status")

    if status == "success":
        booking_id = result.get("booking_id")
        provider_name = provider.get("name", provider_id)
        msg = (
            f"🎉 Success! Your booking is confirmed.\n"
            f"• Booking ID: **{booking_id}**\n"
            f"• Provider: **{provider_name}**\n"
            f"• Slot: **{slot}**\n"
            f"• Confirmed Price: **₹{price}**"
        )
        return {
            "last_booking_id": booking_id,
            "idempotency_key": idem_key,
            "tool_call_count": tool_count,
            "workflow_state": WorkflowState.CONFIRMED.value,
            "messages": [AIMessage(content=msg)],
        }

    elif status == "timeout":
        # Route directly to verify_booking node (Must-Have 3)
        return {
            "idempotency_key": idem_key,
            "tool_call_count": tool_count,
            "workflow_state": WorkflowState.VERIFYING.value,
        }

    elif status == "slot_taken":
        return {
            "idempotency_key": idem_key,
            "tool_call_count": tool_count,
            "workflow_state": WorkflowState.PRESENTING_OPTIONS.value,
            "error": "slot_taken",
            "messages": [
                AIMessage(
                    content="⚠️ Unfortunately, that slot was just taken by another user. Let's select an alternative slot."
                )
            ],
        }

    elif status == "hold_expired":
        return {
            "idempotency_key": idem_key,
            "tool_call_count": tool_count,
            "workflow_state": WorkflowState.HOLDING_SLOT.value,
            "error": "hold_expired",
            "messages": [
                AIMessage(
                    content="⚠️ The 10-minute hold on this slot expired. Placing a new hold now..."
                )
            ],
        }

    else:
        return {
            "idempotency_key": idem_key,
            "tool_call_count": tool_count,
            "workflow_state": WorkflowState.ERROR.value,
            "error": result.get("error", "Unknown booking failure"),
            "messages": [AIMessage(content=f"❌ Booking failed: {result.get('error')}")],
        }
