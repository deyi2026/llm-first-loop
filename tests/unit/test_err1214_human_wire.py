"""Regression coverage for GLM 1214 after provider history compaction.

The invariant is provider-mechanical: while a genuine human turn is active, history
compaction may retire old atomic tool groups but must not retire that turn's exact
human ingress.  Otherwise an otherwise well-paired tool trajectory can become
``system -> assistant -> tool`` with no user message, which GLM rejects as 1214.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from llm_loop.core.history import (
    build_conservative_active_run_projection,
    build_history_messages,
    validate_tool_call_pairing,
)
from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.core.prompt_build.stages.history_projection import run_history_projection
from llm_loop.core.reference_injection import (
    is_active_run_ingress_message,
    is_human_user_message,
)
from llm_loop.llm.client import GuardRequestContext, LLMClient
from llm_loop.llm.errors import LLMProjectionError

_INCIDENT_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "err1214_delegated_compaction_v1.json"
)


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


def _incident_fixture_messages() -> tuple[dict, list[Message], Message]:
    fixture = json.loads(_INCIDENT_FIXTURE.read_text(encoding="utf-8"))
    ingress_spec = fixture["ingress"]
    ingress_seq = int(ingress_spec["msg_seq"])
    messages: list[Message] = []
    active_calls: list[str] = []
    ingress_message: Message | None = None
    for row in fixture["archived_span"]:
        role = str(row["role"])
        seq = int(row["msg_seq"])
        content = ("U" if role == "user" else "R") * int(row["content_chars"])
        if role == "user":
            metadata = dict(ingress_spec["metadata"]) if seq == ingress_seq else {}
            message = Message(
                role="user", content=content, source=MessageSource.USER, metadata=metadata
            )
            if seq == ingress_seq:
                ingress_message = message
            messages.append(message)
            active_calls = []
            continue
        if role == "assistant":
            count = int(row.get("tool_call_count", 0))
            active_calls = [f"fixture-{seq}-{ordinal}" for ordinal in range(count)]
            messages.append(
                Message(
                    role="assistant",
                    content=content,
                    source=MessageSource.USER,
                    tool_calls=[
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                        for call_id in active_calls
                    ],
                )
            )
            continue
        ordinal = int(row["tool_result_ordinal"])
        call_id = active_calls[ordinal]
        messages.append(
            Message(
                role="tool",
                content=content,
                source=MessageSource.TOOL,
                tool_call_id=call_id,
                tool_name="read_file",
                status=ToolResultStatus.SUCCESS,
            )
        )
    assert ingress_message is not None
    return fixture, messages, ingress_message


def test_active_run_ingress_provenance_does_not_relabel_delegated_as_human() -> None:
    delegated = Message(
        role="user",
        content="CONTINUE",
        source=MessageSource.USER,
        metadata={
            "origin_layer": "user_instruction",
            "program_origin": False,
            "ingress_delegated": True,
        },
    )
    assert is_human_user_message(delegated) is False
    assert is_active_run_ingress_message(delegated) is True

    program_recovery = Message(
        role="user",
        content="RECOVERY",
        source=MessageSource.SYSTEM,
        metadata={"origin_layer": "program_recovery", "program_origin": True},
    )
    assert is_human_user_message(program_recovery) is False
    assert is_active_run_ingress_message(program_recovery) is False


def test_privacy_safe_incident_fixture_replays_legacy_loss_and_active_ingress_fix() -> None:
    fixture, base, current = _incident_fixture_messages()
    observation = fixture["compaction_observation"]
    assert fixture["active_turn_ref"] == 537
    assert observation["anchor_before"] == 0
    assert observation["anchor_after"] == 550
    assert observation["archived_count"] == len(fixture["archived_span"])
    assert fixture["provider_failure"]["provider_code"] == "1214"
    assert fixture["provider_failure"]["provider_truncated"] is None

    legacy_archived: list[Message] = []
    legacy = build_history_messages(
        base,
        "SYS",
        max_chars=4_000,
        compact_ratio=0.85,
        session_id="err1214-fixture-legacy",
        archive_sink=lambda _sid, message: legacy_archived.append(message),
        head_keep_chars=0,
        cache_archive_provider="glm",
        cache_archive_model="glm/glm-5.3",
        cache_archive_budget=4_000,
        preserve_last_human_exact=False,
        current_turn_ref=0,
    )
    assert current in legacy_archived
    assert not any(
        item.get("role") == "user" and item.get("content") == current.content
        for item in legacy
    )

    # Rebuild from fresh fixture messages because the legacy call intentionally writes
    # provider compaction markers onto its input messages.
    _, repaired_base, repaired_current = _incident_fixture_messages()
    repaired_archived: list[Message] = []
    repaired = build_history_messages(
        repaired_base,
        "SYS",
        max_chars=4_000,
        compact_ratio=0.85,
        session_id="err1214-fixture-repaired",
        archive_sink=lambda _sid, message: repaired_archived.append(message),
        head_keep_chars=0,
        cache_archive_provider="glm",
        cache_archive_model="glm/glm-5.3",
        cache_archive_budget=4_000,
        preserve_active_ingress_message=repaired_current,
        current_turn_ref=0,
    )
    assert all(message is not repaired_current for message in repaired_archived)
    assert any(
        item.get("role") == "user" and item.get("content") == repaired_current.content
        for item in repaired
    )
    assert validate_tool_call_pairing(repaired) == []


def test_active_ingress_internal_ref_survives_history_projection_until_final_validator() -> None:
    delegated = Message(
        role="user",
        content="DELEGATED",
        source=MessageSource.USER,
        metadata={
            "origin_layer": "user_instruction",
            "program_origin": False,
            "ingress_delegated": True,
        },
    )
    base = [delegated, *_tool_group(1)]
    projection = run_history_projection(
        base=base,
        system_prompt="SYS",
        filtered_indices=list(range(len(base))),
        sess_anchor=0,
        prefix_len=0,
        session_id="err1214-marker",
        max_chars=50_000,
        runtime_history_budget_value=50_000,
        compact_ratio=0.85,
        archive_sink=lambda _sid, _message: None,
        settings=SimpleNamespace(exact_duplicate_tool_fold=False),
        provider_id="glm",
        resolved_label="glm/glm-5.3",
        reasoning_tail=0,
        r6_ingress_truth=None,
        registry=SimpleNamespace(evidence_mode="off"),
        cache_monitor=_CacheMonitor(),
        effective_budget=50_000,
        current_turn_ref=0,
    )

    marked = [m for m in projection.built if m.get("_active_run_ingress_ref")]
    assert len(marked) == 1
    assert marked[0]["role"] == "user"
    assert marked[0]["content"] == "DELEGATED"
    assert marked[0]["_active_run_ingress_ref"] == "0"


def test_final_provider_validator_accepts_parallel_results_and_strips_internal_ref() -> None:
    messages = [
        {"role": "system", "content": "SYS"},
        {
            "role": "user",
            "content": "DELEGATED",
            "_active_run_ingress_ref": "537",
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-a",
                    "type": "function",
                    "function": {"name": "a", "arguments": "{}"},
                },
                {
                    "id": "call-b",
                    "type": "function",
                    "function": {"name": "b", "arguments": "{}"},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call-b", "content": "B"},
        {"role": "tool", "tool_call_id": "call-a", "content": "A"},
    ]
    states: list[dict] = []
    client = object.__new__(LLMClient)
    client.provider = "glm"
    context = GuardRequestContext(
        active_run_ingress_ref="537",
        active_run_ingress_kind="delegated",
        structure_state_hook=lambda state: states.append(state),
    )

    assert LLMClient._provider_structure_violations(
        messages, expected_active_ingress_ref="537"
    ) == []
    stripped = client._validate_and_strip_provider_structure(messages, guard_context=context)
    assert all("_active_run_ingress_ref" not in message for message in stripped)
    assert states == [
        {
            "valid": True,
            "violations": [],
            "active_run_ingress_ref": "537",
            "active_run_ingress_kind": "delegated",
        }
    ]


def test_final_provider_validator_blocks_missing_expected_active_ingress() -> None:
    states: list[dict] = []
    client = object.__new__(LLMClient)
    client.provider = "glm"
    context = GuardRequestContext(
        active_run_ingress_ref="537",
        active_run_ingress_kind="delegated",
        structure_state_hook=lambda state: states.append(state),
    )

    try:
        client._validate_and_strip_provider_structure(
            [{"role": "system", "content": "SYS"}, {"role": "assistant", "content": "OLD"}],
            guard_context=context,
        )
    except LLMProjectionError as exc:
        assert "active_run_ingress_missing:537" in exc.violations
    else:  # pragma: no cover - validator must fail closed before transport
        raise AssertionError("missing active ingress must be blocked")
    assert states and states[-1]["valid"] is False
    assert "active_run_ingress_missing:537" in states[-1]["violations"]


def test_conservative_rebuild_retires_only_older_complete_groups() -> None:
    current = Message(
        role="user",
        content="DELEGATED",
        source=MessageSource.USER,
        metadata={
            "origin_layer": "user_instruction",
            "program_origin": False,
            "ingress_delegated": True,
        },
    )
    older = _tool_group(1)
    newest = _tool_group(2)
    base = [current, *older, *newest]
    # Enough for system + ingress + newest complete atomic group, but not both tool groups.
    mandatory_chars = len("SYS") + len(current.content) + sum(
        len(message.content) + len(str(message.tool_calls or "")) for message in newest
    )
    outcome = build_conservative_active_run_projection(
        base=base,
        filtered_indices=list(range(len(base))),
        system_prompt="SYS",
        current_turn_ref=0,
        max_chars=mandatory_chars + 20,
    )

    assert outcome.state == "rebuilt"
    assert outcome.retired_groups == 1
    assert outcome.total_groups == 3
    assert outcome.messages[0] == {"role": "system", "content": "SYS"}
    assert outcome.messages[1]["role"] == "user"
    assert outcome.messages[1]["content"] == "DELEGATED"
    assert outcome.messages[1]["_active_run_ingress_ref"] == "0"
    rebuilt = list(outcome.messages)
    assert validate_tool_call_pairing(rebuilt) == []
    rebuilt_ids = {
        call["id"]
        for message in rebuilt
        for call in (message.get("tool_calls") or [])
    }
    assert rebuilt_ids == {"call-2"}


def test_conservative_rebuild_soft_history_cap_cannot_fake_window_cannot_fit() -> None:
    current = Message(
        role="user", content="DELEGATED", source=MessageSource.USER,
        metadata={"ingress_delegated": True},
    )
    newest = _tool_group(8)
    base = [current, *newest]
    outcome = build_conservative_active_run_projection(
        base=base,
        filtered_indices=list(range(len(base))),
        system_prompt="SYS",
        current_turn_ref=0,
        max_chars=1,
        hard_limit_chars=10_000,
    )

    assert outcome.state == "rebuilt"
    assert outcome.projected_chars > outcome.budget_chars


def test_conservative_rebuild_reports_projection_cannot_fit_without_mutating_truth() -> None:
    current = Message(
        role="user",
        content="U" * 900,
        source=MessageSource.USER,
        metadata={
            "origin_layer": "user_instruction",
            "program_origin": False,
            "ingress_delegated": True,
        },
    )
    newest = _tool_group(9)
    metadata_before = dict(current.metadata)
    outcome = build_conservative_active_run_projection(
        base=[current, *newest],
        filtered_indices=list(range(1 + len(newest))),
        system_prompt="SYS",
        current_turn_ref=0,
        max_chars=100,
        hard_limit_chars=100,
    )

    assert outcome.state == "projection_cannot_fit"
    assert outcome.messages == ()
    assert outcome.projected_chars > outcome.budget_chars
    assert current.content == "U" * 900
    assert current.metadata == metadata_before
    assert "_active_run_ingress_ref" not in current.metadata


def test_conservative_rebuild_fails_closed_on_incomplete_current_atomic_group() -> None:
    current = Message(
        role="user",
        content="DELEGATED",
        source=MessageSource.USER,
        metadata={"origin_layer": "user_instruction", "ingress_delegated": True},
    )
    incomplete = Message(
        role="assistant",
        content="",
        source=MessageSource.USER,
        tool_calls=[
            {
                "id": "call-a",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }
        ],
    )
    outcome = build_conservative_active_run_projection(
        base=[current, incomplete],
        filtered_indices=[0, 1],
        system_prompt="SYS",
        current_turn_ref=0,
        max_chars=10_000,
    )

    assert outcome.state == "current_atomic_group_incomplete"
    assert outcome.messages == ()
    assert "not_exactly_closed" in outcome.detail


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


def test_delegated_followup_compaction_keeps_exact_active_run_ingress() -> None:
    """A scheduled/delegated run ingress is protocol-active even though it is not human."""
    current = Message(
        role="user",
        content="[定时续跑·先前真人授权的程序委派·非新真人输入] CONTINUE",
        source=MessageSource.USER,
        metadata={"ingress_delegated": True, "ingress_channel": "schedule_wake"},
    )
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
        session_id="err1214-delegated-followup",
        max_chars=1_200,
        runtime_history_budget_value=1_200,
        compact_ratio=0.85,
        archive_sink=lambda _sid, message: archived.append(message),
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
        item.get("role") == "user" and item.get("content") == current.content
        for item in projection.built
    ), "exact active delegated ingress must remain provider-visible after compaction"
    assert all(message is not current for message in archived)
    assert archived, "preserving active ingress must not disable mechanical tool compaction"
    assert sum(item.get("role") == "user" for item in projection.built) == 1
    assert validate_tool_call_pairing(projection.built) == []


def test_bad_marker_and_advanced_anchor_cannot_hide_active_delegated_ingress() -> None:
    """Persisted bad compaction must reopen the exact delegated run ingress on retry."""
    current = Message(
        role="user",
        content="[定时续跑·先前真人授权的程序委派·非新真人输入] CONTINUE",
        source=MessageSource.USER,
        metadata={"ingress_delegated": True, "ingress_channel": "schedule_wake"},
    )
    base = [
        Message(role="assistant", content="H" * 170, source=MessageSource.USER),
        current,
    ]
    for index in range(6):
        base.extend(_tool_group(index))

    bad_archived: list[Message] = []
    bad_anchor: list[int] = []
    build_history_messages(
        base,
        "SYS",
        max_chars=1_200,
        compact_ratio=0.85,
        session_id="err1214-delegated-bad-state",
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
        session_id="err1214-delegated-retry",
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
        item.get("role") == "user" and item.get("content") == current.content
        for item in projection.built
    ), "retry must reopen the exact delegated ingress past bad anchor/marker state"
    assert all(message is not current for message in retried_archived)
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
        item.get("role") == "user" and item.get("content") == "CURRENT-HUMAN"
        for item in built
    )
    assert all(message is not current for message in archived)
    assert archived, "head downgrade should still retire other atomic groups"
    assert validate_tool_call_pairing(built) == []


def _parallel_tool_group(index: int) -> list[Message]:
    call_ids = [f"parallel-{index}-a", f"parallel-{index}-b"]
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
                for call_id in call_ids
            ],
        ),
        *[
            Message(
                role="tool",
                content=("P" if ordinal == 0 else "Q") * 260,
                source=MessageSource.TOOL,
                tool_call_id=call_id,
                tool_name="read_file",
                status=ToolResultStatus.SUCCESS,
            )
            for ordinal, call_id in enumerate(call_ids)
        ],
    ]


def _project_for_t_matrix(
    base: list[Message], *, current_turn_ref: int, sess_anchor: int = 0, session_id: str
):
    return run_history_projection(
        base=base,
        system_prompt="SYS",
        filtered_indices=list(range(len(base))),
        sess_anchor=sess_anchor,
        prefix_len=0,
        session_id=session_id,
        max_chars=1_100,
        runtime_history_budget_value=1_100,
        compact_ratio=0.85,
        archive_sink=lambda _sid, _message: None,
        settings=SimpleNamespace(exact_duplicate_tool_fold=False),
        provider_id="glm",
        resolved_label="glm/glm-5.3",
        reasoning_tail=0,
        r6_ingress_truth=None,
        registry=SimpleNamespace(evidence_mode="off"),
        cache_monitor=_CacheMonitor(),
        effective_budget=1_100,
        current_turn_ref=current_turn_ref,
    )


def test_t3_delegated_active_ingress_survives_three_followup_compaction_builds() -> None:
    """T3: N+1/N+2/N+3 builds cannot advance history past the active delegated ingress."""
    current = Message(
        role="user",
        content="[定时续跑·先前真人授权的程序委派·非新真人输入] CONTINUE",
        source=MessageSource.USER,
        metadata={"ingress_delegated": True, "ingress_channel": "schedule_wake"},
    )
    base = [current]
    for index in range(5):
        base.extend(_tool_group(index))

    anchor = 0
    for round_index in range(3):
        projection = _project_for_t_matrix(
            base,
            current_turn_ref=0,
            sess_anchor=anchor,
            session_id=f"err1214-t3-{round_index}",
        )
        assert any(
            item.get("role") == "user" and item.get("content") == current.content
            for item in projection.built
        )
        assert validate_tool_call_pairing(projection.built) == []
        # With identity filtered_indices/prefix=0, a persisted anchor must never pass
        # the exact active ingress at source index 0.
        anchor = projection.anchor_box[0] if projection.anchor_box else anchor
        assert anchor == 0
        base.extend(_tool_group(10 + round_index))


def test_t5_delegated_no_tool_projection_keeps_active_ingress() -> None:
    """T5: a delegated continuation that only needs text remains a legal user-anchored wire."""
    current = Message(
        role="user",
        content="[定时续跑·先前真人授权的程序委派·非新真人输入] TEXT-ONLY",
        source=MessageSource.USER,
        metadata={"ingress_delegated": True, "ingress_channel": "schedule_wake"},
    )
    base = [Message(role="assistant", content="H" * 700, source=MessageSource.USER), current]
    projection = _project_for_t_matrix(
        base, current_turn_ref=1, session_id="err1214-t5-text-only"
    )
    users = [item for item in projection.built if item.get("role") == "user"]
    assert [item.get("content") for item in users] == [current.content]
    assert validate_tool_call_pairing(projection.built) == []


def test_t6_delegated_parallel_tool_group_stays_atomic_under_compaction() -> None:
    """T6: delegated active ingress and all parallel tool_call results remain structurally paired."""
    current = Message(
        role="user",
        content="[定时续跑·先前真人授权的程序委派·非新真人输入] PARALLEL",
        source=MessageSource.USER,
        metadata={"ingress_delegated": True, "ingress_channel": "schedule_wake"},
    )
    base = [current]
    for index in range(4):
        base.extend(_tool_group(index))
    parallel = _parallel_tool_group(9)
    base.extend(parallel)

    projection = _project_for_t_matrix(
        base, current_turn_ref=0, session_id="err1214-t6-parallel"
    )
    assert any(item.get("content") == current.content for item in projection.built)
    assert validate_tool_call_pairing(projection.built) == []
    projected_ids = {
        item.get("tool_call_id")
        for item in projection.built
        if item.get("role") == "tool"
    }
    assert {"parallel-9-a", "parallel-9-b"}.issubset(projected_ids)


def test_t7_new_human_turn_retires_old_delegated_ingress_protection() -> None:
    """T7: after handoff, only the new human is active; old delegated ingress may retire normally."""
    old_delegated = Message(
        role="user",
        content="OLD-DELEGATED-" + "D" * 420,
        source=MessageSource.USER,
        metadata={"ingress_delegated": True, "ingress_channel": "schedule_wake"},
    )
    base = [old_delegated]
    for index in range(4):
        base.extend(_tool_group(index))
    new_human_index = len(base)
    new_human = Message(role="user", content="NEW-HUMAN", source=MessageSource.USER)
    base.append(new_human)
    base.extend(_tool_group(20))

    archived: list[Message] = []
    projection = run_history_projection(
        base=base,
        system_prompt="SYS",
        filtered_indices=list(range(len(base))),
        sess_anchor=0,
        prefix_len=0,
        session_id="err1214-t7-human-takeover",
        max_chars=1_100,
        runtime_history_budget_value=1_100,
        compact_ratio=0.85,
        archive_sink=lambda _sid, message: archived.append(message),
        settings=SimpleNamespace(exact_duplicate_tool_fold=False),
        provider_id="glm",
        resolved_label="glm/glm-5.3",
        reasoning_tail=0,
        r6_ingress_truth=None,
        registry=SimpleNamespace(evidence_mode="off"),
        cache_monitor=_CacheMonitor(),
        effective_budget=1_100,
        current_turn_ref=new_human_index,
    )
    assert any(item.get("content") == "NEW-HUMAN" for item in projection.built)
    assert old_delegated in archived or all(
        item.get("content") != old_delegated.content for item in projection.built
    )
    assert validate_tool_call_pairing(projection.built) == []
