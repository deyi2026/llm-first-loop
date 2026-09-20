"""Explicit P4-LIVE canary tool scope.

The exact surface is frozen from the qualified P4 shared perception/wait surface plus
the five G2-S4 typed ActionRef mutation facades. Ordinary runtime remains unscoped.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from llm_loop.core.run_context import current_tool_discovery_scope

P4_LIVE_CANARY_TOOL_SCOPE = frozenset(
    {
        "browser_perceive",
        "browser_wait_scope_url",
        "browser_wait_scope_ready",
        "browser_wait_scope_count",
        "browser_wait_object_state",
        "browser_wait_object_text",
        "get_tool_schema",
        "browser_semantic_click",
        "browser_semantic_fill",
        "browser_semantic_select",
        "browser_semantic_scroll",
        "browser_semantic_navigate",
    }
)


@contextmanager
def p4_live_canary_tool_scope() -> Iterator[frozenset[str]]:
    """Activate the exact P4-LIVE canary scope for the current context only."""
    token = current_tool_discovery_scope.set(P4_LIVE_CANARY_TOOL_SCOPE)
    try:
        yield P4_LIVE_CANARY_TOOL_SCOPE
    finally:
        current_tool_discovery_scope.reset(token)
