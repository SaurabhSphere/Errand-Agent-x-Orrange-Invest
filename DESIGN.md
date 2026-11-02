# Errand Agent — Technical Design Note

## 1. State Model & Workflow Architecture

The Errand Agent is modeled as a compiled **LangGraph `StateGraph`** with explicit workflow states (`idle`, `gathering_info`, `searching`, `presenting_options`, `holding_slot`, `awaiting_approval`, `booking`, `verifying`, `confirmed`, `error`). 

```
[START] ──> [route_intent] ──> [gather_info] ──> [search_providers] ──> [present_options]
                                                                                │
                                                                         [hold_slot]
                                                                                │
                                                                        [await_approval]
                                                                                │ (interrupt_before)
                                                                       [execute_booking]
                                                                         /          \
                                                             (success)  /            \ (timeout)
                                                                       ▼              ▼
                                                                    [CONFIRMED]    [verify_booking]
```

* **Selective slot gathering**: The `gather_info` node asks *only* for missing information (service, area, date range, budget). Slot updates modify only the specific field, keeping all other gathered details intact.
* **Checkpoint persistence**: The graph is compiled with a state checkpointer (`SqliteSaver` in production / `MemorySaver` in testing). State snapshots are saved after every transition, enabling zero-data-loss resumption after crashes or restarts.

---

## 2. Approval Enforcement (Code-Level)

Approval is **never inferred from model output or conversational pleasantries**. It is governed by a dedicated `ApprovalController` and verified via a code gate:

1. **Gate Placement**: The graph registers `interrupt_before=["execute_booking", "execute_cancel", "execute_reschedule"]`. Execution physically pauses before any mutating tool call can occur.
2. **Explicit Record**: An immutable `ApprovalRecord(action, provider_id, slot, price)` is presented to the user.
3. **Strict Validation**: Before calling the backend, `validate_for_action()` asserts that:
   - User provided affirmative confirmation (`"yes"`, `"confirm"`).
   - The execution payload exactly matches the approved `provider_id`, `slot`, and `price`.
4. **Automatic Voiding**: Any change to provider, slot, or price (such as hold-time price drift) immediately voids the approval record with an `ApprovalVoidedError`, requiring re-approval.

---

## 3. Idempotency & Failure Recovery

The agent enforces strict booking correctness against unreliable backends:

* **Client Idempotency Keys**: Every mutation generates a deterministic key (e.g. `book-{hold_id}-{uuid}`). Repeated confirmations or duplicate retries pass the identical key, ensuring the provider returns the cached result without duplicate billing or booking.
* **Timeout-After-Success Recovery**: When `book()` returns a network timeout, the agent **never retries blindly** and **never reports failure prematurely**. It transitions to `verify_booking`, querying `get_booking_status(idempotency_key)`. If the authoritative ledger confirms `booked`, the agent reports verified success.
* **Transient 503 Retry**: On cancellation, transient 503 errors trigger exponential retry with the same idempotency key, succeeding on subsequent attempts.

---

## 4. Cross-Session Memory & Fact Provenance

User preferences (area, earliest time, preferred technician) are managed by `MemoryManager`:

* **Fact Provenance**: Facts are tagged with `source="user_stated"` (usable directly) or `source="agent_inferred"` (flagged as `[AGENT INFERRED - MUST CONFIRM BEFORE USING]`).
* **Forget Semantics & Tombstones**: When a user forgets a preference, a permanent tombstone is recorded. Even if the agent later infers the same preference from booking patterns, the tombstone prevents reuse unless the user explicitly re-states it.

---

## 5. Observability & Annotated Timeout-After-Success Trace

Every run outputs a structured, non-secret JSONL trace recording state transitions, model turns, and tool calls.

### Annotated Excerpt: Timeout-After-Success Run (`traces/trace-timeout-after-success-demo.jsonl`)

```jsonl
// 1. User selects provider option 1; 10-minute hold placed
{"event": "tool_call", "tool": "hold_slot", "args": {"provider_id": "plumber-rajesh-01", "slot": "2026-11-02T09:00"}, "result": "{'hold_id': 'HOLD-5BFC1C1E', 'quoted_price': 1200}"}

// 2. User confirms with "yes"; code approval gate validates exact action, provider, slot, and price
{"event": "approval_granted", "user_input": "yes"}
{"event": "approval_gate", "action": "book", "provider_id": "plumber-rajesh-01", "slot": "2026-11-02T09:00", "price": 1200, "status": "PASSED"}

// 3. book() tool executed with idempotency key; call times out
{"event": "tool_call", "tool": "book", "args": {"hold_id": "HOLD-5BFC1C1E", "idempotency_key": "book-HOLD-5BFC1C1E-851f36c4"}, "result": "{'status': 'timeout', 'error': 'Connection timed out'}"}

// 4. Agent intercepts timeout, calls get_booking_status; confirms booking was actually created!
{"event": "tool_call", "tool": "get_booking_status", "args": {"idempotency_key": "book-HOLD-5BFC1C1E-851f36c4"}, "result": "{'status': 'booked', 'booking_id': 'BK-7E897E'}"}
```

---

## 6. What Breaks First at 100× Scale & Recommended Changes

1. **State Checkpointing & Concurrency**:
   * *Break point*: SQLite single-writer lock contention when handling hundreds of concurrent users.
   * *Change*: Upgrade checkpointer from `SqliteSaver` to `PostgresSaver` with distributed connection pooling and row-level locking on `thread_id`.
2. **Provider Inventory Contention & Hold Race Conditions**:
   * *Break point*: Popular slots will experience high hold contention; distributed holds will expire while users deliberate approval.
   * *Change*: Implement distributed Redis key-expiry leases and dynamic hold TTLs with WebSocket real-time expiry countdowns pushed to the client.
3. **Idempotency Store Scalability**:
   * *Break point*: Storing idempotency payloads in provider process memory will exhaust RAM and fail across horizontally scaled provider pods.
   * *Change*: Persist idempotency records in a shared Redis / DynamoDB store with a 72-hour TTL.
