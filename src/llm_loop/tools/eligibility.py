"""Runtime tool-health facts.

P1-B (2026-09-04) retired the R8.7 semantic selection plane. Registered tools are
provider-callable by default; the runtime may remove only tools that are mechanically
unavailable in the current environment. User/task keywords, protocol history, recovery
hints, promotion state, and capability requirements never decide tool visibility here.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

_QUARANTINE_REPLACEMENTS: dict[str, tuple[str, ...]] = {
    "playwright_exec": ("web_fetch", "web_search", "skill_load:web-fetch-fast"),
    "playwright_test": ("execute_command",),
}


@dataclass(frozen=True)
class ToolHealth:
    """Cheap mechanical availability fact for one registered tool."""

    state: str
    reason_code: str = ""
    preferred_next: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.state != "quarantined"


def runtime_tool_health(name: str) -> ToolHealth:
    """Return cheap runtime health without executing the tool or judging task strategy."""
    if name in {"playwright_exec", "playwright_test"}:
        try:
            available = importlib.util.find_spec("playwright") is not None
        except (ImportError, AttributeError, ValueError):
            available = False
        if not available:
            return ToolHealth(
                state="quarantined",
                reason_code="playwright_python_dependency_missing",
                preferred_next=_QUARANTINE_REPLACEMENTS.get(name, ()),
            )
    return ToolHealth(state="ready")
