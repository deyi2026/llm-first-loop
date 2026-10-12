"""Durable mechanical SubAgent topology / execution-generation facts.

This module deliberately does not recover threads, Futures, mailboxes, settlement, task
semantics, or authorization.  EventStore is the append-only source of truth; callers may
rebuild a read-only topology index after restart and decide separately whether any future
reclaim mechanism is allowed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from llm_loop.event_log.model import (
    EVENT_SUBAGENT_GENERATION_RELEASED,
    EVENT_SUBAGENT_GENERATION_STARTED,
    EVENT_SUBAGENT_LINKED,
    EVENT_SUBAGENT_TERMINAL,
)


@dataclass(frozen=True)
class SubAgentTopologyState:
    child_id: str
    parent_id: str
    generation: str
    depth: int = 0
    owner_id: str = ""
    generation_started: bool = False
    generation_released: bool = False
    terminal: bool = False
    outcome: str = ""
    last_seq: int = 0


class SubAgentTopologyJournal:
    """Append/fold topology facts with generation fencing and no semantic judgment."""

    def __init__(self, event_store: Any | None) -> None:
        self.event_store = event_store

    def _enabled(self) -> bool:
        store = self.event_store
        return store is not None and bool(getattr(store, "enabled", False))

    def _append(self, child_id: str, event_type: str, payload: dict[str, object]) -> bool:
        store = self.event_store
        if not self._enabled():
            # EventStore-disabled test/legacy deployments keep historical behavior.
            return True
        assert store is not None
        return store.append(child_id, event_type, payload) is not None

    @staticmethod
    def fold(events: Iterable[Any], child_id: str) -> SubAgentTopologyState | None:
        state: SubAgentTopologyState | None = None
        for event in events:
            event_type = str(getattr(event, "type", "") or "")
            payload = dict(getattr(event, "payload", None) or {})
            event_child = str(payload.get("child_id") or child_id)
            if event_child != child_id:
                continue
            seq = int(getattr(event, "seq", 0) or 0)
            parent_id = str(payload.get("parent_id") or "")
            generation = str(payload.get("generation") or "")
            depth = int(payload.get("depth") or 0)

            if event_type == EVENT_SUBAGENT_LINKED:
                if not generation:
                    continue
                state = SubAgentTopologyState(
                    child_id=child_id,
                    parent_id=parent_id,
                    generation=generation,
                    depth=depth,
                    last_seq=seq,
                )
                continue

            if event_type == EVENT_SUBAGENT_GENERATION_STARTED:
                if not generation:
                    continue
                if state is None or generation != state.generation:
                    # A newer generation supersedes old terminal/release state.  This is
                    # fencing only; it does not authorize or trigger execution.
                    state = SubAgentTopologyState(
                        child_id=child_id,
                        parent_id=parent_id or (state.parent_id if state else ""),
                        generation=generation,
                        depth=depth if payload.get("depth") is not None else (state.depth if state else 0),
                        owner_id=str(payload.get("owner_id") or ""),
                        generation_started=True,
                        last_seq=seq,
                    )
                else:
                    state = SubAgentTopologyState(
                        child_id=state.child_id,
                        parent_id=parent_id or state.parent_id,
                        generation=state.generation,
                        depth=depth if payload.get("depth") is not None else state.depth,
                        owner_id=str(payload.get("owner_id") or state.owner_id),
                        generation_started=True,
                        generation_released=False,
                        terminal=False,
                        outcome="",
                        last_seq=seq,
                    )
                continue

            if state is None or not generation or generation != state.generation:
                # Late facts from an older generation are fenced out deterministically.
                continue

            if event_type == EVENT_SUBAGENT_GENERATION_RELEASED:
                owner_id = str(payload.get("owner_id") or "")
                if state.owner_id and owner_id and owner_id != state.owner_id:
                    continue
                state = SubAgentTopologyState(
                    child_id=state.child_id,
                    parent_id=state.parent_id,
                    generation=state.generation,
                    depth=state.depth,
                    owner_id=state.owner_id or owner_id,
                    generation_started=state.generation_started,
                    generation_released=True,
                    terminal=state.terminal,
                    outcome=state.outcome,
                    last_seq=seq,
                )
                continue

            if event_type == EVENT_SUBAGENT_TERMINAL:
                state = SubAgentTopologyState(
                    child_id=state.child_id,
                    parent_id=state.parent_id,
                    generation=state.generation,
                    depth=state.depth,
                    owner_id=state.owner_id,
                    generation_started=state.generation_started,
                    generation_released=state.generation_released,
                    terminal=True,
                    outcome=str(payload.get("outcome") or "failed"),
                    last_seq=seq,
                )

        return state

    def recover(self, child_id: str) -> SubAgentTopologyState | None:
        store = self.event_store
        if not self._enabled() or store is None or not store.exists(child_id):
            return None
        return self.fold(store.read(child_id) or [], child_id)

    def linked(self, *, child_id: str, parent_id: str, generation: str, depth: int) -> bool:
        current = self.recover(child_id)
        if (
            current is not None
            and current.generation == generation
            and current.parent_id == parent_id
        ):
            return True
        return self._append(
            child_id,
            EVENT_SUBAGENT_LINKED,
            {
                "child_id": child_id,
                "parent_id": parent_id,
                "generation": generation,
                "depth": int(depth),
            },
        )

    def generation_started(
        self,
        *,
        child_id: str,
        parent_id: str,
        generation: str,
        owner_id: str,
        depth: int,
    ) -> bool:
        current = self.recover(child_id)
        if current is not None and current.generation == generation and current.generation_started:
            if current.terminal:
                return False
            return not current.owner_id or current.owner_id == owner_id
        return self._append(
            child_id,
            EVENT_SUBAGENT_GENERATION_STARTED,
            {
                "child_id": child_id,
                "parent_id": parent_id,
                "generation": generation,
                "owner_id": owner_id,
                "depth": int(depth),
            },
        )

    def generation_released(
        self,
        *,
        child_id: str,
        parent_id: str,
        generation: str,
        owner_id: str,
        depth: int,
        reason: str,
    ) -> bool:
        current = self.recover(child_id)
        if current is not None:
            if current.generation != generation:
                return False
            if current.owner_id and current.owner_id != owner_id:
                return False
            if current.generation_released:
                return True
        return self._append(
            child_id,
            EVENT_SUBAGENT_GENERATION_RELEASED,
            {
                "child_id": child_id,
                "parent_id": parent_id,
                "generation": generation,
                "owner_id": owner_id,
                "depth": int(depth),
                "reason": str(reason or "worker_exit"),
            },
        )

    def terminal(
        self,
        *,
        child_id: str,
        parent_id: str,
        generation: str,
        depth: int,
        outcome: str,
    ) -> bool:
        current = self.recover(child_id)
        if current is not None:
            if current.generation != generation:
                return False
            if current.terminal:
                return current.outcome == str(outcome or "failed")
        return self._append(
            child_id,
            EVENT_SUBAGENT_TERMINAL,
            {
                "child_id": child_id,
                "parent_id": parent_id,
                "generation": generation,
                "depth": int(depth),
                "outcome": str(outcome or "failed"),
            },
        )
