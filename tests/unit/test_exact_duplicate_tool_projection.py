from __future__ import annotations

from copy import deepcopy

from llm_loop.core.history import project_exact_duplicate_tool_groups


def _group(call_id: str, *, reasoning: str = "", result: str = "same") -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": reasoning,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "execute_command",
                        "arguments": '{"command":"probe"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "content": result,
        },
    ]


def test_contiguous_exact_action_observation_duplicates_fold_without_hint() -> None:
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        *_group("call-1"),
        *_group("call-2"),
        *_group("call-3"),
    ]
    original = deepcopy(messages)

    projected, stats = project_exact_duplicate_tool_groups(messages)

    assert messages == original  # durable/source truth is untouched
    assert stats == {"folded_groups": 2, "removed_messages": 4}
    assert projected == messages[:4]  # keep first group for stable-prefix bytes
    assert all("重复" not in str(message) and "retry" not in str(message) for message in projected)


def test_different_reasoning_or_result_is_not_semantically_folded() -> None:
    messages = [
        {"role": "user", "content": "u"},
        *_group("call-1", reasoning="hypothesis-a"),
        *_group("call-2", reasoning="hypothesis-b"),
        *_group("call-3", reasoning="hypothesis-b", result="different"),
    ]

    projected, stats = project_exact_duplicate_tool_groups(messages)

    assert projected == messages
    assert stats == {"folded_groups": 0, "removed_messages": 0}


def test_nonconsecutive_exact_groups_are_not_folded() -> None:
    messages = [
        {"role": "user", "content": "u"},
        *_group("call-1"),
        {"role": "assistant", "content": "new fact"},
        *_group("call-2"),
    ]

    projected, stats = project_exact_duplicate_tool_groups(messages)

    assert projected == messages
    assert stats == {"folded_groups": 0, "removed_messages": 0}


def test_two_identical_groups_remain_visible_as_retry_evidence() -> None:
    messages = [
        {"role": "user", "content": "u"},
        *_group("call-1"),
        *_group("call-2"),
    ]

    projected, stats = project_exact_duplicate_tool_groups(messages)

    assert projected == messages
    assert stats == {"folded_groups": 0, "removed_messages": 0}


def test_history_projection_wires_exact_duplicate_fold_only_when_enabled(monkeypatch) -> None:
    from types import SimpleNamespace

    from llm_loop.core.prompt_build.stages import history_projection as stage

    built = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        *_group("call-1"),
        *_group("call-2"),
        *_group("call-3"),
    ]
    monkeypatch.setattr(stage, "build_history_messages", lambda *a, **kw: deepcopy(built))

    class _Cache:
        force_head_keep = False

        @staticmethod
        def breaker_freeze_compression(_session_id: str) -> bool:
            return False

    common = dict(
        base=[],
        system_prompt="",
        filtered_indices=[],
        sess_anchor=0,
        prefix_len=0,
        session_id="sid",
        max_chars=10000,
        runtime_history_budget_value=10000,
        compact_ratio=1.0,
        archive_sink=None,
        provider_id="",
        resolved_label="model",
        reasoning_tail=0,
        r6_ingress_truth=None,
        registry=SimpleNamespace(evidence_mode="off"),
        cache_monitor=_Cache(),
        effective_budget=10000,
    )

    off = stage.run_history_projection(
        **common,
        settings=SimpleNamespace(exact_duplicate_tool_fold=False),
    )
    on = stage.run_history_projection(
        **common,
        settings=SimpleNamespace(exact_duplicate_tool_fold=True),
    )

    assert off.built == built
    assert off.duplicate_tool_projection_stats == {
        "enabled": False,
        "folded_groups": 0,
        "removed_messages": 0,
    }
    assert on.built == built[:4]
    assert on.duplicate_tool_projection_stats == {
        "enabled": True,
        "folded_groups": 2,
        "removed_messages": 4,
    }
