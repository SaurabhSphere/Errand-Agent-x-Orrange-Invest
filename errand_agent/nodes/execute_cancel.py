"""Execute cancel node with transient 503 retry."""

from typing import Any
import uuid
from langchain_core.messages import AIMessage
from mcp_server.provider_api import MockProviderAPI, ServiceUnavailableError
from errand_agent.approval import ApprovalController, ApprovalError
from errand_agent.models import ActionType, WorkflowState
from errand_agent.state import ErrandState
from errand_agent.tracer import Tracer


def execute_cancel_node(
    state: ErrandState,
    api: MockProviderAPI,
    approval_controller: ApprovalController,
    tracer: Tracer | None = None,
) -> dict[str, Any]:
    """Cancel booking with automatic retry on transient 503 error."""
    booking_id = state.get("target_booking_id", "")
    provider_id = state.get("provider_id", "assigned-provider")
    slot = state.get("slot", "Scheduled Slot")
    price = state.get("price", 0)

    # STEP 1: Verify code-level approval
    try:
        approval_controller.validate_for_action(
            action=ActionType.CANCEL,
            provider_id=provider_id,
            slot=slot,
            price=price,
            booking_id=booking_id,
        )
        if tracer:
            tracer.record_approval_gate("cancel", provider_id, slot, price, status="PASSED")
    except ApprovalError as e:
        if tracer:
            tracer.record_approval_gate("cancel", provider_id, slot, price, status="REJECTED", reason=str(e))
        return {
            "workflow_state": WorkflowState.ERROR.value,
            "error": str(e),
            "messages": [AIMessage(content=f"❌ Cancellation aborted by code approval gate: {e}")],
        }

    idem_key = f"cancel-{booking_id}-{uuid.uuid4().hex[:8]}"
    max_retries = 3
    tool_count = state.get("tool_call_count", 0)

    for attempt in range(1, max_retries + 1):
        tool_count += 1
        try:
            res = api.cancel(booking_id=booking_id, idempotency_key=idem_key)
            if tracer:
                tracer.record_tool_call(
                    tool="cancel",
                    args={"booking_id": booking_id, "idempotency_key": idem_key, "attempt": attempt},
                    result=res,
                )
            return {
                "tool_call_count": tool_count,
                "workflow_state": WorkflowState.CONFIRMED.value,
                "messages": [
                    AIMessage(
                        content=f"✅ Booking **{booking_id}** has been successfully cancelled."
                    )
                ],
            }
        except ServiceUnavailableError as e:
            if tracer:
                tracer.record_tool_call(
                    tool="cancel",
                    args={"booking_id": booking_id, "idempotency_key": idem_key, "attempt": attempt},
                    result=f"503 Service Unavailable (attempt {attempt})",
                )
            if attempt < max_retries:
                # Retry transient 503
                continue
            else:
                return {
                    "tool_call_count": tool_count,
                    "workflow_state": WorkflowState.ERROR.value,
                    "error": str(e),
                    "messages": [
                        AIMessage(
                            content=f"❌ Cancellation failed after {max_retries} attempts: {e}"
                        )
                    ],
                }
        except Exception as e:
            return {
                "tool_call_count": tool_count,
                "workflow_state": WorkflowState.ERROR.value,
                "error": str(e),
                "messages": [AIMessage(content=f"❌ Cancellation error: {e}")],
            }

    return {"tool_call_count": tool_count, "workflow_state": WorkflowState.ERROR.value}
