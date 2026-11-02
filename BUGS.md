# Three Real Bugs Hit While Building

This document details three real bugs encountered during implementation, their root cause analysis, the fix applied, and the regression tests now guarding them.

---

### Bug 1: LangGraph `interrupt_before` Silent Bypass Due to Missing Inter-Node Edge

* **What broke**:
  During multi-turn execution, after the agent presented approval details to the user and the user replied `"yes"`, the agent did not execute the booking. Instead, it re-ran `search_providers` and re-prompted the user with provider options from scratch.
* **Why**:
  In LangGraph, compile-time `interrupt_before=["execute_booking"]` only halts graph execution if an active edge transitions into `execute_booking`. In the initial graph definition, `await_approval` had an unconditional terminal edge `builder.add_edge("await_approval", END)`. Because `await_approval` routed directly to `END`, the execution cycle completed immediately without queuing `execute_booking`. When the user subsequent sent `"yes"`, `state.next` was empty `()`. The agent treated `"yes"` as a brand-new turn starting at `START`, defaulting back to search intent.
* **The fix**:
  Replaced the terminal edge from `await_approval` with a conditional routing function `route_after_approval(state)` that explicitly inspects `state["current_action"]` and routes to `"execute_booking"`, `"execute_cancel"`, or `"execute_reschedule"`. This allowed LangGraph's checkpointer to serialize the graph state and trigger the `interrupt_before` pause cleanly.
* **Regression test**:
  `tests/test_evals.py::test_scenario_01_happy_path_booking` and `tests/test_evals.py::test_scenario_13_restart_mid_booking`.

---

### Bug 2: Premature Code-Level Approval Verification in Evaluation Scenario

* **What broke**:
  In `test_scenario_03_price_change_voids_approval`, the test asserted that an altered price threw `ApprovalVoidedError`, but the code instead raised `ApprovalRequiredError`, causing test failure.
* **Why**:
  `ApprovalController.validate_for_action()` performs checks in priority order:
  1. Is there an active approval record?
  2. Has the user confirmed it (`record.approved is True`)?
  3. Does the execution payload match the approved price, slot, and provider?
  In the scenario, `agent.step("Option 1")` was called, which staged the approval request, but `agent.step("yes")` had not yet been submitted. Calling `validate_for_action()` directly failed at step 2 (`ApprovalRequiredError`) before reaching the price-drift validation at step 3 (`ApprovalVoidedError`).
* **The fix**:
  In the test, submitted the user's affirmative confirmation (`await agent.step("yes")`) before asserting that backend price changes or mismatched execution payloads trigger `ApprovalVoidedError`. Also verified that `price_drift_note` was communicated to the user.
* **Regression test**:
  `tests/test_evals.py::test_scenario_03_price_change_voids_approval`.

---

### Bug 3: Standalone Execution Failure in Eval Report Script Due to Missing Module Path

* **What broke**:
  Running `python tests/eval_report.py` as a standalone script failed immediately with `ModuleNotFoundError: No module named 'mcp_server'`.
* **Why**:
  When Python executes a script directly (e.g. `python tests/eval_report.py`), `sys.path[0]` is initialized to the script's directory (`D:\Assignment\tests`), not the project root (`D:\Assignment`). Consequently, absolute imports referencing `mcp_server` and `errand_agent` could not be resolved unless run with `python -m tests.eval_report`.
* **The fix**:
  Added explicit path injection at the top of `tests/eval_report.py`:
  ```python
  import os, sys
  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
  ```
  This guarantees that running `python tests/eval_report.py` directly executes without dependency or import errors.
* **Regression test**:
  Verified by executing `python tests/eval_report.py` directly in the shell.
