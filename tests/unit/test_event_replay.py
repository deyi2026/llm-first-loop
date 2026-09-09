"""单元测试: D1 事件回放与派生视图重建（design.md §2.4.1）.

覆盖:
- 同一事件日志重放两次逐字节一致（确定性，spec §5.3.1-1）
- 重建视图与构造源 messages 逐字段一致
- 压缩标注消息语义保留（context.compressed 引用）
- 元数据重建缺失如实置空
- 未知类型/seq 缺口标注正确；空事件列表不伪造空会话
"""

from __future__ import annotations

from llm_loop.event_log.model import (
    EVENT_CONTEXT_COMPRESSED,
    EVENT_MESSAGE_APPENDED,
    EVENT_MESSAGE_CACHE_COMPACTED,
    EVENT_SESSION_CREATED,
    EVENT_SESSION_META_CHANGED,
    Event,
)
from llm_loop.event_log.replay import replay_session


def _event(seq: int, type_: str, **payload) -> Event:
    return Event(
        event_id=f"e{seq}",
        session_id="s1",
        seq=seq,
        type=type_,
        ts="2026-08-14T00:00:00+00:00",
        payload=payload,
    )


def _source_session() -> dict:
    return {
        "version": 4,
        "session_id": "s1",
        "created_at": "2026-01-01T00:00:00",
        "title": "测试会话",
        "updated_at": "2026-01-01T00:00:02",
        "status": "active",
        "parent_id": None,
        "branch_id": "",
        "branch_summary": "",
        "model_override": None,
        "pinned": True,
        "channel": "web",
        "messages": [
            {
                "role": "user",
                "content": "你好",
                "source": "user",
                "tool_call_id": None,
                "status": None,
                "tool_name": None,
                "error_detail": None,
                "tool_calls": None,
                "reasoning_content": None,
                "metadata": {},
            },
            {
                "role": "assistant",
                "content": "",
                "source": "user",
                "tool_call_id": None,
                "status": None,
                "tool_name": None,
                "error_detail": None,
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "f1", "arguments": "{}"}}
                ],
                "reasoning_content": "思考链",
                "metadata": {},
            },
            {
                "role": "tool",
                "content": "[状态: success] 结果",
                "source": "tool",
                "tool_call_id": "c1",
                "status": "success",
                "tool_name": "f1",
                "error_detail": None,
                "tool_calls": None,
                "reasoning_content": None,
                "metadata": {},
            },
        ],
    }


def _events_from_session(src: dict) -> list[Event]:
    events = [
        _event(
            1,
            EVENT_SESSION_CREATED,
            **{
                k: src[k]
                for k in (
                    "version",
                    "title",
                    "created_at",
                    "updated_at",
                    "status",
                    "parent_id",
                    "branch_id",
                    "branch_summary",
                    "model_override",
                    "pinned",
                    "channel",
                )
            },
        )
    ]
    seq = 2
    for i, m in enumerate(src["messages"]):
        events.append(_event(seq, EVENT_MESSAGE_APPENDED, index=i, **m))
        seq += 1
    return events


def test_replay_deterministic_byte_identical():
    events = _events_from_session(_source_session())
    v1 = replay_session(events)
    v2 = replay_session(events)
    assert v1 == v2  # 确定性：两次重放逐字节一致


def test_replay_messages_field_identical():
    src = _source_session()
    view = replay_session(_events_from_session(src))
    assert view["messages"] == src["messages"]  # 逐字段一致
    assert view["title"] == src["title"]
    assert view["pinned"] is True
    assert view["version"] == 4


def test_replay_preserves_provider_opaque_replay_metadata_exactly():
    """Provider replay state is protocol data, not prose; event replay must be lossless."""
    src = _source_session()
    opaque = {
        "provider": "minimax",
        "fields": {
            "reasoning_details": [
                {
                    "type": "reasoning.text",
                    "text": "private-reasoning-state",
                    "signature": "opaque-signature-1",
                }
            ]
        },
    }
    src["messages"][1]["metadata"] = {"provider_replay": opaque}
    view = replay_session(_events_from_session(src))
    assert view["messages"][1]["metadata"]["provider_replay"] == opaque


def test_replay_compressed_marker_preserved():
    src = _source_session()
    events = _events_from_session(src)
    # 追加 context.compressed（压缩引用契约）
    events.append(
        _event(
            100, EVENT_CONTEXT_COMPRESSED, archive_ref="c1", tool_call_id="c1", msg_seq=2, chars=123
        )
    )
    view = replay_session(events)
    # 视图保留压缩标注语义（消息 content 原样）+ 压缩引用记录
    assert view["compressed_refs"] == [
        {"archive_ref": "c1", "tool_call_id": "c1", "msg_seq": 2, "chars": 123}
    ]


def test_replay_provider_cache_compacted_updates_message_metadata():
    """中段折叠状态必须可由event-log独立重建，且支持多provider累加。"""
    src = _source_session()
    events = _events_from_session(src)
    events.extend(
        [
            _event(100, EVENT_MESSAGE_CACHE_COMPACTED, msg_seq=0, provider_id="deepseek"),
            _event(101, EVENT_MESSAGE_CACHE_COMPACTED, msg_seq=0, provider_id="minimax"),
        ]
    )
    view = replay_session(events)
    assert view["messages"][0]["metadata"]["cache_compacted_for"] == [
        "deepseek",
        "minimax",
    ]


def test_replay_meta_changed_updates_top_level():
    events = _events_from_session(_source_session())
    events.append(
        _event(
            99,
            EVENT_SESSION_META_CHANGED,
            field="title",
            changes={"title": {"from": "测试会话", "to": "新标题"}},
        )
    )
    view = replay_session(events)
    assert view["title"] == "新标题"


def test_replay_missing_meta_keeps_defaults():
    # 仅 message.appended（无 session.created）→ 顶层缺失字段如实置空/默认
    events = [_event(1, EVENT_MESSAGE_APPENDED, index=0, role="user", content="hi")]
    view = replay_session(events)
    assert view["version"] is None
    assert view["title"] == ""
    assert view["pinned"] is False
    assert view["session_id"] == "s1"  # 事件必填字段兜底


def test_replay_unknown_type_counted():
    events = _events_from_session(_source_session())
    events.append(_event(99, "ghost.type", x=1))
    view = replay_session(events)
    assert view["unknown_event_types"] == ["ghost.type"]


def test_replay_seq_gap_annotated():
    src = _source_session()
    events = _events_from_session(src)
    # 制造缺口：把第二条消息的 seq 从 3 改到 10
    events = [
        Event(
            event_id=e.event_id,
            session_id=e.session_id,
            seq=10,
            type=e.type,
            ts=e.ts,
            payload=e.payload,
        )
        if e.type == EVENT_MESSAGE_APPENDED and e.payload.get("index") == 1
        else e
        for e in events
    ]
    view = replay_session(events)
    assert "event_log_gaps" in view
    total_missing = sum(g["missing"] for g in view["event_log_gaps"])
    assert total_missing > 0


def test_replay_empty_events_not_faked():
    view = replay_session([])
    assert view == {"exists": False}


def test_replay_forked_reserved_noop():
    events = _events_from_session(_source_session())
    events.append(_event(99, "session.forked", parent_id="p1", branch_id="b1", fork_point=0))
    view = replay_session(events)
    # 预留类型不触发行为：无额外标注

    assert view["session_id"] == "s1"


def test_replay_idx_conflict_keeps_all_messages():
    """2026-08-21 修复: run 中断导致 idx 重复 → replay 按 seq 保留全部（不覆盖）.

    回归: 180c662a 事故——"评估"和"继续"两条 user 消息都 idx=4, 原实现
    按 idx 排序后到覆盖先到 → 丢任务; 修复后按 seq 顺序收集 → 全部保留。
    """
    from llm_loop.event_log.replay import replay_session

    class E:
        def __init__(self, seq, sid, typ, payload):
            self.seq = seq
            self.session_id = sid
            self.type = typ
            self.payload = payload

    events = [
        E(1, "sid", "session.created", {"session_id": "sid"}),
        E(2, "sid", "message.appended", {"index": 0, "role": "user", "content": "第一个问题"}),
        E(3, "sid", "message.appended", {"index": 1, "role": "assistant", "content": "回答1"}),
        # 中断后恢复: idx 回到 1（内存回滚）, 新消息 idx 冲突
        E(4, "sid", "message.appended", {"index": 1, "role": "user", "content": "继续任务"}),
    ]
    view = replay_session(events)
    msgs = view.get("messages", [])
    contents = [str(m.get("content", "")) for m in msgs]
    assert "第一个问题" in contents, "第一条 user 应保留"
    assert "继续任务" in contents, "冲突 idx 的后续消息也应保留（不覆盖）"
    assert contents.index("第一个问题") < contents.index("继续任务"), "顺序应按 seq"


def test_replay_version5_summary_meta_change():
    events = [
        _event(1, EVENT_SESSION_CREATED, version=5, fixed_summary="", summary_chain=[]),
        _event(
            2,
            EVENT_SESSION_META_CHANGED,
            field="summary_state",
            changes={
                "fixed_summary": {"from": "", "to": "固定"},
                "summary_chain": {"from": [], "to": ["一", "二"]},
            },
        ),
    ]
    view = replay_session(events)
    assert view["fixed_summary"] == "固定"
    assert view["summary_chain"] == ["一", "二"]
