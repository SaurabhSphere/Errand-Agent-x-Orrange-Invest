"""LangChain tool adapter for MockProviderAPI and MCP server."""

from typing import Any
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from mcp_server.provider_api import (
    MockProviderAPI,
    ProviderAPIError,
    ServiceUnavailableError,
    SlotConflictError,
    SlotUnavailableError,
)


class SearchProvidersInput(BaseModel):
    service: str = Field(description="Service type, e.g. plumbing, electrician, ac_servicing, cleaning")
    area: str = Field(description="Locality / neighborhood, e.g. koramangala, indiranagar")
    date_range_start: str = Field(default="", description="Start date in ISO format or empty")
    date_range_end: str = Field(default="", description="End date in ISO format or empty")


class GetProviderInput(BaseModel):
    provider_id: str = Field(description="Unique provider ID, e.g. plumber-rajesh-01")


class ListBookingsInput(BaseModel):
    user_id: str = Field(default="user_default", description="User identifier")


class HoldSlotInput(BaseModel):
    provider_id: str = Field(description="Unique provider ID")
    slot: str = Field(description="Requested time slot in ISO format, e.g. 2026-11-02T09:00")


class BookInput(BaseModel):
    hold_id: str = Field(description="Valid hold ID returned by hold_slot")
    idempotency_key: str = Field(description="Unique client idempotency key to prevent double bookings")


class GetBookingStatusInput(BaseModel):
    idempotency_key: str = Field(description="Client idempotency key previously used with book()")


class CancelInput(BaseModel):
    booking_id: str = Field(description="Unique booking ID to cancel")
    idempotency_key: str = Field(description="Unique idempotency key for this cancellation request")


class RescheduleInput(BaseModel):
    booking_id: str = Field(description="Unique booking ID to reschedule")
    new_slot: str = Field(description="Target new slot in ISO format")
    idempotency_key: str = Field(description="Unique idempotency key for this reschedule request")


def get_errand_tools(api: MockProviderAPI) -> list[StructuredTool]:
    """Build LangChain StructuredTools from the MockProviderAPI instance."""

    def _search(service: str, area: str, date_range_start: str = "", date_range_end: str = "") -> Any:
        date_range = (date_range_start, date_range_end) if date_range_start else None
        return api.search_providers(service, area, date_range)

    def _get_provider(provider_id: str) -> Any:
        return api.get_provider(provider_id)

    def _list_bookings(user_id: str = "user_default") -> Any:
        return api.list_bookings(user_id)

    def _hold_slot(provider_id: str, slot: str) -> Any:
        try:
            return api.hold_slot(provider_id, slot)
        except SlotUnavailableError as e:
            return {"status": "error", "error_code": "slot_unavailable", "message": str(e)}
        except ProviderAPIError as e:
            return {"status": "error", "error_code": "provider_error", "message": str(e)}

    def _book(hold_id: str, idempotency_key: str) -> Any:
        try:
            return api.book(hold_id, idempotency_key)
        except ProviderAPIError as e:
            return {"status": "error", "error_code": "booking_error", "message": str(e)}

    def _get_booking_status(idempotency_key: str) -> Any:
        return api.get_booking_status(idempotency_key)

    def _cancel(booking_id: str, idempotency_key: str) -> Any:
        try:
            return api.cancel(booking_id, idempotency_key)
        except ServiceUnavailableError as e:
            return {"status": "error", "error_code": "503_service_unavailable", "message": str(e)}
        except ProviderAPIError as e:
            return {"status": "error", "error_code": "cancel_error", "message": str(e)}

    def _reschedule(booking_id: str, new_slot: str, idempotency_key: str) -> Any:
        try:
            return api.reschedule(booking_id, new_slot, idempotency_key)
        except SlotConflictError as e:
            return {"status": "error", "error_code": "slot_conflict", "message": str(e)}
        except ProviderAPIError as e:
            return {"status": "error", "error_code": "reschedule_error", "message": str(e)}

    return [
        StructuredTool.from_function(
            func=_search,
            name="search_providers",
            description="Search for available home-service providers by service and area.",
            args_schema=SearchProvidersInput,
        ),
        StructuredTool.from_function(
            func=_get_provider,
            name="get_provider",
            description="Fetch provider profile details and reviews by provider_id.",
            args_schema=GetProviderInput,
        ),
        StructuredTool.from_function(
            func=_list_bookings,
            name="list_bookings",
            description="List user bookings: id, provider, service, slot, status.",
            args_schema=ListBookingsInput,
        ),
        StructuredTool.from_function(
            func=_hold_slot,
            name="hold_slot",
            description="Place a 10-minute hold on a provider slot before booking.",
            args_schema=HoldSlotInput,
        ),
        StructuredTool.from_function(
            func=_book,
            name="book",
            description="Book a held slot with an idempotency key. Requires prior user approval.",
            args_schema=BookInput,
        ),
        StructuredTool.from_function(
            func=_get_booking_status,
            name="get_booking_status",
            description="Authoritative check of booking status by idempotency key.",
            args_schema=GetBookingStatusInput,
        ),
        StructuredTool.from_function(
            func=_cancel,
            name="cancel",
            description="Cancel an active booking. Requires prior user approval.",
            args_schema=CancelInput,
        ),
        StructuredTool.from_function(
            func=_reschedule,
            name="reschedule",
            description="Reschedule an active booking to a new slot. Requires prior user approval.",
            args_schema=RescheduleInput,
        ),
    ]
