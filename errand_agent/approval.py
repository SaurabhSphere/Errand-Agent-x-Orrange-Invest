"""Code-enforced approval controller for high-impact errand actions."""

from datetime import datetime, timezone
from typing import Any
from errand_agent.models import ActionType, ApprovalRecord


class ApprovalError(Exception):
    """Base error for approval validation failures."""
    pass


class ApprovalRequiredError(ApprovalError):
    """Raised when an action is attempted without active approval."""
    pass


class ApprovalVoidedError(ApprovalError):
    """Raised when an approval is voided due to changed action, provider, slot, or price."""
    pass


class ApprovalDeclinedError(ApprovalError):
    """Raised when the user declines or inputs anything other than affirmative approval."""
    pass


class NoApprovalPendingError(ApprovalError):
    """Raised when confirmation is received without an outstanding approval request."""
    pass


AFFIRMATIVE_RESPONSES = {
    "yes", "y", "confirm", "approve", "approved", "ok", "proceed",
    "yes please", "sure", "go ahead", "book it", "confirm booking"
}

DECLINE_RESPONSES = {
    "no", "n", "cancel", "decline", "stop", "abort", "don't", "dont", "nevermind"
}


class ApprovalController:
    """Manages explicit, code-enforced approval records.

    Rules enforced:
    1. An action (book, cancel, reschedule) MUST have a validated ApprovalRecord.
    2. Approval can only be granted by explicit affirmative user confirmation.
    3. Any discrepancy between approved details (action, provider, slot, price)
       and the execution payload immediately VOIDS the approval.
    4. Model output CANNOT create or grant approval.
    """

    def __init__(self):
        self.pending_approval: ApprovalRecord | None = None
        self.history: list[ApprovalRecord] = []

    def request_approval(
        self,
        action: ActionType | str,
        provider_id: str,
        provider_name: str,
        slot: str,
        price: int,
        booking_id: str | None = None,
        hold_id: str | None = None,
    ) -> ApprovalRecord:
        """Create a new pending approval record. Replaces any previous pending request."""
        if isinstance(action, str):
            action = ActionType(action.lower())

        record = ApprovalRecord(
            action=action,
            provider_id=provider_id,
            provider_name=provider_name,
            slot=slot,
            price=price,
            booking_id=booking_id,
            hold_id=hold_id,
            approved=False,
            voided=False,
        )
        self.pending_approval = record
        return record

    def process_user_confirmation(self, user_input: str) -> tuple[bool, str]:
        """Process user text against the pending approval record.

        Returns (is_approved, explanation_message).
        """
        if not self.pending_approval:
            raise NoApprovalPendingError("No action is currently awaiting your approval.")

        cleaned = user_input.strip().lower()

        if cleaned in AFFIRMATIVE_RESPONSES:
            self.pending_approval.approved = True
            self.pending_approval.approved_at = datetime.now(timezone.utc)
            self.history.append(self.pending_approval)
            return True, "Approval granted."

        if cleaned in DECLINE_RESPONSES:
            self.pending_approval.void("Declined by user")
            self.history.append(self.pending_approval)
            self.pending_approval = None
            raise ApprovalDeclinedError("Action was declined by the user.")

        # Anything ambiguous or non-affirmative is treated as NOT approved
        return False, "Input was not recognized as an affirmative confirmation. Please reply with 'yes' to confirm or 'no' to decline."

    def validate_for_action(
        self,
        action: ActionType | str,
        provider_id: str,
        slot: str,
        price: int,
        hold_id: str | None = None,
        booking_id: str | None = None,
    ) -> ApprovalRecord:
        """Strict code gate executed immediately before calling book, cancel, or reschedule.

        Raises ApprovalVoidedError or ApprovalRequiredError if not strictly valid.
        """
        if isinstance(action, str):
            action = ActionType(action.lower())

        record = self.pending_approval
        if not record:
            raise ApprovalRequiredError(
                f"Action '{action.value}' cannot proceed: no active approval record exists."
            )

        if not record.approved:
            raise ApprovalRequiredError(
                f"Action '{action.value}' cannot proceed: approval has not been confirmed by user."
            )

        if record.voided:
            raise ApprovalVoidedError(
                f"Action '{action.value}' cannot proceed: approval was voided ({record.void_reason})."
            )

        # Check invariants
        if record.action != action:
            record.void(f"Action mismatch: approved {record.action.value}, attempted {action.value}")
            raise ApprovalVoidedError(record.void_reason)

        if record.provider_id != provider_id:
            record.void(f"Provider mismatch: approved {record.provider_id}, attempted {provider_id}")
            raise ApprovalVoidedError(record.void_reason)

        if record.slot != slot:
            record.void(f"Slot mismatch: approved '{record.slot}', attempted '{slot}'")
            raise ApprovalVoidedError(record.void_reason)

        if record.price != price:
            record.void(f"Price mismatch: approved ₹{record.price}, attempted ₹{price}")
            raise ApprovalVoidedError(record.void_reason)

        if hold_id and record.hold_id and record.hold_id != hold_id:
            record.void(f"Hold ID mismatch: approved {record.hold_id}, attempted {hold_id}")
            raise ApprovalVoidedError(record.void_reason)

        if booking_id and record.booking_id and record.booking_id != booking_id:
            record.void(f"Booking ID mismatch: approved {record.booking_id}, attempted {booking_id}")
            raise ApprovalVoidedError(record.void_reason)

        return record

    def clear(self) -> None:
        """Clear active pending approval."""
        self.pending_approval = None
