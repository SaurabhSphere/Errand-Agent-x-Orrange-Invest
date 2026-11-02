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
async def test_trade_task_contradiction_detected(temp_memory_store, temp_tracer):
    api = MockProviderAPI()
    agent = ErrandAgent(api=api, memory_manager=temp_memory_store, tracer=temp_tracer)

    # User asks for a plumber to fix light bulb
    res = await agent.step("i need plumber to fix my light bulb")
    assert "electrician" in res.lower()
    assert "light bulb" in res.lower() or "electrical" in res.lower()


@pytest.mark.asyncio
async def test_option_attribute_inquiries_preserve_options(temp_memory_store, temp_tracer):
    api = MockProviderAPI()
    agent = ErrandAgent(api=api, memory_manager=temp_memory_store, tracer=temp_tracer)

    await agent.step("I need a plumber in Koramangala")

    # 1. Ask rating of Anil
    r_rating = await agent.step("rating of anil")
    assert "4.6" in r_rating
    assert "Anil" in r_rating

    # 2. Ask price of Anil
    r_price = await agent.step("price of anil")
    assert "1400" in r_price or "Anil" in r_price

    # 3. Direct option selection still works without re-searching!
    r_select = await agent.step("2")
    assert "Please confirm your booking details" in r_select
    assert "Anil Emergency Plumbing" in r_select
    assert "1400" in r_select


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
@pytest.mark.asyncio
async def test_cleaning_service_request_returns_only_cleaners(temp_memory_store, temp_tracer):
    api = MockProviderAPI()
    agent = ErrandAgent(api=api, memory_manager=temp_memory_store, tracer=temp_tracer)

    r1 = await agent.step('cleaning')
    assert 'area' in r1.lower() or 'locality' in r1.lower()

    res = await agent.step('koramangala')
    assert 'matching provider' in res.lower()
    assert any(name in res for name in ['SparkleClean', 'UrbanMaid', 'EcoClean', 'QuickShine'])
    assert 'Rajesh Kumar Plumbing' not in res
    assert 'Vikram Premium Plumbers' not in res
    assert 'Amit Electrical Works' not in res
