"""Data models and schemas for Errand Agent."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class WorkflowState(str, Enum):
    IDLE = "idle"
    GATHERING_INFO = "gathering_info"
    SEARCHING = "searching"
    PRESENTING_OPTIONS = "presenting_options"
    AWAITING_SELECTION = "awaiting_selection"
    HOLDING_SLOT = "holding_slot"
    AWAITING_APPROVAL = "awaiting_approval"
    BOOKING = "booking"
    VERIFYING = "verifying"
    CONFIRMED = "confirmed"
    CANCELLING = "cancelling"
    RESCHEDULING = "rescheduling"
    ERROR = "error"
    LIMIT_EXHAUSTED = "limit_exhausted"


class ActionType(str, Enum):
    BOOK = "book"
    CANCEL = "cancel"
    RESCHEDULE = "reschedule"


class Provider(BaseModel):
    id: str
    name: str
    service: str
    area: str
    price: int
    rating: float
    free_slots: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ProviderReview(BaseModel):
    user: str
    text: str
    rating: int


class ProviderDetail(Provider):
    reviews: list[ProviderReview] = Field(default_factory=list)


class HoldRecord(BaseModel):
    hold_id: str
    provider_id: str
    slot: str
    quoted_price: int
    expires_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at


class ApprovalRecord(BaseModel):
    action: ActionType
    provider_id: str
    provider_name: str
    slot: str
    price: int
    booking_id: str | None = None
    hold_id: str | None = None
    approved: bool = False
    approved_at: datetime | None = None
    voided: bool = False
    void_reason: str | None = None

    def void(self, reason: str) -> None:
        self.voided = True
        self.approved = False
        self.void_reason = reason


class BookingRecord(BaseModel):
    booking_id: str
    user_id: str
    provider_id: str
    provider_name: str
    service: str
    slot: str
    price: int
    status: Literal["booked", "cancelled"] = "booked"
    idempotency_key: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MemorySource(str, Enum):
    USER_STATED = "user_stated"
    AGENT_INFERRED = "agent_inferred"


class MemoryFact(BaseModel):
    key: str
    value: str
    source: MemorySource
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    forgotten: bool = False
    forgotten_at: datetime | None = None


class ExecutionLimits(BaseModel):
    max_model_turns: int = 20
    max_tool_calls: int = 50
    max_wall_clock_seconds: float = 120.0
    current_model_turns: int = 0
    current_tool_calls: int = 0
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def check_limits(self) -> tuple[bool, str | None]:
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        if self.current_model_turns >= self.max_model_turns:
            return False, f"Max model turns ({self.max_model_turns}) exceeded"
        if self.current_tool_calls >= self.max_tool_calls:
            return False, f"Max tool calls ({self.max_tool_calls}) exceeded"
        if elapsed >= self.max_wall_clock_seconds:
            return False, f"Max wall-clock time ({self.max_wall_clock_seconds}s) exceeded"
        return True, None
