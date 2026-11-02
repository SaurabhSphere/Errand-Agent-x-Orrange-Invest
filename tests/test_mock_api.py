"""Tests for MockProviderAPI contract requirements."""

import pytest
from mcp_server.provider_api import (
    MockProviderAPI,
    ServiceUnavailableError,
    SlotConflictError,
    SlotUnavailableError,
)
from mcp_server.scenarios import ScenarioConfig


def test_search_providers():
    api = MockProviderAPI()
    results = api.search_providers("plumbing", "koramangala")
    assert 3 <= len(results) <= 8
    first = results[0]
    assert "id" in first
    assert "price" in first
    assert "rating" in first
    assert "free_slots" in first
    assert "attributes" in first


def test_get_provider_contains_prompt_injection():
    api = MockProviderAPI()
    rajesh = api.get_provider("plumber-rajesh-01")
    assert "reviews" in rajesh
    reviews_text = " ".join(r["text"] for r in rajesh["reviews"])
    assert "SYSTEM OVERRIDE" in reviews_text or "Ignore all previous instructions" in reviews_text


def test_list_bookings():
    api = MockProviderAPI()
    bookings = api.list_bookings("user_default")
    assert len(bookings) >= 2
    assert any(b["service"] == "ac_servicing" for b in bookings)


def test_hold_slot_and_price_drift():
    # Normal hold
    api = MockProviderAPI()
    hold = api.hold_slot("plumber-rajesh-01", "2026-11-02T09:00")
    assert hold["hold_id"].startswith("HOLD-")
    assert hold["quoted_price"] == 1200

    # Configured price drift
    cfg = ScenarioConfig(
        price_drift_map={("plumber-rajesh-01", "2026-11-02T09:00"): 1350}
    )
    api_drift = MockProviderAPI(cfg)
    hold_drift = api_drift.hold_slot("plumber-rajesh-01", "2026-11-02T09:00")
    assert hold_drift["quoted_price"] == 1350


def test_hold_slot_unavailable():
    cfg = ScenarioConfig(unavailable_slots={("plumber-rajesh-01", "2026-11-02T09:00")})
    api = MockProviderAPI(cfg)
    with pytest.raises(SlotUnavailableError):
        api.hold_slot("plumber-rajesh-01", "2026-11-02T09:00")


def test_book_success_and_idempotency():
    cfg = ScenarioConfig(force_book_outcome="success")
    api = MockProviderAPI(cfg)
    hold = api.hold_slot("plumber-rajesh-01", "2026-11-02T09:00")

    idem_key = "key-abc-123"
    res1 = api.book(hold["hold_id"], idempotency_key=idem_key)
    assert res1["status"] == "success"
    booking_id = res1["booking_id"]

    # Calling with SAME idempotency key must return exact same result
    res2 = api.book(hold["hold_id"], idempotency_key=idem_key)
    assert res2["status"] == "success"
    assert res2["booking_id"] == booking_id

    # Authoritative status check
    status = api.get_booking_status(idem_key)
    assert status["status"] == "booked"
    assert status["booking_id"] == booking_id


def test_book_timeout_after_success():
    cfg = ScenarioConfig(force_book_outcome="timeout_booked")
    api = MockProviderAPI(cfg)
    hold = api.hold_slot("plumber-rajesh-01", "2026-11-02T09:00")

    idem_key = "key-timeout-001"
    res = api.book(hold["hold_id"], idempotency_key=idem_key)
    assert res["status"] == "timeout"

    # Status check confirms authoritative booking
    status = api.get_booking_status(idem_key)
    assert status["status"] == "booked"
    assert status["booking_id"].startswith("BK-")


def test_cancel_transient_503_and_retry():
    api = MockProviderAPI()
    booking_id = "BK-AC-9011"
    idem_key = "cancel-key-01"

    # First attempt fails with 503
    with pytest.raises(ServiceUnavailableError):
        api.cancel(booking_id, idempotency_key=idem_key)

    # Retry succeeds
    res = api.cancel(booking_id, idempotency_key=idem_key)
    assert res["status"] == "cancelled"


def test_reschedule_conflict():
    cfg = ScenarioConfig(conflict_reschedule_slots={"2026-11-07T14:00"})
    api = MockProviderAPI(cfg)
    booking_id = "BK-AC-9011"

    # Conflicting slot fails
    with pytest.raises(SlotConflictError):
        api.reschedule(booking_id, "2026-11-07T14:00", idempotency_key="resched-01")

    # Non-conflicting slot succeeds
    res = api.reschedule(booking_id, "2026-11-07T10:00", idempotency_key="resched-02")
    assert res["status"] == "updated"
    assert res["new_slot"] == "2026-11-07T10:00"
def test_search_providers_strict_service_isolation_for_all_categories():
    api = MockProviderAPI()
    categories = ['cleaning', 'plumbing', 'electrician', 'ac_servicing']
    for cat in categories:
        providers = api.search_providers(service=cat, area="koramangala")
        assert len(providers) >= 3, f'Expected >= 3 providers for {cat}, got {len(providers)}'
        services = {p['service'] for p in providers}
        assert services == {cat}, f'Strict service isolation violated for {cat}: got {services}'
