"""Mock Provider API implementing the fixed contract from assignment."""

import copy
from datetime import datetime, timedelta, timezone
import random
from typing import Any
import uuid

from mcp_server.data import INITIAL_BOOKINGS, PROVIDERS_DATA, REVIEWS_DATA
from mcp_server.scenarios import ScenarioConfig


class ProviderAPIError(Exception):
    """Base error for Provider API failures."""
    pass


class SlotUnavailableError(ProviderAPIError):
    pass


class SlotConflictError(ProviderAPIError):
    pass


class HoldExpiredError(ProviderAPIError):
    pass


class ServiceUnavailableError(ProviderAPIError):
    """Represents a transient 503 error."""
    pass


class MockProviderAPI:
    """Mock implementation of the 8 provider tools with strictly enforced behavior."""

    def __init__(self, config: ScenarioConfig | None = None):
        self.config = config or ScenarioConfig()
        self._rng = random.Random(self.config.seed)

        # Internal state
        self._providers = {p["id"]: copy.deepcopy(p) for p in PROVIDERS_DATA}
        self._reviews = copy.deepcopy(REVIEWS_DATA)

        # Map of hold_id -> hold dictionary
        self._holds: dict[str, dict[str, Any]] = {}

        # Map of booking_id -> booking dictionary
        self._bookings: dict[str, dict[str, Any]] = {}
        for b in INITIAL_BOOKINGS:
            self._bookings[b["booking_id"]] = copy.deepcopy(b)

        # Idempotency log: idempotency_key -> response payload or status
        # This is the authoritative ledger for get_booking_status and deduplication
        self._idempotency_records: dict[str, dict[str, Any]] = {}

        # Track cancel attempts per booking_id or idempotency_key for 503 transient failure
        self._cancel_attempt_counts: dict[str, int] = {}

    def search_providers(
        self,
        service: str,
        area: str,
        date_range: tuple[str, str] | list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search for providers matching service and area. Returns 3-8 providers."""
        service_clean = service.lower().strip().replace(" ", "_")
        area_clean = area.lower().strip()

        matched = []
        for p in self._providers.values():
            p_service = p["service"].lower().replace(" ", "_")
            p_area = p["area"].lower()

            # Flexible match for service & area
            service_match = (
                service_clean in p_service
                or p_service in service_clean
                or ("plumb" in service_clean and "plumb" in p_service)
                or ("electr" in service_clean and "electr" in p_service)
                or ("ac" in service_clean and "ac" in p_service)
                or ("clean" in service_clean and "clean" in p_service)
            )
            area_match = area_clean in p_area or p_area in area_clean or not area_clean

            if service_match and area_match:
                matched.append(copy.deepcopy(p))

        # If strict match yields fewer than 3, fall back to matching service anywhere
        if len(matched) < 3:
            for p in self._providers.values():
                if p not in matched and ("plumb" in service_clean and "plumb" in p["service"]):
                    matched.append(copy.deepcopy(p))

        # Always return between 3 and 8 providers
        return matched[:8] if len(matched) >= 3 else list(self._providers.values())[:5]

    def get_provider(self, provider_id: str) -> dict[str, Any]:
        """Fetch provider details and free-text reviews."""
        if provider_id not in self._providers:
            raise ProviderAPIError(f"Provider '{provider_id}' not found")

        provider_copy = copy.deepcopy(self._providers[provider_id])
        provider_copy["reviews"] = copy.deepcopy(self._reviews.get(provider_id, []))
        return provider_copy

    def list_bookings(self, user_id: str = "user_default") -> list[dict[str, Any]]:
        """Return user's past and upcoming bookings."""
        return [
            copy.deepcopy(b)
            for b in self._bookings.values()
            if b.get("user_id") == user_id
        ]

    def hold_slot(self, provider_id: str, slot: str) -> dict[str, Any]:
        """Place a 10-minute hold on a provider's slot.

        Returns hold_id, expires_at, quoted_price.
        May fail with SlotUnavailableError.
        quoted_price may differ from search price if configured.
        """
        if (provider_id, slot) in self.config.unavailable_slots:
            raise SlotUnavailableError(f"Slot {slot} for provider {provider_id} is unavailable")

        provider = self._providers.get(provider_id)
        if not provider:
            raise ProviderAPIError(f"Provider {provider_id} not found")

        # Check configured price drift
        search_price = provider["price"]
        quoted_price = self.config.price_drift_map.get((provider_id, slot), search_price)

        hold_id = f"HOLD-{uuid.uuid4().hex[:8].upper()}"
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.config.hold_duration_seconds)

        hold_data = {
            "hold_id": hold_id,
            "provider_id": provider_id,
            "provider_name": provider["name"],
            "service": provider["service"],
            "slot": slot,
            "quoted_price": quoted_price,
            "expires_at": expires_at.isoformat(),
            "expires_at_dt": expires_at,
        }
        self._holds[hold_id] = hold_data

        return {
            "hold_id": hold_id,
            "expires_at": expires_at.isoformat(),
            "quoted_price": quoted_price,
        }

    def book(self, hold_id: str, idempotency_key: str) -> dict[str, Any]:
        """Book a held slot with idempotency protection.

        Contract:
        - 70% success
        - 15% slot_taken
        - 15% timeout (of which half actually booked)
        - hold_expired if past expiry
        - Identical idempotency_key returns cached result
        """
        if not idempotency_key:
            raise ValueError("idempotency_key is mandatory for book()")

        # Idempotency check: if this key was already processed, return existing outcome
        if idempotency_key in self._idempotency_records:
            return copy.deepcopy(self._idempotency_records[idempotency_key]["client_return"])

        hold = self._holds.get(hold_id)
        if not hold:
            raise ProviderAPIError(f"Hold '{hold_id}' not found")

        # Expiry check
        now = datetime.now(timezone.utc)
        if now >= hold["expires_at_dt"]:
            res = {"status": "hold_expired", "error": "Hold expired before booking confirmation"}
            self._idempotency_records[idempotency_key] = {
                "authoritative_status": "failed",
                "booking_id": None,
                "client_return": res,
            }
            return res

        # Determine outcome (deterministic override or probabilistic roll)
        outcome = self.config.force_book_outcome
        if not outcome:
            roll = self._rng.random()
            if roll < self.config.book_success_rate:
                outcome = "success"
            elif roll < (self.config.book_success_rate + self.config.book_slot_taken_rate):
                outcome = "slot_taken"
            else:
                # Timeout
                if self._rng.random() < self.config.timeout_actually_booked_rate:
                    outcome = "timeout_booked"
                else:
                    outcome = "timeout_failed"

        if outcome == "success":
            booking_id = f"BK-{uuid.uuid4().hex[:6].upper()}"
            booking = {
                "booking_id": booking_id,
                "user_id": "user_default",
                "provider_id": hold["provider_id"],
                "provider_name": hold["provider_name"],
                "service": hold["service"],
                "slot": hold["slot"],
                "price": hold["quoted_price"],
                "status": "booked",
                "idempotency_key": idempotency_key,
                "created_at": now.isoformat(),
            }
            self._bookings[booking_id] = booking
            client_res = {"status": "success", "booking_id": booking_id}
            self._idempotency_records[idempotency_key] = {
                "authoritative_status": "booked",
                "booking_id": booking_id,
                "client_return": client_res,
            }
            return client_res

        elif outcome == "slot_taken":
            client_res = {"status": "slot_taken", "error": "Slot was taken by another user"}
            self._idempotency_records[idempotency_key] = {
                "authoritative_status": "failed",
                "booking_id": None,
                "client_return": client_res,
            }
            return client_res

        elif outcome == "hold_expired":
            client_res = {"status": "hold_expired", "error": "Hold has expired"}
            self._idempotency_records[idempotency_key] = {
                "authoritative_status": "failed",
                "booking_id": None,
                "client_return": client_res,
            }
            return client_res

        elif outcome == "timeout_booked":
            # Call times out, BUT the booking actually succeeded in the backend
            booking_id = f"BK-{uuid.uuid4().hex[:6].upper()}"
            booking = {
                "booking_id": booking_id,
                "user_id": "user_default",
                "provider_id": hold["provider_id"],
                "provider_name": hold["provider_name"],
                "service": hold["service"],
                "slot": hold["slot"],
                "price": hold["quoted_price"],
                "status": "booked",
                "idempotency_key": idempotency_key,
                "created_at": now.isoformat(),
            }
            self._bookings[booking_id] = booking
            client_res = {"status": "timeout", "error": "Connection timed out during booking call"}
            # The authoritative ledger registers it as booked!
            self._idempotency_records[idempotency_key] = {
                "authoritative_status": "booked",
                "booking_id": booking_id,
                "client_return": client_res,
            }
            return client_res

        else:  # timeout_failed
            client_res = {"status": "timeout", "error": "Connection timed out during booking call"}
            self._idempotency_records[idempotency_key] = {
                "authoritative_status": "failed",
                "booking_id": None,
                "client_return": client_res,
            }
            return client_res

    def get_booking_status(self, idempotency_key: str) -> dict[str, Any]:
        """Authoritative source of truth for a booking attempt.

        Returns:
        - {"status": "booked", "booking_id": "..."}
        - {"status": "not_found"}
        - {"status": "failed"}
        """
        record = self._idempotency_records.get(idempotency_key)
        if not record:
            return {"status": "not_found"}

        if record["authoritative_status"] == "booked":
            return {
                "status": "booked",
                "booking_id": record["booking_id"],
            }
        else:
            return {"status": "failed"}

    def cancel(self, booking_id: str, idempotency_key: str) -> dict[str, Any]:
        """Cancel a booking.

        Contract: First call fails with transient 503; retry succeeds.
        """
        if not idempotency_key:
            raise ValueError("idempotency_key is mandatory for cancel()")

        booking = self._bookings.get(booking_id)
        if not booking:
            raise ProviderAPIError(f"Booking '{booking_id}' not found")

        # Transient 503 check on first attempt
        attempts = self._cancel_attempt_counts.get(booking_id, 0)
        self._cancel_attempt_counts[booking_id] = attempts + 1

        if attempts == 0 and self.config.cancel_first_call_fails_503:
            raise ServiceUnavailableError("503 Service Unavailable: Provider backend temporarily busy. Please retry.")

        # Successful cancellation
        booking["status"] = "cancelled"
        booking["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        return {"status": "cancelled", "booking_id": booking_id}

    def reschedule(self, booking_id: str, new_slot: str, idempotency_key: str) -> dict[str, Any]:
        """Reschedule a booking to new_slot.

        Contract: slot_conflict on configured slots.
        """
        if not idempotency_key:
            raise ValueError("idempotency_key is mandatory for reschedule()")

        booking = self._bookings.get(booking_id)
        if not booking:
            raise ProviderAPIError(f"Booking '{booking_id}' not found")

        # Slot conflict check
        if new_slot in self.config.conflict_reschedule_slots:
            raise SlotConflictError(f"Slot conflict: {new_slot} is already occupied for provider {booking['provider_id']}")

        booking["slot"] = new_slot
        booking["rescheduled_at"] = datetime.now(timezone.utc).isoformat()
        return {
            "status": "updated",
            "booking_id": booking_id,
            "new_slot": new_slot,
            "provider_name": booking["provider_name"],
            "price": booking["price"],
        }
