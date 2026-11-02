# Errand Agent — Founding AI Engineer Assignment

[![Eval Status](https://img.shields.io/badge/Evals-18%2F18%20Passed-brightgreen)](EVAL_TABLE.md)
[![Tests](https://img.shields.io/badge/Tests-58%20Passed-success)](tests/)
[![Demo Video](https://img.shields.io/badge/Demo-Loom%20Video-blue)](https://www.loom.com/share/121adfbffadd4206adb4f091d447a62e)

Autonomous home-service chat agent that books, reschedules, and cancels errands against a mocked provider API — enforcing code-level approval gates, idempotency, prompt-injection containment, and cross-session memory.

---

## 🎥 Demo Video (Loom)

▶️ **Watch the Walkthrough**: **[https://www.loom.com/share/121adfbffadd4206adb4f091d447a62e](https://www.loom.com/share/121adfbffadd4206adb4f091d447a62e)**

### Video Walkthrough Highlights
1. **Introduction & LangGraph State Architecture**: Explicit state transitions, typed state schema, and interrupt gates (`interrupt_before=["execute_booking", ...]`).
2. **Happy-Path Booking & Code-Enforced Approval**: Selective slot gathering, slot holding, immutable approval record presentation, and verified execution.
3. **Live Failure Handling & Invariant Enforcement**:
   - **Prompt Injection Resistance**: Provider review containing `SYSTEM OVERRIDE` is sanitized and quarantined as passive data; code-level approval gate prevents autonomous execution.
   - **Timeout-After-Success Recovery**: Catching booking timeout, avoiding duplicate billing/booking, querying authoritative `get_booking_status`, and verifying state.
4. **Side-by-Side Trace Inspection**: Inspection of the committed JSONL trace ([`traces/trace-timeout-after-success-demo.jsonl`](traces/trace-timeout-after-success-demo.jsonl)) with timestamps, tool call parameters, and scrubbed secrets.

---

## 📑 Assignment Deliverables Quick Links

* 📖 **Design Note (Max 2 pages)**: [`DESIGN.md`](DESIGN.md) (Architecture, Code Gates, Recovery, Memory, 100× Scale Bottlenecks)
* 📊 **Automated Eval Table**: [`EVAL_TABLE.md`](EVAL_TABLE.md) (18/18 Scenarios Passed, dynamically generated)
* 🐛 **Three Real Bugs Encountered**: [`BUGS.md`](BUGS.md) (Root causes, architectural fixes, and regression tests)
* 📜 **Raw E2E Trace**: [`traces/trace-timeout-after-success-demo.jsonl`](traces/trace-timeout-after-success-demo.jsonl)
* 🎥 **Recorded Demo**: [Loom Video Walkthrough](https://www.loom.com/share/121adfbffadd4206adb4f091d447a62e)

---

## ⚡ Quick Start (3 Commands or Fewer)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the interactive chat agent
python -m errand_agent.cli

# 3. Run all automated evals (18 scenarios) & generate eval table
python tests/eval_report.py
```

To run unit tests via pytest:
```bash
pytest tests/ -v
```

---

## 📋 Architecture & Graded Must-Haves

1. **Explicit Workflow State**: Modeled as a LangGraph `StateGraph`. Asks *only* for missing information; corrections to one detail preserve all other gathered fields.
2. **Approval Enforced by Code**: `interrupt_before=["execute_booking", "execute_cancel", "execute_reschedule"]` halts execution. The code-level `ApprovalController` verifies exact match of provider, slot, and price before any action executes. Any change voids approval.
3. **Booking Correctness**: Idempotency keys prevent double-booking across repeated "yes" inputs. On booking timeouts, the agent queries authoritative `get_booking_status` before reporting. First cancellation attempt 503 is automatically retried.
4. **Untrusted Tool Output & JEV Guardrail**: Integrated with **TypeSafe AI's Jev** System One classifier (`JEVGuardrail`) to screen incoming prompts and untrusted tool outputs against jailbreak, instruction override, or persona manipulation attacks. Configured via `.env` (`JEV_API_KEY`).
5. **Bounded Execution**: Hard caps enforced by `ExecutionLimits` (max model turns, tool calls, and wall-clock time) with graceful degradation.
6. **Cross-Session Memory**: `MemoryManager` records facts with provenance (`user_stated` vs `agent_inferred`). Inferred facts require confirmation; forgotten facts are permanently tombstoned.
7. **Traces**: Every session records a JSONL trace in `traces/` tracking state transitions, model turns, tool calls, guardrail events, and scrubbed secrets.
8. **18 Automated Evals**: Deterministic offline test suite asserting invariants across all failure modes and requirements.

---

## 📁 Repository Structure

```
├── errand_agent/              # Core Agent package
│   ├── cli.py                 # Interactive terminal chat interface
│   ├── agent.py               # Orchestrator (LangGraph + approval + limits)
│   ├── graph.py               # LangGraph StateGraph with interrupt gates
│   ├── approval.py            # Code-enforced ApprovalController
│   ├── memory.py              # Cross-session memory with fact provenance
│   ├── jev_guardrail.py       # TypeSafe AI Jev guardrail for jailbreak defense
│   ├── sanitizer.py           # Untrusted tool output sanitizer
│   ├── tracer.py              # Structured JSONL trace recorder
│   ├── state.py               # Workflow state TypedDict schema
│   ├── models.py              # Pydantic domain models
│   └── nodes/                 # StateGraph workflow nodes (routing, search, inquiry, etc.)
├── mcp_server/                # Mock Provider API & FastMCP tool server
│   ├── server.py              # FastMCP server exposing 8 tools
│   ├── provider_api.py        # Mock implementation of all 8 tools
│   ├── tool_adapter.py        # LangChain tool bindings
│   ├── scenarios.py           # Configurable failure scenarios
│   └── data.py                # Seed providers & prompt-injection reviews
├── tests/                     # Test suite (44 unit & eval tests)
│   ├── test_evals.py          # 18 automated eval scenarios
│   ├── eval_report.py         # Markdown eval report generator
│   ├── test_conversational_resilience.py # Recovery & inquiry tests
│   ├── test_jev_guardrail.py  # JEV guardrail & jailbreak tests
│   ├── test_mock_api.py       # Unit tests for mock API
│   ├── test_security_and_approval.py  # Unit tests for approval & sanitizer
│   └── test_memory_and_tracer.py      # Unit tests for memory & tracer
├── traces/                    # Audit logs (e.g. trace-timeout-after-success-demo.jsonl)
├── DESIGN.md                  # 2-page design note & 100x scale analysis
├── BUGS.md                    # Real bugs encountered, root causes & fixes
├── EVAL_TABLE.md              # Dynamically generated 18-scenario eval table
└── requirements.txt           # Project dependencies
```
