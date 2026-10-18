"""Mechanical Method read/use observations for optional settlement telemetry.

Reading a method never injects a reminder or delays the final answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MethodUseLedger:
    """Method refs exactly hydrated vs. refs with a record_use this run."""

    hydrated: tuple[str, ...]
    recorded: tuple[str, ...]

    def unrecorded(self) -> tuple[str, ...]:
        seen: list[str] = []
        for ref in self.hydrated:
            if ref not in self.recorded and ref not in seen:
                seen.append(ref)
        return tuple(seen)


def scan_method_use_ledger(tool_trace: list[Any]) -> MethodUseLedger:
    """Derive hydrated vs. recorded method refs from this run's tool trace."""
    hydrated: list[str] = []
    recorded: list[str] = []
    for row in tool_trace or []:
        try:
            if isinstance(row, dict):
                name = str(row.get("name", "") or "")
                arguments = row.get("arguments") or {}
                status = str(row.get("status", "success") or "")
            else:
                name = str(getattr(row, "name", "") or "")
                arguments = getattr(row, "arguments", None) or {}
                status = str(getattr(row, "status", "success") or "")
            if status != "success":
                continue
            if name == "search_records":
                if str(arguments.get("kind", "")) != "method":
                    continue
                query = str(arguments.get("query", "") or "").strip()
                if query.startswith("method:"):
                    hydrated.append(query)
            elif name == "method_manage":
                if str(arguments.get("action", "")) != "record_use":
                    continue
                ref = str(arguments.get("method_ref", "") or "").strip()
                if ref:
                    recorded.append(ref)
        except Exception:
            continue
    return MethodUseLedger(hydrated=tuple(hydrated), recorded=tuple(recorded))
