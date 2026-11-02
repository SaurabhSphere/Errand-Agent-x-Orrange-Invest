"""Unit tests for MemoryManager and Tracer."""

import os
import tempfile
import pytest
from errand_agent.memory import MemoryManager
from errand_agent.models import MemorySource
from errand_agent.tracer import Tracer


def test_memory_provenance_and_recall():
    with tempfile.TemporaryDirectory() as tmp_dir:
        store_path = os.path.join(tmp_dir, "test_memory.json")
        mem = MemoryManager(storage_path=store_path)

        # 1. Store user stated preference
        mem.remember("user1", "preferred_area", "koramangala", source=MemorySource.USER_STATED)
        f1 = mem.recall("user1", "preferred_area")
        assert f1 is not None
        assert f1.value == "koramangala"
        assert f1.source == MemorySource.USER_STATED

        # 2. Store agent inferred preference
        mem.remember("user1", "preferred_slot_time", "mornings", source=MemorySource.AGENT_INFERRED)
        f2 = mem.recall("user1", "preferred_slot_time")
        assert f2 is not None
        assert f2.source == MemorySource.AGENT_INFERRED

        # 3. Prompt context flags inferred vs confirmed
        ctx = mem.get_context_for_prompt("user1")
        assert "[CONFIRMED / USER STATED] preferred_area: koramangala" in ctx
        assert "[AGENT INFERRED - MUST CONFIRM BEFORE USING] preferred_slot_time: mornings" in ctx


def test_memory_forget_semantics():
    with tempfile.TemporaryDirectory() as tmp_dir:
        store_path = os.path.join(tmp_dir, "test_memory.json")
        mem = MemoryManager(storage_path=store_path)

        mem.remember("user1", "preferred_technician", "electrician-amit-01")
        assert mem.recall("user1", "preferred_technician") is not None

        # User requests to forget it
        mem.forget("user1", "preferred_technician")
        assert mem.recall("user1", "preferred_technician") is None

        # Invariant: Forgotten facts are NEVER reused via agent inference!
        revived = mem.remember(
            "user1",
            "preferred_technician",
            "electrician-amit-01",
            source=MemorySource.AGENT_INFERRED,
        )
        assert revived is None
        assert mem.recall("user1", "preferred_technician") is None

        # But if the user explicitly re-states it, it is restored
        user_stated = mem.remember(
            "user1",
            "preferred_technician",
            "electrician-amit-01",
            source=MemorySource.USER_STATED,
        )
        assert user_stated is not None
        assert mem.recall("user1", "preferred_technician").value == "electrician-amit-01"


def test_memory_correct():
    with tempfile.TemporaryDirectory() as tmp_dir:
        store_path = os.path.join(tmp_dir, "test_memory.json")
        mem = MemoryManager(storage_path=store_path)

        mem.remember("user1", "preferred_area", "indiranagar")
        assert mem.recall("user1", "preferred_area").value == "indiranagar"

        # User corrects area
        mem.correct("user1", "preferred_area", "koramangala")
        assert mem.recall("user1", "preferred_area").value == "koramangala"


def test_tracer_records_and_scrubs_secrets():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tracer = Tracer(trace_dir=tmp_dir)

        tracer.record_state_transition("idle", "gathering_info", "User initiated errand search")
        tracer.record_tool_call("search_providers", {"service": "plumbing"}, [{"id": "plumber-01"}], latency_ms=45.2)

        # Record event containing secret
        tracer.record("api_request", authorization="Bearer sk-abcdef12345678901234567890")

        assert len(tracer.entries) == 3
        assert tracer.entries[0]["event"] == "state_transition"
        assert tracer.entries[1]["event"] == "tool_call"

        # Check scrubbing
        secret_entry = tracer.entries[2]
        assert "sk-abcdef" not in str(secret_entry)
        assert "[REDACTED_SECRET]" in str(secret_entry)

        # Check file was written
        assert tracer.trace_file.exists()
