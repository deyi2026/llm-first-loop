from __future__ import annotations

from llm_loop.core.episode_history import (
    collect_active_evidence_groups,
    evidence_candidate_set_digest,
    measure_evidence_selection_shadow,
)
from llm_loop.core.message import Message, MessageSource, ToolResultStatus


def _assistant(*calls: tuple[str, str, object]) -> Message:
    tool_calls = []
    for call_id, name, arguments in calls:
        tool_calls.append(
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        )
    return Message(
        role="assistant",
        content="checking",
        source=MessageSource.USER,
        tool_calls=tool_calls,
        model_used="test-model",
        metadata={"answer_origin": "model"},
    )


def _tool(
    call_id: str,
    content: str,
    *,
    name: str = "read_file",
    status: ToolResultStatus = ToolResultStatus.SUCCESS,
    ref: str | None = "evidence://v1/test",
) -> Message:
    metadata = {}
    if ref is not None:
        metadata = {"recoverability_status": "recorded", "evidence_ref": ref}
    return Message(
        role="tool",
        content=content,
        source=MessageSource.TOOL,
        tool_call_id=call_id,
        status=status,
        tool_name=name,
        metadata=metadata,
    )


def _model_final(text: str = "continue") -> Message:
    return Message(
        role="assistant",
        content=text,
        source=MessageSource.USER,
        model_used="test-model",
        metadata={"answer_origin": "model"},
    )


def test_collector_assigns_fold_local_ids_and_keeps_multi_tool_group_atomic():
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant(("c1", "read_file", '{"b":2,"a":1}'), ("c2", "grep", '{"q":"x"}')),
        _tool("c1", "A" * 7, ref="evidence://v1/a"),
        _tool("c2", "B" * 5, name="grep", ref="evidence://v1/b"),
        _assistant(("c3", "read_file", "{}")),
        _tool("c3", "C" * 3, ref="evidence://v1/c"),
    ]

    groups = collect_active_evidence_groups(messages)

    assert [group.descriptor.evidence_id for group in groups] == ["e1", "e2"]
    first = groups[0]
    assert first.descriptor.tool_call_ids == ("c1", "c2")
    assert first.descriptor.tool_names == ("read_file", "grep")
    assert first.descriptor.canonical_args == ('{"a":1,"b":2}', '{"q":"x"}')
    assert first.descriptor.result_count == 2
    assert first.descriptor.raw_chars == 12
    assert first.descriptor.statuses == ("success", "success")
    assert first.descriptor.recoverable is True
    assert first.result_indices == (2, 3)
    assert first.exposed is True
    assert groups[1].exposed is False


def test_collector_uses_only_latest_human_turn_and_restarts_fold_local_ids():
    messages = [
        Message(role="user", content="old task", source=MessageSource.USER),
        _assistant(("old", "read_file", "{}")),
        _tool("old", "OLD"),
        _model_final("old final"),
        Message(role="user", content="new task", source=MessageSource.USER),
        _assistant(("new", "read_file", "{}")),
        _tool("new", "NEW"),
    ]

    groups = collect_active_evidence_groups(messages)

    assert len(groups) == 1
    assert groups[0].descriptor.evidence_id == "e1"
    assert groups[0].descriptor.tool_call_ids == ("new",)


def test_protocol_digest_is_stable_for_dict_key_order_and_changes_with_raw_result():
    call_a = {
        "id": "c1",
        "type": "function",
        "function": {"name": "read_file", "arguments": "{}"},
    }
    call_b = {
        "function": {"arguments": "{}", "name": "read_file"},
        "type": "function",
        "id": "c1",
    }

    def digest(call: dict, content: str) -> str:
        messages = [
            Message(role="user", content="task", source=MessageSource.USER),
            Message(
                role="assistant",
                content="checking",
                source=MessageSource.USER,
                tool_calls=[call],
                model_used="test-model",
                metadata={"answer_origin": "model"},
            ),
            _tool("c1", content),
        ]
        return collect_active_evidence_groups(messages)[0].descriptor.protocol_digest

    assert digest(call_a, "same") == digest(call_b, "same")
    assert digest(call_a, "same") != digest(call_a, "changed")


def test_catalog_arguments_are_bounded_without_semantic_summary():
    argument = '{"payload":"' + ("X" * 2000) + '"}'
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant(("c1", "read_file", argument)),
        _tool("c1", "result"),
    ]

    descriptor = collect_active_evidence_groups(messages)[0].descriptor
    catalog = descriptor.to_catalog_dict()

    assert descriptor.canonical_args[0].startswith("sha256=")
    assert ";preview=" in descriptor.canonical_args[0]
    assert len(descriptor.canonical_args[0]) < 300
    assert set(catalog) == {
        "id",
        "protocol_digest",
        "tool_call_ids",
        "tool_names",
        "canonical_args",
        "raw_chars",
        "result_count",
        "status",
        "recoverable",
    }
    assert not ({"relevance", "importance", "sufficiency", "staleness", "summary"} & set(catalog))


def test_incomplete_pair_is_not_synthesized_into_candidate():
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant(("c1", "read_file", "{}"), ("c2", "grep", "{}")),
        _tool("c1", "only one receipt"),
    ]

    assert collect_active_evidence_groups(messages) == ()


def test_recoverable_requires_every_result_to_have_durable_ref():
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant(("c1", "read_file", "{}"), ("c2", "grep", "{}")),
        _tool("c1", "A", ref="evidence://v1/a"),
        _tool("c2", "B", name="grep", ref=None),
    ]

    groups = collect_active_evidence_groups(messages)

    assert len(groups) == 1
    assert groups[0].descriptor.recoverable is False


def test_candidate_set_digest_is_deterministic_for_same_snapshot():
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant(("c1", "read_file", "{}")),
        _tool("c1", "A"),
        _assistant(("c2", "grep", "{}")),
        _tool("c2", "B", name="grep"),
    ]

    first = collect_active_evidence_groups(messages)
    second = collect_active_evidence_groups(messages)

    assert evidence_candidate_set_digest(first) == evidence_candidate_set_digest(second)
    assert evidence_candidate_set_digest(first).startswith("v1:")


def test_shadow_selection_reports_only_mechanical_selected_size_facts():
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant(("c1", "read_file", "{}")),
        _tool("c1", "A" * 10),
        _assistant(("c2", "grep", "{}"), ("c3", "read_file", "{}")),
        _tool("c2", "B" * 20, name="grep"),
        _tool("c3", "C" * 30),
    ]
    groups = collect_active_evidence_groups(messages)

    stats = measure_evidence_selection_shadow(groups, ["e2"])
    payload = stats.to_dict()

    assert stats.selection_valid is True
    assert stats.selected_ids == ("e2",)
    assert stats.candidate_group_count == 2
    assert stats.candidate_raw_chars == 60
    assert stats.selected_group_count == 1
    assert stats.selected_raw_chars == 50
    assert stats.selected_tool_call_count == 2
    assert stats.unknown_id_count == 0
    assert stats.duplicate_id_count == 0
    assert stats.pairing_valid is True
    assert not ({"quality", "importance", "task_complete", "relevance"} & set(payload))


def test_shadow_selection_flags_unknown_and_duplicate_ids_without_applying_any_selection():
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant(("c1", "read_file", "{}")),
        _tool("c1", "A" * 10),
    ]
    groups = collect_active_evidence_groups(messages)

    stats = measure_evidence_selection_shadow(groups, ["e1", "e1", "e9"])

    assert stats.selection_valid is False
    assert stats.selected_ids == ("e1", "e1", "e9")
    assert stats.selected_group_count == 1
    assert stats.selected_raw_chars == 10
    assert stats.duplicate_id_count == 1
    assert stats.unknown_id_count == 1
