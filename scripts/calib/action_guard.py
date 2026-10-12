"""Experimental Action-Plane tool-loop guards for A3.

Pure mechanism layer: it knows tool identity/arguments and action budget only.
It does NOT know benchmark oracles, decision relevance, or expected sources.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

DUPLICATE_SUPPRESSED = "DUPLICATE_SUPPRESSED"
TOOL_BUDGET_EXHAUSTED = "TOOL_BUDGET_EXHAUSTED"


@dataclass(frozen=True)
class GuardConfig:
    duplicate_suppression: bool = False
    budget_terminal: bool = False


@dataclass
class GuardState:
    tool_attempt_count: int = 0
    tool_execution_count: int = 0
    duplicate_suppressed_count: int = 0
    budget_blocked_count: int = 0
    limit_exceeded_count: int = 0
    tool_budget_exhausted: bool = False
    result_cache: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GuardOutcome:
    content: str
    disposition: str
    executed: bool
    channel_closed: bool


def canonical_fingerprint(tool_name: str, args: dict) -> str:
    return f"{tool_name}:{json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"


def visible_tools(base_tools: list[dict], state: GuardState, config: GuardConfig) -> list[dict]:
    """A terminal budget closes the action channel on subsequent LLM rounds."""
    if config.budget_terminal and state.tool_budget_exhausted:
        return []
    return base_tools


def handle_request_fixture(
    *,
    source: str,
    args: dict,
    state: GuardState,
    config: GuardConfig,
    source_limit: int,
    lookup: Callable[[str], str | None],
    unavailable_response: str,
    limit_exceeded_response: str,
) -> GuardOutcome:
    """Process one model-emitted request_fixture attempt.

    attempt_count always records model behavior. execution_count records actual
    source lookups only. Duplicate/budget suppression never pretends the model
    did not attempt the action.
    """
    state.tool_attempt_count += 1
    fp = canonical_fingerprint("request_fixture", args)

    # If the channel has already been terminally closed, block even if the same
    # response contains additional batched tool calls.
    if config.budget_terminal and state.tool_budget_exhausted:
        state.budget_blocked_count += 1
        return GuardOutcome(
            content=(
                f"{TOOL_BUDGET_EXHAUSTED}: request_fixture action channel is closed. "
                "Use evidence already obtained and produce the Final Decision."
            ),
            disposition="budget_blocked",
            executed=False,
            channel_closed=True,
        )

    # Duplicate suppression is checked before the legacy budget response so a
    # repeated deterministic call can reuse evidence without consuming another
    # external execution slot.
    if config.duplicate_suppression and fp in state.result_cache:
        state.duplicate_suppressed_count += 1
        previous = state.result_cache[fp]
        return GuardOutcome(
            content=(
                f"{DUPLICATE_SUPPRESSED}: identical deterministic call already succeeded; "
                "reuse_previous_result=true\nPREVIOUS_RESULT:\n" + previous
            ),
            disposition="duplicate_suppressed",
            executed=False,
            channel_closed=False,
        )

    if state.tool_execution_count >= source_limit:
        state.limit_exceeded_count += 1
        if config.budget_terminal:
            state.tool_budget_exhausted = True
            state.budget_blocked_count += 1
            return GuardOutcome(
                content=(
                    f"{TOOL_BUDGET_EXHAUSTED}: request_fixture execution budget exhausted. "
                    "Use evidence already obtained and produce the Final Decision."
                ),
                disposition="budget_blocked",
                executed=False,
                channel_closed=True,
            )
        return GuardOutcome(
            content=limit_exceeded_response,
            disposition="limit_exceeded",
            executed=False,
            channel_closed=False,
        )

    content = lookup(source) or unavailable_response
    state.tool_execution_count += 1
    # Cache deterministic successful/available results only. Unavailable results
    # are not treated as evidence worth reusing.
    if content not in {unavailable_response, limit_exceeded_response}:
        state.result_cache[fp] = content

    if config.budget_terminal and state.tool_execution_count >= source_limit:
        state.tool_budget_exhausted = True
        content = (
            content
            + "\n\nACTION_STATE: tool_budget_exhausted=true; "
            "request_fixture action channel is closed after this result. "
            "Continue reasoning from evidence already obtained and finish the decision."
        )

    return GuardOutcome(
        content=content,
        disposition="executed",
        executed=True,
        channel_closed=config.budget_terminal and state.tool_budget_exhausted,
    )
