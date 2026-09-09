from __future__ import annotations

import pytest

from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt import build_system_prompt


@pytest.fixture(autouse=True)
def _pin_compact_ratio_env(monkeypatch: pytest.MonkeyPatch):
    """Declare COMPACT_RATIO dependency: exact-number assertions need ratio=1.0.

    Compaction trigger threshold = max_chars × COMPACT_RATIO
    (history_budget_prep.py reads os.environ directly). Ambient env or real
    .env residue leaking via load_env_file() (same lesson as
    test_context_budget_warning.py EVO-20260831) silently turns 3000 into
    2550 and flips these assertions red with zero code change. This module
    pins the default semantics explicitly; the env→threshold contract is
    guarded separately in test_compact_ratio_env_syncs_trigger_limit.
    """
    monkeypatch.setenv("COMPACT_RATIO", "1.0")


def _pair(i: int) -> list[Message]:
    return [
        Message(
            role="assistant",
            content="D" * 260,
            source=MessageSource.USER,
            tool_calls=[{"id": f"c{i}", "name": "read_file", "arguments": {"path": f"/tmp/{i}"}}],
        ),
        Message(
            role="tool",
            content="R" * 260,
            source=MessageSource.USER,
            tool_call_id=f"c{i}",
        ),
    ]


def test_compact_runtime_status_is_prompt_neutral_but_observable():
    messages: list[Message] = []
    for i in range(8):
        messages.extend(_pair(i))
    archived: list[Message] = []
    stats: list[dict] = []
    compacted: list[Message] = []

    out = build_history_messages(
        messages,
        "SYS",
        max_chars=1800,
        session_id="s-r817",
        archive_sink=lambda _sid, msg: archived.append(msg),
        cache_archive_provider="deepseek",
        cache_compacted_out=compacted,
        compact_view_stats=stats,
    )

    joined = "\n".join(str(m.get("content", "")) for m in out)
    assert archived
    assert compacted
    assert stats and int(stats[0]["archived_count"]) > 0
    assert float(stats[0]["drop_pct"]) > 0
    assert stats[0]["trigger"] == "projected_history_over_compact_limit"
    assert stats[0]["effective_budget_chars"] == 1800
    assert stats[0]["trigger_limit_chars"] == 1800
    assert stats[0]["trigger_excess_chars"] > 0
    assert stats[0]["archive_target_ratio"] == 0.6
    assert stats[0]["archive_target_chars"] == 1080
    assert stats[0]["archived_group_count"] > 0
    assert stats[0]["atomic_group_count"] == 8
    assert stats[0]["compaction_mode"] == "provider_contiguous_oldest"
    for forbidden in (
        "[上下文压缩]",
        "[中段折叠]",
        "[渐进折叠]",
        "[缓存降级]",
        "ref=archive:search_archive",
    ):
        assert forbidden not in joined


def test_history_postprocess_emits_deterministic_compaction_event():
    from types import SimpleNamespace

    from llm_loop.core.prompt_build.stages.history_postprocess import run_history_postprocess

    class _Monitor:
        def note_build_result(self, **_kwargs):
            return None

        def note_anchor_moved(self, **_kwargs):
            return None

    events: list[tuple[str, dict]] = []
    sess = SimpleNamespace(
        session_id="s-compact-event",
        messages=[Message(role="user", content="u", source=MessageSource.USER)],
        history_anchors={"glm": 0},
    )
    stats = {
        "trigger": "projected_history_over_compact_limit",
        "pre_history_chars": 1100,
        "pre_chars": 1200,
        "post_chars": 700,
        "drop_pct": 41.7,
        "effective_budget_chars": 1000,
        "compact_ratio": 1.0,
        "trigger_limit_chars": 1000,
        "trigger_excess_chars": 100,
        "archive_target_ratio": 0.6,
        "archive_target_chars": 600,
        "archived_count": 3,
        "archived_group_count": 2,
        "atomic_group_count": 8,
        "compaction_mode": "provider_contiguous_oldest",
        "head_keep_chars": 200,
        "head_keep_target_ratio": 0.5,
        "cache_boundary_mode": "epoch_reset",
        "cache_protected_messages": 2,
        "cache_protected_chars": 180,
    }
    out = run_history_postprocess(
        cache_compacted_source_box=[],
        compacted_box=[True],
        compact_view_box=[stats],
        anchor_box=[1],
        filtered_indices=[0],
        prefix_len=0,
        sess=sess,
        sess_anchor=0,
        provider_id="glm",
        resolved_label="glm/glm-5.3",
        effective_budget=1000,
        compact_event_seq=4,
        compact_event_was_compacted=False,
        cache_monitor=_Monitor(),
        event_append=lambda _sid, typ, payload: events.append((typ, payload)),
        provider_visible_chars=lambda *_args: 1,
    )
    assert out.compact_event_seq == 5
    event = next(payload for typ, payload in events if typ == "history.compaction")
    assert event["compaction_epoch"] == 5
    assert event["model"] == "glm/glm-5.3"
    assert event["pre_history_chars"] == 1100
    assert event["effective_budget_chars"] == 1000
    assert event["archive_target_chars"] == 600
    assert event["archived_group_count"] == 2
    assert event["cache_epoch_reset"] is True
    assert event["anchor_before"] == 0
    assert event["anchor_after"] == 1
    assert event["anchor_moved"] is True


def test_minimax_opaque_replay_survives_history_compaction_view():
    """Compaction may archive turns, but kept provider replay must remain byte-structured."""
    messages: list[Message] = []
    expected: dict[str, dict] = {}
    for i in range(6):
        replay = {
            "provider": "minimax",
            "fields": {
                "reasoning_details": [
                    {
                        "type": "reasoning.text",
                        "text": f"reason-{i}",
                        "signature": f"sig-{i}",
                    }
                ]
            },
        }
        expected[f"c{i}"] = replay
        messages.extend(
            [
                Message(
                    role="assistant",
                    content="",
                    source=MessageSource.USER,
                    tool_calls=[
                        {
                            "id": f"c{i}",
                            "name": "read_file",
                            "arguments": {"path": f"/tmp/{i}"},
                        }
                    ],
                    reasoning_content=f"reason-{i}",
                    metadata={"provider_replay": replay},
                ),
                Message(
                    role="tool",
                    content="R" * 320,
                    source=MessageSource.USER,
                    tool_call_id=f"c{i}",
                ),
            ]
        )

    out = build_history_messages(
        messages,
        "SYS",
        max_chars=1_500,
        session_id="s-minimax-replay-compact",
        archive_sink=lambda _sid, _msg: None,
        cache_archive_provider="minimax",
        reasoning_tail=0,
    )
    kept = [m for m in out if m.get("role") == "assistant" and m.get("tool_calls")]
    assert kept
    for assistant in kept:
        call_id = assistant["tool_calls"][0]["id"]
        assert assistant["_provider_replay"] == expected[call_id]
        assert (
            assistant["reasoning_content"]
            == (expected[call_id]["fields"]["reasoning_details"][0]["text"])
        )


def test_cloud_compaction_second_build_is_byte_stable_and_does_not_rearchive():
    """A legitimate compact may change one request, but must settle by the next build."""
    cases = [
        ("deepseek", 20_000, 0.35, 0.70),
        ("glm", 20_000, 0.15, 0.50),
        ("minimax", 20_000, 0.15, 0.50),
    ]
    for provider, budget, head_ratio, head_target_ratio in cases:
        messages: list[Message] = []
        for i in range(30):
            metadata = {}
            if provider == "minimax":
                metadata = {
                    "provider_replay": {
                        "provider": "minimax",
                        "fields": {
                            "reasoning_details": [
                                {
                                    "type": "reasoning.text",
                                    "text": f"reason-{i}-" + ("r" * 220),
                                    "signature": f"sig-{i}",
                                }
                            ]
                        },
                    }
                }
            messages.extend(
                [
                    Message(
                        role="assistant",
                        content="",
                        source=MessageSource.USER,
                        tool_calls=[
                            {
                                "id": f"{provider}-c{i}",
                                "name": "read_file",
                                "arguments": {"path": f"/tmp/{i}"},
                            }
                        ],
                        reasoning_content=f"reason-{i}-" + ("r" * 220),
                        metadata=metadata,
                    ),
                    Message(
                        role="tool",
                        content=f"tool-{i}-" + ("t" * 520),
                        source=MessageSource.USER,
                        tool_call_id=f"{provider}-c{i}",
                    ),
                ]
            )
        messages.append(
            Message(
                role="user",
                content="CURRENT-TASK-" + ("u" * 300),
                source=MessageSource.USER,
            )
        )

        first_archived: list[Message] = []
        first = build_history_messages(
            messages,
            "",
            max_chars=budget,
            compact_ratio=1.0,
            session_id=f"stable-{provider}",
            archive_sink=lambda _sid, msg, sink=first_archived: sink.append(msg),
            head_keep_chars=int(budget * head_ratio),
            head_keep_target_ratio=head_target_ratio,
            cache_archive_provider=provider,
            reasoning_tail=0,
        )
        first_marked = sum(
            provider in ((m.metadata or {}).get("cache_compacted_for") or []) for m in messages
        )
        assert first_archived, provider
        assert first_marked == len(first_archived), provider

        second_archived: list[Message] = []
        second = build_history_messages(
            messages,
            "",
            max_chars=budget,
            compact_ratio=1.0,
            session_id=f"stable-{provider}",
            archive_sink=lambda _sid, msg, sink=second_archived: sink.append(msg),
            head_keep_chars=int(budget * head_ratio),
            head_keep_target_ratio=head_target_ratio,
            cache_archive_provider=provider,
            reasoning_tail=0,
        )
        second_marked = sum(
            provider in ((m.metadata or {}).get("cache_compacted_for") or []) for m in messages
        )

        assert second == first, provider
        assert second_archived == [], provider
        assert second_marked == first_marked, provider
        kept_tools = [m for m in second if m.get("role") == "assistant" and m.get("tool_calls")]
        assert kept_tools and all(m.get("reasoning_content") for m in kept_tools), provider
        if provider == "minimax":
            assert all(m.get("_provider_replay") for m in kept_tools)


def test_search_archive_discovery_is_not_forced_into_universal_prompt():
    prompt = build_system_prompt()
    # Archive retrieval remains a tool capability; every user turn must not carry a
    # retrieval SOP merely because compaction might happen in some sessions.
    assert "search_archive" not in prompt
    assert "会话超长时程序把最早消息完整另存到压缩档案" not in prompt
    assert "[上下文压缩] 标注 + 档案目录 + 关键事实" not in prompt


def test_engine_compact_action_reports_real_stats_not_missing_fact_warning(build_test_engine):
    engine, _fake = build_test_engine([{"content": "unused", "tool_calls": []}])
    sid = engine.session.create()
    sess = engine.session.load(sid)
    for i in range(14):
        sess.messages.append(
            Message(
                role="user",
                content=f"old-user-{i}-" + "U" * 500,
                source=MessageSource.USER,
            )
        )
        sess.messages.append(
            Message(
                role="assistant",
                content=f"old-answer-{i}-" + "A" * 500,
                source=MessageSource.SYSTEM,
            )
        )

    actions: list[tuple[str, str, str]] = []
    events: list[tuple[str, dict]] = []
    engine._record_action = lambda phase, status, detail: actions.append(  # type: ignore[method-assign]
        (phase, status, detail)
    )
    engine._event_append = lambda _sid, typ, payload: events.append(  # type: ignore[method-assign]
        (typ, payload)
    )
    built = engine._build_llm_messages(sess, [], max_chars=3_000)

    compact = [a for a in actions if a[0] == "run.compact"]
    assert compact
    phase, status, detail = compact[-1]
    assert phase == "run.compact" and status == "ok"
    assert "archived=" in detail and "drop_pct=" in detail
    assert "prompt_chars=0" in detail
    assert "retrieval=search_archive" in detail
    assert "关键事实帧缺失" not in detail

    dynamic_tail = "\n".join(str(m.get("content", "")) for m in built[1:])
    assert "[上下文压缩]" not in dynamic_tail
    assert "[中段折叠]" not in dynamic_tail
    assert "ref=archive:search_archive" not in dynamic_tail

    compact_events = [payload for typ, payload in events if typ == "history.compaction"]
    assert compact_events
    payload = compact_events[-1]
    assert payload["trigger"] == "projected_history_over_compact_limit"
    assert payload["effective_budget_chars"] == 3_000
    assert payload["trigger_limit_chars"] == 3_000
    assert payload["archive_target_chars"] == 1_800
    assert int(payload["archived_count"]) > 0
    assert payload["compaction_epoch"] >= 1


def test_compact_ratio_env_syncs_trigger_limit(build_test_engine):
    """Env COMPACT_RATIO scales the trigger threshold, not the budget.

    Guards the production contract that the autouse pin above deliberately
    neutralizes for exact-number assertions: ratio<1 lowers when compaction
    fires (3000 × 0.85 = 2550) while effective_budget_chars keeps the full
    budget. If this fails, budget semantics drifted, not test hygiene.
    """
    engine, _fake = build_test_engine([{"content": "unused", "tool_calls": []}])
    sid = engine.session.create()
    sess = engine.session.load(sid)
    for i in range(14):
        sess.messages.append(
            Message(
                role="user",
                content=f"old-user-{i}-" + "U" * 500,
                source=MessageSource.USER,
            )
        )
        sess.messages.append(
            Message(
                role="assistant",
                content=f"old-answer-{i}-" + "A" * 500,
                source=MessageSource.SYSTEM,
            )
        )

    events: list[tuple[str, dict]] = []
    engine._event_append = lambda _sid, typ, payload: events.append(  # type: ignore[method-assign]
        (typ, payload)
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("COMPACT_RATIO", "0.85")
        engine._build_llm_messages(sess, [], max_chars=3_000)

    compact_events = [payload for typ, payload in events if typ == "history.compaction"]
    assert compact_events, "ratio=0.85 lowers the threshold; history must compact"
    payload = compact_events[-1]
    assert payload["trigger_limit_chars"] == 2_550
    assert payload["effective_budget_chars"] == 3_000
