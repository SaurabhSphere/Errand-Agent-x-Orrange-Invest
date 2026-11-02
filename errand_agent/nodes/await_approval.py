"""Approval presentation and record preparation node."""

from typing import Any
from langchain_core.messages import AIMessage
from errand_agent.approval import ApprovalController
from errand_agent.models import ActionType, WorkflowState
from errand_agent.state import ErrandState


def await_approval_node(
    state: ErrandState,
    approval_controller: ApprovalController,
) -> dict[str, Any]:
    """Present explicit action details to the user and register a pending ApprovalRecord."""
    action_str = state.get("current_action", "book")
    action = ActionType(action_str)

    if action == ActionType.BOOK:
        provider = state.get("selected_provider", {})
        provider_id = provider.get("id", "unknown-provider")
        provider_name = provider.get("name", "Home Service Provider")
        slot = state.get("selected_slot", "Selected Slot")
        price = state.get("quoted_price", provider.get("price", 0))
        hold_id = state.get("hold_id")
        booking_id = None

        record = approval_controller.request_approval(
            action=action,
            provider_id=provider_id,
            provider_name=provider_name,
            slot=slot,
            price=price,
            hold_id=hold_id,
        )

        drift_note = state.get("price_drift_note")
        drift_prefix = f"{drift_note}\n\n" if drift_note else ""

        prompt = (
            f"{drift_prefix}"
            f"Please confirm your booking details:\n"
            f"• Action: **Book Appointment**\n"
            f"• Provider: **{provider_name}** ({provider_id})\n"
            f"• Slot: **{slot}**\n"
            f"• Total Price: **₹{price}**\n\n"
            f"Do you approve this booking? (Reply 'yes' to confirm or 'no' to cancel)"
        )

    elif action == ActionType.CANCEL:
        booking_id = state.get("target_booking_id", "BK-UNKNOWN")
        provider_name = state.get("provider_name", "Assigned Provider")
        provider_id = state.get("provider_id", "assigned-provider")
        slot = state.get("slot", "Scheduled Slot")
        price = state.get("price", 0)

        record = approval_controller.request_approval(
            action=action,
            provider_id=provider_id,
            provider_name=provider_name,
            slot=slot,
            price=price,
            booking_id=booking_id,
        )

        prompt = (
            f"Please confirm your cancellation:\n"
            f"• Action: **Cancel Booking**\n"
            f"• Booking ID: **{booking_id}**\n\n"
            f"Are you sure you want to cancel? (Reply 'yes' to confirm or 'no' to keep)"
        )

    else:  # ActionType.RESCHEDULE
        booking_id = state.get("target_booking_id", "BK-UNKNOWN")
        new_slot = state.get("new_reschedule_slot", "New Slot")
        provider_name = state.get("provider_name", "Assigned Provider")
        provider_id = state.get("provider_id", "assigned-provider")
        price = state.get("price", 0)

        record = approval_controller.request_approval(
            action=action,
            provider_id=provider_id,
            provider_name=provider_name,
            slot=new_slot,
            price=price,
            booking_id=booking_id,
        )

        prompt = (
            f"Please confirm your reschedule request:\n"
            f"• Action: **Reschedule Booking**\n"
            f"• Booking ID: **{booking_id}**\n"
            f"• New Slot: **{new_slot}**\n\n"
            f"Do you approve moving your appointment? (Reply 'yes' to confirm or 'no' to keep current slot)"
        )

    return {
        "approval": record.model_dump(mode="json"),
        "approval_confirmed": False,
        "workflow_state": WorkflowState.AWAITING_APPROVAL.value,
        "messages": [AIMessage(content=prompt)],
    }
