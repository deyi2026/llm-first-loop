from __future__ import annotations

import json

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata
from llm_loop.core.message import Message, MessageSource, ToolResultStatus


def _seed_tool_round(sess) -> tuple[str, str]:
    call_id = "call-r818-digest"
    fact = "UNIQUE_R818_TOOL_FACT"
    sess.messages.extend(
        [
            Message(role="user", content="检查文件", source=MessageSource.USER),
            Message(
                role="assistant",
                content="",
                source=MessageSource.USER,
                tool_calls=[
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps({"path": "/tmp/r818.txt"}),
                        },
                    }
                ],
            ),
            Message(
                role="tool",
                content=f"[状态: success] {fact}",
                source=MessageSource.TOOL,
                tool_call_id=call_id,
                tool_name="read_file",
                status=ToolResultStatus.SUCCESS,
            ),
        ]
    )
    return call_id, fact


def test_digest_enabled_does_not_emit_or_persist_catalog(build_test_engine):
    engine, _fake = build_test_engine([{"content": "unused", "tool_calls": []}])
    object.__setattr__(engine.settings, "digest_enabled", True)
    sid = engine.session.create()
    sess = engine.session.load(sid)
    _call_id, fact = _seed_tool_round(sess)
    before = len(sess.messages)

    built = engine._build_llm_messages(sess, [], max_chars=100_000)
    joined = "\n".join(str(m.get("content", "")) for m in built)

    assert fact in joined  # original current tool result remains available
    assert "slot:digest" not in joined
    assert "ref=digest:" not in joined
    assert len(sess.messages) == before
    assert not any(
        (m.metadata or {}).get("injection_kind") == "session_digest_catalog"
        for m in sess.messages
    )


def test_legacy_catalog_is_filtered_but_human_digest_text_is_preserved(build_test_engine):
    engine, _fake = build_test_engine([{"content": "unused", "tool_calls": []}])
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.messages.extend(
        [
            Message(
                role="user",
                content="LEGACY_R818_CATALOG ref=digest:old-call;archive_tool=read_file",
                source=MessageSource.USER,
                metadata=origin_metadata(
                    InjectionLayer.REFERENCE,
                    injection_kind="session_digest_catalog",
                    persisted_injection=True,
                    turn_ref=1,
                ),
            ),
            Message(
                role="user",
                content="我在讨论 ref=digest:human-text，这是真实用户原话",
                source=MessageSource.USER,
            ),
        ]
    )

    built = engine._build_llm_messages(sess, [], max_chars=100_000)
    joined = "\n".join(str(m.get("content", "")) for m in built)

    assert "LEGACY_R818_CATALOG" not in joined
    assert "ref=digest:human-text" in joined
    assert any(
        (m.metadata or {}).get("injection_kind") == "session_digest_catalog"
        for m in sess.messages
    ), "storage/event truth must remain untouched"
