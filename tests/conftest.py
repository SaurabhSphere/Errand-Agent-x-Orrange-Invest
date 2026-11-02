"""Pytest configuration and shared fixtures for Errand Agent evals."""

import os
import tempfile
import pytest
from mcp_server.provider_api import MockProviderAPI
from mcp_server.scenarios import ScenarioConfig
from errand_agent.agent import ErrandAgent
from errand_agent.memory import MemoryManager
from errand_agent.tracer import Tracer


@pytest.fixture
def temp_memory_store():
    """Create a temporary memory json store for isolation."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "test_memory.json")
        yield MemoryManager(storage_path=path)


@pytest.fixture
def temp_tracer():
    """Create a temporary tracer for isolation."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Tracer(trace_dir=tmp_dir)
