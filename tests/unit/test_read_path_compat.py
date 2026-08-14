"""单元测试: D1 读路径零变化 + 写路径挂接（design.md §2.4.1 / spec §5.4 / tasks §7.3/§9.1）.

覆盖:
- 迁移前后 `SessionStore.load(sid).to_dict()` 语义逐字节一致（键排序后）
- 迁移前后 `build_history_messages(...)` 输出一致（web/feishu/history 读路径）
- 迁移前后 `list_sessions()` / `get_meta()` 一致（CLI/Web 会话列表）
- web 归档展开 `ArchiveStore.get_by_tool_call_id` 迁移后仍可经引用取回原文
- 写路径挂接（零回归红线）:
  - save() 兜底钩子默认 None 零行为
  - event_log_enabled=False 时 engine 正常跑且事件目录零写入
  - 开启时消息落库生成 session.created + message.appended 事件
  - 事件写入抛异常时主循环不中断（fail-open 断言）
"""

from __future__ import annotations

import json

from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.core.session import Session, SessionStore
from llm_loop.event_log.migrate import run_migration
from llm_loop.event_log.store import EventStore
from llm_loop.memory.archive import ArchiveStore


def _write_source_session(sessions_dir, sid: str = "s1", n_messages: int = 3) -> None:
    """构造完整字段会话源（模拟真实存量 session JSON）."""
    sessions_dir.mkdir(parents=True, exist_ok=True)
    messages = [
        Message(role="user", content="问题", source=MessageSource.USER),
        Message(
            role="tool",
            content="[状态: success] 结果",
            source=MessageSource.TOOL,
            tool_call_id="c1",
            status=ToolResultStatus.SUCCESS,
            tool_name="f1",
        ),
        Message(
            role="assistant",
            content="回答",
            source=MessageSource.USER,
            reasoning_content="思考",
        ),
    ][:n_messages]
    session = Session(
        session_id=sid,
        messages=messages,
        created_at="2026-08-14T00:00:00",
        title="读路径会话",
        updated_at="2026-08-14T00:01:00",
        pinned=True,
        channel="web",
    )
    (sessions_dir / f"{sid}.json").write_text(
        json.dumps(session.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return session.to_dict()


def _canonical(raw: dict) -> str:
    """键排序后序列化（语义逐字节一致的稳健比较）."""
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# ── 读路径零变化（tasks §9.1）──

def test_migration_preserves_session_load_byte_identical(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    _write_source_session(sessions_dir)
    store = SessionStore(sessions_dir)

    before = _canonical(store.load("s1").to_dict())
    rep = run_migration(sessions_dir, logs_dir)
    assert rep.migrated == 1
    after = _canonical(store.load("s1").to_dict())
    assert before == after
    # 与源 JSON 语义一致（读路径未因迁移改变）
    source = json.loads((sessions_dir / "s1.json").read_text(encoding="utf-8"))
    assert after == _canonical(source)


def test_migration_preserves_build_history_messages(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    _write_source_session(sessions_dir)
    store = SessionStore(sessions_dir)

    def _history(sid: str) -> list[dict]:
        sess = store.load(sid)
        return build_history_messages(
            sess.messages,
            "你是助手",
            max_chars=1000000,
            session_id=sid,
        )

    before = _canonical({"m": _history("s1")})
    rep = run_migration(sessions_dir, logs_dir)
    assert rep.migrated == 1
    after = _canonical({"m": _history("s1")})
    assert before == after


def test_migration_preserves_list_and_meta(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    _write_source_session(sessions_dir, "s1")
    _write_source_session(sessions_dir, "s2")
    store = SessionStore(sessions_dir)

    before = {
        "list": [m.to_dict() for m in store.list_sessions(include_archived=True)],
        "meta": store.get_meta("s1").to_dict() if store.get_meta("s1") else None,
    }
    rep = run_migration(sessions_dir, logs_dir)
    assert rep.migrated == 2
    after = {
        "list": [m.to_dict() for m in store.list_sessions(include_archived=True)],
        "meta": store.get_meta("s1").to_dict() if store.get_meta("s1") else None,
    }
    assert _canonical(before) == _canonical(after)


def test_archive_get_by_tool_call_id_after_migration(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    archives_dir = tmp_path / "archives"
    _write_source_session(sessions_dir)

    # 构造压缩档案（超长原文另存，tool_call_id 索引）
    archive = ArchiveStore(archives_dir)
    entry = archive.archive(
        "s1",
        role="tool",
        source="tool",
        content="超长原文内容" * 10,
        tool_name="f1",
        tool_call_id="c1",
        status="success",
    )

    rep = run_migration(sessions_dir, logs_dir)
    assert rep.migrated == 1
    # 迁移后经引用仍可取回原文（web 归档展开数据源，spec §5.4.1-3）
    found = archive.get_by_tool_call_id("s1", "c1")
    assert found is not None
    assert found.get("content") == entry.content
    assert found.get("tool_call_id") == "c1"
    # 无引用 → None（如实降级）
    assert archive.get_by_tool_call_id("s1", "ghost") is None


# ── 写路径挂接（tasks §7.3，零回归红线）──

def test_save_backfill_default_none_zero_behavior(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    store = SessionStore(sessions_dir)  # event_store 默认 None
    session = Session(session_id="s1", messages=[Message(role="user", content="hi", source=MessageSource.USER)])
    store.save(session)
    assert store.exists("s1")
    assert not logs_dir.exists()  # 未注入事件存储 → 零行为，不创建事件目录


def test_save_backfill_disabled_zero_write(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    store = SessionStore(sessions_dir, event_store=EventStore(logs_dir, enabled=False))
    session = Session(session_id="s1", messages=[Message(role="user", content="hi", source=MessageSource.USER)])
    store.save(session)
    assert store.exists("s1")
    assert not logs_dir.exists()  # event_log_enabled=False → 事件目录零写入


def test_save_backfill_enabled_generates_events(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    store = SessionStore(sessions_dir, event_store=EventStore(logs_dir))
    session = Session(
        session_id="s1",
        messages=[
            Message(role="user", content="hi", source=MessageSource.USER),
            Message(role="assistant", content="回答", source=MessageSource.USER),
        ],
    )
    store.save(session)
    event_store = EventStore(logs_dir)
    events = event_store.read("s1")
    types = [e.type for e in events]
    assert "session.created" in types
    assert types.count("message.appended") == 2  # 消息数与事件一致（兜底覆盖）


def test_save_backfill_appends_missing_message_events(tmp_path):
    """tasks §7.3: 事件日志已存在但消息数增长（迁移后引擎继续追加）→ 兜底补缺失事件，零重复."""
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    store = SessionStore(sessions_dir, event_store=EventStore(logs_dir))
    store.save(Session(
        session_id="s1",
        messages=[
            Message(role="user", content="hi", source=MessageSource.USER),
            Message(role="assistant", content="回答", source=MessageSource.USER),
        ],
    ))
    event_store = EventStore(logs_dir)
    assert len(event_store.read("s1")) == 3

    # 追加 1 条消息再 save → 兜底补 index=2 的事件，不重复既有事件
    session = store.load("s1")
    session.messages.append(Message(role="assistant", content="追加回答", source=MessageSource.USER))
    store.save(session)
    events = event_store.read("s1")
    assert len(events) == 4
    appended = [e for e in events if e.type == "message.appended"]
    assert [e.payload.get("index") for e in appended] == [0, 1, 2]
    assert appended[2].payload.get("content") == "追加回答"


def test_event_write_exception_fail_open(tmp_path):
    sessions_dir = tmp_path / "sessions"

    class BoomStore:
        enabled = True

        def append(self, *a, **k):
            raise RuntimeError("事件写入故障")

        def exists(self, *a, **k):
            return False

    store = SessionStore(sessions_dir, event_store=BoomStore())
    session = Session(session_id="s1", messages=[Message(role="user", content="hi", source=MessageSource.USER)])
    store.save(session)  # 事件写入抛异常 → save 不中断（fail-open）
    assert store.exists("s1")


def test_engine_event_log_disabled_zero_write(build_test_engine, tmp_path):
    logs_dir = tmp_path / "event_logs"
    store = EventStore(logs_dir, enabled=False)
    engine, _fake = build_test_engine([{"content": "你好"}])
    engine._event_store = store  # noqa: SLF001 — 测试注入事件存储
    engine.session._event_store = store  # noqa: SLF001
    for _ in engine.run_stream("s1", "你好"):
        pass  # 主循环正常跑完（FakeLLM 无 chat_stream → 同步路径不 yield）
    assert engine.session.exists("s1")
    assert not logs_dir.exists() or list(logs_dir.glob("*.jsonl")) == []  # 事件目录零写入


def test_engine_event_log_enabled_generates_events(build_test_engine, tmp_path):
    logs_dir = tmp_path / "event_logs"
    store = EventStore(logs_dir)
    engine, _fake = build_test_engine([{"content": "你好"}])
    engine._event_store = store  # noqa: SLF001
    engine.session._event_store = store  # noqa: SLF001
    list(engine.run_stream("s1", "你好"))
    assert store.exists("s1")
    types = [e.type for e in store.read("s1")]
    assert "session.created" in types
    assert types.count("message.appended") >= 2  # 用户消息 + 最终回答


def test_engine_event_write_exception_fail_open(build_test_engine, tmp_path):
    class BoomStore:
        enabled = True

        def append(self, *a, **k):
            raise RuntimeError("事件写入故障")

        def exists(self, *a, **k):
            return False

    engine, _fake = build_test_engine([{"content": "你好"}])
    engine._event_store = BoomStore()  # noqa: SLF001
    engine.session._event_store = BoomStore()  # noqa: SLF001
    for _ in engine.run_stream("s1", "你好"):  # 事件写入异常不抛穿主循环
        pass
    assert engine.session.exists("s1")
