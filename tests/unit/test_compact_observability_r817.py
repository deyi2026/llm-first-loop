from __future__ import annotations

from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt import build_system_prompt


def _pair(i: int) -> list[Message]:
    return [
        Message(
            role="assistant",
            content="D" * 260,
            source=MessageSource.USER,
            tool_calls=[
                {"id": f"c{i}", "name": "read_file", "arguments": {"path": f"/tmp/{i}"}}
            ],
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
        _append_summary_enabled=True,
        progressive_fold=2,
        cache_archive_provider="deepseek",
        cache_compacted_out=compacted,
        compact_view_stats=stats,
    )

    joined = "\n".join(str(m.get("content", "")) for m in out)
    assert archived
    assert compacted
    assert stats and int(stats[0]["archived_count"]) > 0
    assert float(stats[0]["drop_pct"]) > 0
    for forbidden in (
        "[上下文压缩]",
        "[中段折叠]",
        "[渐进折叠]",
        "[缓存降级]",
        "ref=archive:search_archive",
    ):
        assert forbidden not in joined


def test_search_archive_discovery_is_stable_not_dynamic():
    prompt = build_system_prompt()
    assert "search_archive" in prompt
    assert "会话超长时程序把最早消息完整另存到压缩档案" in prompt
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
    engine._record_action = lambda phase, status, detail: actions.append(  # type: ignore[method-assign]
        (phase, status, detail)
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
