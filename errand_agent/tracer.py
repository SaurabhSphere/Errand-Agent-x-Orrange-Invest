"""Structured trace recorder for auditability, observability, and debugging."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
import uuid


class Tracer:
    """Records one structured JSONL trace file per execution run.

    Tracks:
    - State transitions
    - Model calls (with token counts, latency, cost)
    - Tool calls (name, args, sanitized result, latency)
    - Code-level approval checks & gates
    - Scrubbing of secrets (API keys, authorization headers)
    """

    SECRET_PATTERNS = [
        re.compile(r"sk-[a-zA-Z0-9_-]{20,}", re.IGNORECASE),
        re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE),
        re.compile(r"api[_-]?key['\"]\s*:\s*['\"][^'\"]+['\"]", re.IGNORECASE),
    ]

    def __init__(self, run_id: str | None = None, trace_dir: str = "traces"):
        self.run_id = run_id or f"run-{uuid.uuid4().hex[:10]}"
        self.trace_dir = Path(trace_dir)
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.trace_file = self.trace_dir / f"trace-{self.run_id}.jsonl"
        self.entries: list[dict[str, Any]] = []

    def _scrub_secrets(self, text: str) -> str:
        """Mask out potential secrets and API keys."""
        if not isinstance(text, str):
            return text
        scrubbed = text
        for p in self.SECRET_PATTERNS:
            scrubbed = p.sub("[REDACTED_SECRET]", scrubbed)
        return scrubbed

    def record(self, event_type: str, **kwargs: Any) -> dict[str, Any]:
        """Record a structured event into the trace file and in-memory list."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "event": event_type,
            **kwargs,
        }

        # Convert entry to scrubbed JSON string
        raw_json = json.dumps(entry, default=str)
        clean_json = self._scrub_secrets(raw_json)
        clean_entry = json.loads(clean_json)

        self.entries.append(clean_entry)
        try:
            with open(self.trace_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(clean_entry) + "\n")
        except Exception:
            pass  # Non-fatal if disk write fails during testing

        return clean_entry

    def record_state_transition(
        self,
        from_state: str,
        to_state: str,
        reason: str | None = None,
    ) -> None:
        self.record(
            "state_transition",
            from_state=from_state,
            to_state=to_state,
            reason=reason,
        )

    def record_tool_call(
        self,
        tool: str,
        args: dict[str, Any],
        result: Any,
        latency_ms: float = 0.0,
    ) -> None:
        # Truncate large result payloads to keep traces readable and performant
        sanitized_res = str(result)
        if len(sanitized_res) > 1000:
            sanitized_res = sanitized_res[:1000] + "... [TRUNCATED]"

        self.record(
            "tool_call",
            tool=tool,
            args=args,
            result=sanitized_res,
            latency_ms=round(latency_ms, 2),
        )

    def record_model_call(
        self,
        model_name: str,
        prompt_preview: str,
        response_preview: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        self.record(
            "model_call",
            model=model_name,
            prompt_preview=prompt_preview[:300],
            response_preview=response_preview[:300],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=round(latency_ms, 2),
            estimated_cost_usd=round(estimated_cost_usd, 6),
        )

    def record_approval_gate(
        self,
        action: str,
        provider_id: str,
        slot: str,
        price: int,
        status: str,
        reason: str | None = None,
    ) -> None:
        self.record(
            "approval_gate",
            action=action,
            provider_id=provider_id,
            slot=slot,
            price=price,
            status=status,
            reason=reason,
        )
