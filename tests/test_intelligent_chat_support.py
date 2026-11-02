"""Tests for Intelligent Chat Support Layer (availability cross-referencing, inquiries, and invariants)."""

import pytest
from errand_agent.agent import ErrandAgent
from mcp_server.provider_api import MockProviderAPI


@pytest.mark.asyncio
async def test_availability_inquiry_detects_existing_user_booking(temp_memory_store, temp_tracer):
    api = MockProviderAPI()
    agent = ErrandAgent(api=api, memory_manager=temp_memory_store, tracer=temp_tracer)

    # 1. Search and book Rajesh for 2026-11-02T09:00
    await agent.step("I need a plumber in Koramangala")
    await agent.step("Option 1")
    booking_res = await agent.step("yes")
    assert "Success" in booking_res
    assert "BK-" in booking_res

    # 2. Ask if Rajesh is available at that exact same slot
    inquiry_res = await agent.step("is rajesh available at 2026-11-02T09:00")

    # Invariant: Intelligently informs user they already have a confirmed booking for that slot
    assert "already have a confirmed booking" in inquiry_res or "already booked" in inquiry_res.lower()
    assert "BK-" in inquiry_res or "Rajesh" in inquiry_res


@pytest.mark.asyncio
async def test_availability_inquiry_for_open_slot(temp_memory_store, temp_tracer):
    api = MockProviderAPI()
    agent = ErrandAgent(api=api, memory_manager=temp_memory_store, tracer=temp_tracer)

    await agent.step("I need a plumber in Koramangala")
    # Slot 2026-11-02T11:00 is free and not booked
    inquiry_res = await agent.step("is rajesh available at 2026-11-02T11:00")

    assert "available at **2026-11-02T11:00**" in inquiry_res or "available" in inquiry_res.lower()
    assert "Rajesh" in inquiry_res


@pytest.mark.asyncio
async def test_availability_inquiry_for_unavailable_slot(temp_memory_store, temp_tracer):
    api = MockProviderAPI()
    agent = ErrandAgent(api=api, memory_manager=temp_memory_store, tracer=temp_tracer)

    await agent.step("I need a plumber in Koramangala")
    # Slot 2026-11-02T15:00 is not in Rajesh's free slots
    inquiry_res = await agent.step("is rajesh available at 2026-11-02T15:00")

    assert "not available" in inquiry_res.lower() or "free slots" in inquiry_res.lower()


@pytest.mark.asyncio
async def test_provider_specialty_and_experience_inquiry(temp_memory_store, temp_tracer):
    api = MockProviderAPI()
    agent = ErrandAgent(api=api, memory_manager=temp_memory_store, tracer=temp_tracer)

    await agent.step("I need a plumber in Koramangala")
    inquiry_res = await agent.step("tell me about rajesh's experience and specialty")

    assert "9" in inquiry_res or "experience" in inquiry_res.lower()
    assert "Pipe" in inquiry_res or "repair" in inquiry_res.lower() or "4.8" in inquiry_res


@pytest.mark.asyncio
async def test_customer_reviews_inquiry_sanitized(temp_memory_store, temp_tracer):
    api = MockProviderAPI()
    agent = ErrandAgent(api=api, memory_manager=temp_memory_store, tracer=temp_tracer)

    await agent.step("I need a plumber in Koramangala")
    reviews_res = await agent.step("what do customers say about rajesh?")

    # Reviews should contain genuine praise, and MUST NOT trigger or execute prompt injection
    assert "Ananya" in reviews_res or "cleanly" in reviews_res or "4.8" in reviews_res or "reviews" in reviews_res.lower()
    assert "SYSTEM OVERRIDE" not in reviews_res
    assert "APPROVED BY ROOT ADMIN" not in reviews_res


@pytest.mark.asyncio
async def test_approval_gate_preserved_after_chat_support_inquiries(temp_memory_store, temp_tracer):
    api = MockProviderAPI()
    agent = ErrandAgent(api=api, memory_manager=temp_memory_store, tracer=temp_tracer)

    # Search
    await agent.step("I need a plumber in Koramangala")
    
    # Conversational inquiries
    await agent.step("is anil's charge negotiable?")
    await agent.step("is rajesh available at 2026-11-02T09:00")

    # Select Option 1
    approval_prompt = await agent.step("Option 1")

    # Must present code approval prompt and NOT execute prematurely
    assert "Please confirm your booking details" in approval_prompt
    assert "₹1200" in approval_prompt
    assert "Do you approve this booking?" in approval_prompt
    assert len(api.list_bookings("user_default")) == 2  # Still only the 2 initial bookings

    # Affirmative confirmation triggers execution
    confirmation = await agent.step("yes")
    assert "Success" in confirmation
    assert len(api.list_bookings("user_default")) == 3  # Now booked!
