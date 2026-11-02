"""Cross-session memory manager with fact provenance and forget semantics."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
from errand_agent.models import MemoryFact, MemorySource


class MemoryManager:
    """Manages persistent cross-session preferences for users.

    Must-Have 6 Requirements:
    - Persist stable preferences across sessions (area, earliest time, preferred technician).
    - Users can view, correct, and forget them.
    - Mark each fact as stated by user ('user_stated') or inferred by agent ('agent_inferred').
    - Inferred facts are never used without confirmation.
    - Forgotten facts are NEVER reused.
    """

    def __init__(self, storage_path: str = "data/memory.json"):
        self.storage_path = Path(storage_path)
        # In-memory dictionary: user_id -> dict of key -> MemoryFact
        self._store: dict[str, dict[str, MemoryFact]] = {}
        # Tombstones: user_id -> set of forgotten keys (to permanently guarantee non-reuse)
        self._tombstones: dict[str, set[str]] = {}
        self._load()

    def _load(self) -> None:
        """Load persistent memory from disk if available."""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            for user_id, user_facts in raw_data.items():
                self._store[user_id] = {}
                self._tombstones.setdefault(user_id, set())
                for k, v in user_facts.items():
                    fact = MemoryFact(**v)
                    self._store[user_id][k] = fact
                    if fact.forgotten:
                        self._tombstones[user_id].add(k)
        except Exception:
            # Fall back to empty store if unreadable
            self._store = {}
            self._tombstones = {}

    def _save(self) -> None:
        """Persist state to disk."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {
            user_id: {k: f.model_dump(mode="json") for k, f in facts.items()}
            for user_id, facts in self._store.items()
        }
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)

    def remember(
        self,
        user_id: str,
        key: str,
        value: str,
        source: MemorySource | str = MemorySource.USER_STATED,
    ) -> MemoryFact | None:
        """Store a preference fact.

        If the fact was previously forgotten by the user, it will NOT be remembered
        if inferred by the agent. If explicitly re-stated by the user, the tombstone is cleared.
        """
        if isinstance(source, str):
            source = MemorySource(source)

        user_tombstones = self._tombstones.setdefault(user_id, set())

        # Forgotten facts are NEVER reused via agent inference
        if key in user_tombstones and source == MemorySource.AGENT_INFERRED:
            return None

        # If user explicitly states it again, revive it
        if key in user_tombstones and source == MemorySource.USER_STATED:
            user_tombstones.remove(key)

        fact = MemoryFact(
            key=key,
            value=value,
            source=source,
            created_at=datetime.now(timezone.utc),
            forgotten=False,
            forgotten_at=None,
        )

        user_facts = self._store.setdefault(user_id, {})
        user_facts[key] = fact
        self._save()
        return fact

    def recall(self, user_id: str, key: str) -> MemoryFact | None:
        """Recall a fact only if it exists and has not been forgotten."""
        user_facts = self._store.get(user_id, {})
        fact = user_facts.get(key)
        if fact and not fact.forgotten:
            return fact
        return None

    def forget(self, user_id: str, key: str) -> bool:
        """Mark a fact as forgotten.

        Forgotten facts are never reused.
        """
        user_facts = self._store.setdefault(user_id, {})
        user_tombstones = self._tombstones.setdefault(user_id, set())

        user_tombstones.add(key)
        fact = user_facts.get(key)
        if fact:
            fact.forgotten = True
            fact.forgotten_at = datetime.now(timezone.utc)
            self._save()
            return True
        else:
            # Record tombstone even if key was not actively stored
            self._save()
            return True

    def correct(self, user_id: str, key: str, new_value: str) -> MemoryFact:
        """User corrects a previously known or inferred fact."""
        return self.remember(
            user_id=user_id,
            key=key,
            value=new_value,
            source=MemorySource.USER_STATED,
        )

    def view_all(self, user_id: str) -> list[dict[str, Any]]:
        """Return all active (non-forgotten) facts with metadata for display."""
        user_facts = self._store.get(user_id, {})
        active = []
        for f in user_facts.values():
            if not f.forgotten:
                active.append({
                    "key": f.key,
                    "value": f.value,
                    "source": f.source.value,
                    "created_at": f.created_at.isoformat(),
                })
        return active

    def get_context_for_prompt(self, user_id: str) -> str:
        """Generate a concise context string for the agent.

        Differentiates between user_stated (usable directly) and agent_inferred
        (MUST be confirmed before usage).
        """
        facts = self.view_all(user_id)
        if not facts:
            return "No prior user preferences on file."

        lines = ["Known User Preferences from Memory:"]
        for f in facts:
            if f["source"] == MemorySource.USER_STATED.value:
                lines.append(f"- [CONFIRMED / USER STATED] {f['key']}: {f['value']}")
            else:
                lines.append(
                    f"- [AGENT INFERRED - MUST CONFIRM BEFORE USING] {f['key']}: {f['value']}"
                )
        return "\n".join(lines)
