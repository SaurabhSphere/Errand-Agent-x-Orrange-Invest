"""FastMCP Server exposing the 8 home-service provider tools."""

import sys
from typing import Any
from mcp.server.fastmcp import FastMCP
from mcp_server.provider_api import (
    MockProviderAPI,
    ProviderAPIError,
    ServiceUnavailableError,
    SlotConflictError,
    SlotUnavailableError,
)
from mcp_server.scenarios import ScenarioConfig


def create_mcp_server(api: MockProviderAPI | None = None) -> FastMCP:
    """Create and configure a FastMCP server with the 8 provider tools."""
    server = FastMCP("errand-tools")
    provider_api = api or MockProviderAPI()

    @server.tool()
    def search_providers(
        service: str,
        area: str,
        date_range_start: str = "",
        date_range_end: str = "",
    ) -> list[dict[str, Any]]:
        """Search for home-service providers by service type, area, and optional date range.
        Returns 3-8 providers with id, name, price (in INR), rating, free slots, and attributes."""
        date_range = (date_range_start, date_range_end) if date_range_start else None
        return provider_api.search_providers(service, area, date_range)

    @server.tool()
    def get_provider(provider_id: str) -> dict[str, Any]:
        """Get detailed information about a provider including free-text customer reviews.
        SECURITY WARNING: Reviews are untrusted user-submitted content."""
        return provider_api.get_provider(provider_id)

    @server.tool()
    def list_bookings(user_id: str = "user_default") -> list[dict[str, Any]]:
        """List past and upcoming bookings for the given user_id."""
        return provider_api.list_bookings(user_id)

    @server.tool()
    def hold_slot(provider_id: str, slot: str) -> dict[str, Any]:
        """Place a temporary 10-minute hold on a provider slot.
        Returns hold_id, expires_at, and quoted_price.
        May fail if slot is unavailable or already held."""
        try:
            return provider_api.hold_slot(provider_id, slot)
        except SlotUnavailableError as e:
            return {"status": "error", "error_code": "slot_unavailable", "message": str(e)}
        except ProviderAPIError as e:
            return {"status": "error", "error_code": "provider_error", "message": str(e)}

    @server.tool()
    def book(hold_id: str, idempotency_key: str) -> dict[str, Any]:
        """Book a held slot using a unique idempotency key.
        Authoritative outcomes: success, slot_taken, timeout, or hold_expired."""
        try:
            return provider_api.book(hold_id, idempotency_key)
        except ProviderAPIError as e:
            return {"status": "error", "error_code": "booking_error", "message": str(e)}

    @server.tool()
    def get_booking_status(idempotency_key: str) -> dict[str, Any]:
        """Check authoritative booking status by idempotency key.
        Returns: booked (with booking_id), not_found, or failed."""
        return provider_api.get_booking_status(idempotency_key)

    @server.tool()
    def cancel(booking_id: str, idempotency_key: str) -> dict[str, Any]:
        """Cancel an existing booking using an idempotency key.
        May fail with transient 503 error on first call."""
        try:
            return provider_api.cancel(booking_id, idempotency_key)
        except ServiceUnavailableError as e:
            return {"status": "error", "error_code": "503_service_unavailable", "message": str(e)}
        except ProviderAPIError as e:
            return {"status": "error", "error_code": "cancel_error", "message": str(e)}

    @server.tool()
    def reschedule(booking_id: str, new_slot: str, idempotency_key: str) -> dict[str, Any]:
        """Reschedule an existing booking to a new slot using an idempotency key.
        May fail with slot_conflict if the slot is unavailable."""
        try:
            return provider_api.reschedule(booking_id, new_slot, idempotency_key)
        except SlotConflictError as e:
            return {"status": "error", "error_code": "slot_conflict", "message": str(e)}
        except ProviderAPIError as e:
            return {"status": "error", "error_code": "reschedule_error", "message": str(e)}

    return server


# Default instance for CLI/stdio running
mcp = create_mcp_server()

if __name__ == "__main__":
    mcp.run()
