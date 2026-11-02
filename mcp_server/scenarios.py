"""Configurable scenarios and seeded randomness for Mock Provider API."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScenarioConfig:
    """Configures deterministic or probabilistic failure modes for tests."""

    seed: int = 42

    # Probabilistic book failure distributions (per specification: 70% success, 15% slot_taken, 15% timeout)
    book_success_rate: float = 0.70
    book_slot_taken_rate: float = 0.15
    book_timeout_rate: float = 0.15
    timeout_actually_booked_rate: float = 0.50

    # Deterministic overrides for evals:
    force_book_outcome: str | None = None  # "success", "slot_taken", "timeout_booked", "timeout_failed", "hold_expired"

    # Price drift: map of (provider_id, slot) -> new_price
    price_drift_map: dict[tuple[str, str], int] = field(default_factory=dict)

    # Unavailable slots for hold: set of (provider_id, slot)
    unavailable_slots: set[tuple[str, str]] = field(default_factory=set)

    # Cancel failure behavior: first call fails with 503, retry succeeds
    cancel_first_call_fails_503: bool = True

    # Reschedule conflict slots: set of (booking_id, new_slot) or set of new_slot
    conflict_reschedule_slots: set[str] = field(default_factory=set)

    # Hold expiration override in seconds (default: 600s = 10 mins)
    hold_duration_seconds: int = 600
