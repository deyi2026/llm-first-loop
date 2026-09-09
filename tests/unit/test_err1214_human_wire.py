"""Regression coverage for GLM 1214 after provider history compaction.

The invariant is provider-mechanical: while a genuine human turn is active, history
compaction may retire old atomic tool groups but must not retire that turn's exact
human ingress.  Otherwise an otherwise well-paired tool trajectory can become
``system -> assistant -> tool`` with no user message, which GLM rejects as 1214.
"""

from __future__ import annotations

from types import SimpleNamespace

from llm_loop.core.history import build_history_messages, validate_tool_call_pairing
from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.core.prompt_build.stages.history_projection import run_history_projection


class _CacheMonitor:
    force_head_keep = False

    @staticmethod
    def breaker_freeze_compression(_session_id: str) -> bool:
        return False


def _tool_group(index: int) -> list[Message]:
    call_id = f"call-{index}"
    return [
        Message(
            role="assistant",
            content="",
            source=MessageSource.USER,
            tool_calls=[
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        ),
        Message(
            role="tool",
            content="R" * 350,
            source=MessageSource.TOOL,
            tool_call_id=call_id,
            tool_name="read_file",
            status=ToolResultStatus.SUCCESS,
        ),
    ]


def test_tool_followup_compaction_keeps_current_human_and_still_makes_progress() -> None:
    """A long current-turn tool chain must compact around, never through, its human ingress."""
    current = Message(
        role="user",
        content="CURRENT-HUMAN",
        source=MessageSource.USER,
    )
    # Real failures happen after eligibility has retired historical human turns.
    # A stable assistant head can remain, making the current ingress the *only*
    # provider-visible user. Compaction must not turn this into a zero-user wire.
    base = [
        Message(role="assistant", content="H" * 170, source=MessageSource.USER),
        current,
    ]
    for index in range(6):
        base.extend(_tool_group(index))

    archived: list[Message] = []
    projection = run_history_projection(
        base=base,
        system_prompt="SYS",
        filtered_indices=list(range(len(base))),
        sess_anchor=0,
        prefix_len=0,
        session_id="err1214-followup",
        max_chars=1_200,
        runtime_history_budget_value=1_200,
        compact_ratio=0.85,
        archive_sink=lambda _sid, message: archived.append(message),
        settings=SimpleNamespace(exact_duplicate_tool_fold=False),
        provider_id="glm",
        resolved_label="glm/glm-5.3",
        reasoning_tail=0,
        r6_ingress_truth=None,  # reproduces a tool-followup round, not initial ingress
        registry=SimpleNamespace(evidence_mode="off"),
        cache_monitor=_CacheMonitor(),
        effective_budget=1_200,
        current_turn_ref=1,
    )

    assert any(
        item.get("role") == "user" and item.get("content") == "CURRENT-HUMAN"
        for item in projection.built
    ), "active human ingress must remain provider-visible after compaction"
    assert all(message is not current for message in archived)
    assert archived, "preserving the human must not disable mechanical tool compaction"
    assert sum(item.get("role") == "user" for item in projection.built) == 1
    assert validate_tool_call_pairing(projection.built) == []


def test_bad_marker_and_advanced_anchor_cannot_hide_active_human_on_retry() -> None:
    """A failed old compaction state is mechanically reopened around the active human."""
    current = Message(role="user", content="CURRENT-HUMAN", source=MessageSource.USER)
    base = [
        Message(role="assistant", content="H" * 170, source=MessageSource.USER),
        current,
    ]
    for index in range(6):
        base.extend(_tool_group(index))

    # Recreate the pre-fix bad state deliberately: no active-human protection, no
    # fixed head, so the provider compactor marks the current user and advances the
    # contiguous anchor beyond it.
    bad_archived: list[Message] = []
    bad_anchor: list[int] = []
    build_history_messages(
        base,
        "SYS",
        max_chars=1_200,
        compact_ratio=0.85,
        session_id="err1214-bad-state",
        archive_sink=lambda _sid, message: bad_archived.append(message),
        history_anchor=0,
        anchor_out=bad_anchor,
        head_keep_chars=0,
        cache_archive_provider="glm",
        cache_archive_model="glm/glm-5.3",
        cache_archive_budget=1_200,
        preserve_last_human_exact=False,
        current_turn_ref=1,
    )
    assert current in bad_archived
    assert bad_anchor and bad_anchor[0] > 1

    retried_archived: list[Message] = []
    projection = run_history_projection(
        base=base,
        system_prompt="SYS",
        filtered_indices=list(range(len(base))),
        sess_anchor=bad_anchor[0],
        prefix_len=0,
        session_id="err1214-retry",
        max_chars=1_200,
        runtime_history_budget_value=1_200,
        compact_ratio=0.85,
        archive_sink=lambda _sid, message: retried_archived.append(message),
        settings=SimpleNamespace(exact_duplicate_tool_fold=False),
        provider_id="glm",
        resolved_label="glm/glm-5.3",
        reasoning_tail=0,
        r6_ingress_truth=None,
        registry=SimpleNamespace(evidence_mode="off"),
        cache_monitor=_CacheMonitor(),
        effective_budget=1_200,
        current_turn_ref=1,
    )

    assert any(
        item.get("role") == "user" and item.get("content") == "CURRENT-HUMAN"
        for item in projection.built
    )
    assert all(message is not current for message in retried_archived)
    assert sum(item.get("role") == "user" for item in projection.built) == 1
    assert validate_tool_call_pairing(projection.built) == []


def test_head_downgrade_cannot_archive_active_human() -> None:
    """The 95% fixed-head fallback may retire head peers, never the active human itself."""
    current = Message(role="user", content="CURRENT-HUMAN", source=MessageSource.USER)
    base = [current]
    for index in range(8):
        base.extend(_tool_group(index))

    archived: list[Message] = []
    built = build_history_messages(
        base,
        "SYS",
        max_chars=1_200,
        compact_ratio=0.85,
        session_id="err1214-head-downgrade",
        archive_sink=lambda _sid, message: archived.append(message),
        head_keep_chars=600,
        head_keep_target_ratio=0.9,
        cache_archive_provider="glm",
        cache_archive_model="glm/glm-5.3",
        cache_archive_budget=1_200,
        preserve_human_message=current,
        current_turn_ref=0,
    )

    assert any(
        item.get("role") == "user" and item.get("content") == "CURRENT-HUMAN" for item in built
    )
    assert all(message is not current for message in archived)
    assert archived, "head downgrade should still retire other atomic groups"
    assert validate_tool_call_pairing(built) == []
