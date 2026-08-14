"""单元测试: D1 事件模型与事件日志存储（design.md §2.4.1）.

覆盖:
- 模型: serialize→parse 往返逐字段一致；损坏行返回 None（fail-open）；
  未登记类型 validate 报违规；登记表覆盖 5 类事件且字段语义可查询
- 存储: seq 从 1 递增不重号；JSONL 合法且不可变（追加修改被拒绝）；
  多进程并发 append 同会话无行交错；损坏行跳过计数；enabled=False 零写入
"""

from __future__ import annotations

import json
import multiprocessing
import os

from llm_loop.event_log.model import (
    EVENT_CONTEXT_COMPRESSED,
    EVENT_MESSAGE_APPENDED,
    EVENT_REQUEST_META,
    EVENT_SESSION_CREATED,
    EVENT_SESSION_FORKED,
    EVENT_SESSION_META_CHANGED,
    REGISTRY,
    Event,
    parse_event_line,
    serialize_event,
    validate_event_type,
)
from llm_loop.event_log.store import EventStore


def _make_event(seq: int = 1, type_: str = EVENT_MESSAGE_APPENDED, **payload) -> Event:
    return Event(
        event_id=f"evt-{seq}",
        session_id="s1",
        seq=seq,
        type=type_,
        ts="2026-08-14T00:00:00+00:00",
        payload=payload or {"index": seq - 1, "role": "user", "content": "hi"},
    )


# ── 模型: 序列化/解析 ──

def test_event_serialize_parse_roundtrip():
    ev = _make_event(
        seq=3,
        type_=EVENT_MESSAGE_APPENDED,
        index=2,
        role="assistant",
        content="回答，含中文",
        source="user",
        reasoning_content="思考链",
        metadata={"truncated": True},
    )
    line = serialize_event(ev)
    # 单行 JSONL 语义：无内嵌换行
    assert "\n" not in line
    parsed = parse_event_line(line)
    assert parsed is not None
    assert parsed.event_id == ev.event_id
    assert parsed.session_id == ev.session_id
    assert parsed.seq == ev.seq
    assert parsed.type == ev.type
    assert parsed.ts == ev.ts
    assert parsed.payload == ev.payload
    # ensure_ascii=False
    assert "思考链" in line


def test_parse_event_line_corrupt_returns_none():
    assert parse_event_line("not json{{{") is None
    assert parse_event_line("") is None
    assert parse_event_line("123") is None
    assert parse_event_line('{"event_id": "x"}') is None  # 缺 session_id
    assert parse_event_line('{"event_id": "x", "session_id": "s", "seq": "bad", "type": "t", "ts": "ts"}') is None
    assert parse_event_line('{"event_id": "x", "session_id": "s", "seq": 0, "type": "t", "ts": "ts"}') is None


def test_validate_event_type_unregistered():
    ev = _make_event(type_="not.registered")
    problems = validate_event_type(ev)
    assert problems and "未登记" in problems[0]
    # 已登记类型 → 合法
    assert validate_event_type(_make_event(type_=EVENT_SESSION_CREATED)) == []


# ── 模型: 类型登记表 ──

def test_registry_covers_five_types_with_fields():
    names = {
        EVENT_SESSION_CREATED,
        EVENT_MESSAGE_APPENDED,
        EVENT_CONTEXT_COMPRESSED,
        EVENT_SESSION_META_CHANGED,
        EVENT_SESSION_FORKED,
        EVENT_REQUEST_META,  # HARNESS-02: request.meta 请求快照
    }
    assert set(REGISTRY.registered()) == names
    # 字段语义可查询
    msg_spec = REGISTRY.spec(EVENT_MESSAGE_APPENDED)
    assert msg_spec is not None
    assert msg_spec.version >= 1
    assert "index" in msg_spec.fields and "reasoning_content" in msg_spec.fields
    comp_spec = REGISTRY.spec(EVENT_CONTEXT_COMPRESSED)
    assert comp_spec is not None
    assert {"archive_ref", "tool_call_id", "msg_seq", "chars"} <= set(comp_spec.fields)


def test_registry_unregistered_spec_none():
    assert REGISTRY.spec("ghost.type") is None


# ── 存储: EventStore ──

def test_append_seq_increments_without_duplicate(tmp_path):
    store = EventStore(tmp_path / "logs")
    e1 = store.append("s1", EVENT_MESSAGE_APPENDED, {"index": 0, "role": "user"})
    e2 = store.append("s1", EVENT_MESSAGE_APPENDED, {"index": 1, "role": "assistant"})
    e3 = store.append("s1", EVENT_MESSAGE_APPENDED, {"index": 2, "role": "tool"})
    assert [e1.seq, e2.seq, e3.seq] == [1, 2, 3]
    assert e1.event_id != e2.event_id
    assert e1.session_id == "s1"
    assert store.last_seq("s1") == 3
    assert store.exists("s1")
    assert not store.exists("s-other")


def test_append_jsonl_valid_and_immutable(tmp_path):
    store = EventStore(tmp_path / "logs")
    store.append("s1", EVENT_MESSAGE_APPENDED, {"index": 0, "role": "user"})
    p = tmp_path / "logs" / "s1.jsonl"
    # 每行一个合法 JSON 事件
    for raw in p.read_text(encoding="utf-8").splitlines():
        data = json.loads(raw)
        assert data["session_id"] == "s1"
        assert data["seq"] >= 1
    # append-only：既有内容不可被修改（文件重写被拒绝于语义层——追加后原内容原样保留）
    before = p.read_bytes()
    store.append("s1", EVENT_MESSAGE_APPENDED, {"index": 1, "role": "assistant"})
    after = p.read_bytes()
    assert after.startswith(before)  # 原内容前缀保留（append-only）
    assert before != after  # 有新行追加


def test_read_missing_file_empty(tmp_path):
    store = EventStore(tmp_path / "logs")
    assert store.read("ghost") == []
    assert store.last_seq("ghost") == 0


def test_read_skips_corrupt_lines_with_count(tmp_path):
    store = EventStore(tmp_path / "logs")
    store.append("s1", EVENT_MESSAGE_APPENDED, {"index": 0, "role": "user"})
    p = tmp_path / "logs" / "s1.jsonl"
    with p.open("a", encoding="utf-8") as f:
        f.write("{corrupt line}\n")
        f.write('{"seq": 5, "type": "bad"}\n')  # 缺必填字段 → 结构非法
    store.append("s1", EVENT_MESSAGE_APPENDED, {"index": 1, "role": "assistant"})
    events = store.read("s1")
    assert len(events) == 2  # 损坏行如实跳过
    assert store.last_read_skipped >= 2
    # last_seq 以可解析事件为准（容错），损坏行不参与续号
    assert [e.seq for e in events] == [1, 2]


def test_enabled_false_zero_write(tmp_path):
    store = EventStore(tmp_path / "logs", enabled=False)
    result = store.append("s1", EVENT_MESSAGE_APPENDED, {"index": 0})
    assert result is None
    assert not store.exists("s1")
    assert not (tmp_path / "logs").exists()


def _worker_append(logs_dir: str, out_q) -> None:
    """模块级 worker（spawn 可 pickle）：并发向同一会话追加事件."""
    store = EventStore(logs_dir)
    ok = True
    for i in range(30):
        ev = store.append("s1", EVENT_MESSAGE_APPENDED, {"w": os.getpid(), "i": i})
        if ev is None:
            ok = False
    out_q.put(ok)


def test_append_multiprocess_no_interleaving(tmp_path):
    """多进程并发 append 同会话：flock 写锁保证每行不交错."""
    logs_dir = str(tmp_path / "logs")

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    procs = [ctx.Process(target=_worker_append, args=(logs_dir, q)) for _ in range(3)]
    for p_ in procs:
        p_.start()
    for p_ in procs:
        p_.join()
    results = [q.get() for _ in procs]
    assert all(results), "并发 append 存在失败"

    store = EventStore(logs_dir)
    events = store.read("s1")
    assert len(events) == 90
    # 每行均可独立解析（无交错）且 seq 唯一连续
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == 90
    assert seqs == list(range(1, 91))


# ── HARNESS-02: request.meta 请求快照事件 ──


def test_request_meta_event_written_per_round(tmp_path):
    """引擎每轮 LLM 调用前写 request.meta（模型/思考/工具数/预算快照，fail-open）."""
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.message import ToolCall
    from llm_loop.core.session import SessionStore
    from llm_loop.event_log.store import EventStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.tools.registry import ToolRegistry

    class _Fake:
        def __init__(self) -> None:
            self.calls = 0

        def _next(self):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    content="用工具",
                    tool_calls=[
                        ToolCall(id="tc-m", name="read_file", arguments={"path": "a"})
                    ],
                    provider="fake",
                )
            return LLMResponse(content="完成", tool_calls=[], provider="fake")

        def chat(self, messages, tools, **kw):
            return self._next()

        def chat_stream(self, messages, tools, **kw):
            def _gen():
                yield from ()
                return self._next()

            return _gen()

    reg = ToolRegistry()
    reg.register(
        type(
            "RF",
            (),
            {"name": "read_file", "description": "t", "parameters": {"type": "object"}},
        )()
    )
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    ev_dir = tmp_path / "events"
    event_store = EventStore(ev_dir)
    sess_dir = tmp_path / "sessions"
    store = SessionStore(sess_dir, event_store=event_store)
    engine = LoopEngine(
        llm_client=_Fake(),  # type: ignore[arg-type]
        registry=reg,  # type: ignore[arg-type]
        memory=None,  # type: ignore[arg-type]
        session=store,
        settings=settings,
        event_store=event_store,
    )
    result = engine.run_single("任务")
    assert result.final_answer
    events = event_store.read(result.session_id)
    metas = [e for e in events if e.type == "request.meta"]
    assert len(metas) == 2  # 两轮各一次
    assert metas[0].payload["model"]  # 模型标签如实记录（测试环境无 pool 时为回退标签，非空即可）
    assert metas[0].payload["round"] == 1
    assert metas[1].payload["round"] == 2
    assert "tools_count" in metas[0].payload
    assert "budget" in metas[0].payload


def test_request_meta_registered_replay_ignored(tmp_path):
    """回放对已登记但视图不消费的 request.meta → 静默跳过，消息重建不受影响（replay 兼容）."""
    from llm_loop.event_log.model import EVENT_REQUEST_META
    from llm_loop.event_log.replay import replay_session
    from llm_loop.event_log.store import EventStore

    ev_dir = tmp_path / "events"
    store = EventStore(ev_dir)
    sid = "s-request-meta"
    store.append(sid, EVENT_REQUEST_META, {"round": 1, "model": "m"})
    store.append(
        sid,
        "session.created",
        {
            "version": 4,
            "title": "t",
            "created_at": "2026-08-14T00:00:00+00:00",
            "updated_at": "2026-08-14T00:00:00+00:00",
            "status": "active",
            "parent_id": None,
            "branch_id": None,
            "branch_summary": None,
            "model_override": None,
            "pinned": False,
            "channel": "cli",
        },
    )
    view = replay_session(list(store.read(sid)))
    assert view["session_id"] == sid  # 视图正常重建
    assert "unknown_event_types" not in view  # 已登记类型不记 unknown
    assert view["messages"] == []  # request.meta 不产生消息
