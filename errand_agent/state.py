"""LangGraph State definition for Errand Agent."""

from typing import Annotated, Any
from typing_extensions import TypedDict
from langgraph.graph import add_messages


class ErrandState(TypedDict, total=False):
    """Full workflow state dictionary flowing across all LangGraph nodes."""

    # --- Conversation history ---
    messages: Annotated[list[Any], add_messages]
    user_id: str
    thread_id: str

    # --- Current workflow state label ---
    workflow_state: str  # maps to WorkflowState enum

    # --- Errand intent & extracted slot fields ---
    intent: str | None  # "book", "cancel", "reschedule", "list_bookings", "memory", "general"
    service: str | None
    area: str | None
    date_range_start: str | None
    date_range_end: str | None
    time_preference: str | None
    budget_max: int | None
    budget_exceeded: bool | None
    closest_budget_provider: dict[str, Any] | None
    preferred_provider_id: str | None

    # Track provenance of collected slot fields: "user_stated" | "agent_inferred"
    slot_sources: dict[str, str]

    # --- Provider search & selection ---
    providers: list[dict[str, Any]]
    selected_provider_id: str | None
    selected_provider: dict[str, Any] | None
    selected_slot: str | None

    # --- Hold details ---
    hold_id: str | None
    quoted_price: int | None
    hold_expires_at: str | None

    # --- Approval gate record (code-enforced) ---
    approval: dict[str, Any] | None
    approval_confirmed: bool

    # --- Action Execution ---
    current_action: str | None  # "book", "cancel", "reschedule"
    target_booking_id: str | None
    new_reschedule_slot: str | None
    idempotency_key: str | None
    last_booking_id: str | None

    # --- Execution control & limits ---
    model_turn_count: int
    tool_call_count: int
    start_time: str
    limit_exhausted: bool

    # --- Error and status feedback ---
    error: str | None
    status_message: str | None
