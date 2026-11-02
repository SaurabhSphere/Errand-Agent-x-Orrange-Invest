"""Execute reschedule node with slot conflict handling."""

from typing import Any
import uuid
from langchain_core.messages import AIMessage
from mcp_server.provider_api import MockProviderAPI, SlotConflictError
from errand_agent.approval import ApprovalController, ApprovalError
from errand_agent.models import ActionType, WorkflowState
from errand_agent.state import ErrandState
from errand_agent.tracer import Tracer


def execute_reschedule_node(
    state: ErrandState,
    api: MockProviderAPI,
    approval_controller: ApprovalController,
    tracer: Tracer | None = None,
) -> dict[str, Any]:
    """Reschedule booking with slot_conflict error detection."""
    booking_id = state.get("target_booking_id", "")
    new_slot = state.get("new_reschedule_slot", "")
    provider_id = state.get("provider_id", "assigned-provider")
    price = state.get("price", 0)

    # STEP 1: Code approval check
    try:
        approval_controller.validate_for_action(
            action=ActionType.RESCHEDULE,
            provider_id=provider_id,
            slot=new_slot,
            price=price,
            booking_id=booking_id,
        )
        if tracer:
            tracer.record_approval_gate("reschedule", provider_id, new_slot, price, status="PASSED")
    except ApprovalError as e:
        if tracer:
            tracer.record_approval_gate("reschedule", provider_id, new_slot, price, status="REJECTED", reason=str(e))
        return {
            "workflow_state": WorkflowState.ERROR.value,
            "error": str(e),
            "messages": [AIMessage(content=f"❌ Rescheduling aborted by code approval gate: {e}")],
        }

    idem_key = f"resched-{booking_id}-{uuid.uuid4().hex[:8]}"
    tool_count = state.get("tool_call_count", 0) + 1

    try:
        res = api.reschedule(booking_id=booking_id, new_slot=new_slot, idempotency_key=idem_key)
        if tracer:
            tracer.record_tool_call(
                tool="reschedule",
                args={"booking_id": booking_id, "new_slot": new_slot, "idempotency_key": idem_key},
                result=res,
            )
        return {
            "tool_call_count": tool_count,
            "workflow_state": WorkflowState.CONFIRMED.value,
            "messages": [
                AIMessage(
                    content=f"✅ Booking **{booking_id}** rescheduled to **{new_slot}**."
                )
            ],
        }
    except SlotConflictError as e:
        if tracer:
            tracer.record_tool_call(
                tool="reschedule",
                args={"booking_id": booking_id, "new_slot": new_slot, "idempotency_key": idem_key},
                result=str(e),
            )
        return {
            "tool_call_count": tool_count,
            "workflow_state": WorkflowState.ERROR.value,
            "error": "slot_conflict",
            "messages": [
                AIMessage(
                    content=f"⚠️ Reschedule Conflict: Slot **{new_slot}** is occupied. Please suggest another time slot."
                )
            ],
        }
    except Exception as e:
        return {
            "tool_call_count": tool_count,
            "workflow_state": WorkflowState.ERROR.value,
            "error": str(e),
            "messages": [AIMessage(content=f"❌ Rescheduling error: {e}")],
        }
