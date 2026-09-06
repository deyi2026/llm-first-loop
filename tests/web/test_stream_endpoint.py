"""Web 流式端点测试（spec 5.2 / design §2.4.2 / tasks 2.6）.

断言:
1. POST /api/v1/chat/stream 输出 answer_delta* → done 事件序列
2. done.data 含完整九字段
3. 引擎异常 → error 事件（不伪造 done）
4. ChatResponse 九字段零改动（schemas.py 对比）
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from llm_loop.web import build_app
from tests.unit.test_stream_equivalence import StreamingFakeLLM


def test_resume_without_background_runner_never_executes_placeholder(build_test_engine):
    """resume is subscription-only; direct-run fallback must never become human ingress."""
    engine, fake = build_test_engine([{"content": "must-not-run"}])
    sid = engine.session.create()
    client = TestClient(build_app(engine=engine))

    resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "（恢复连接）", "session_id": sid, "resume": True},
    )

    assert resp.status_code == 200
    assert '"type": "error"' in resp.text
    assert "no_active_run" in resp.text
    assert len(fake.calls) == 0

CHAT_RESPONSE_FIELDS = [
    "session_id",
    "final_answer",
    "verification_note",
    "rounds",
    "tool_calls",
    "truncated",
    "model_used",
    "fallback_receipt",
    "tokens_in",
    "tokens_out",
    "tokens_cache_hit",
    "reasoning_content",
    "reasoning_mode",
    "reasoning_capable",
    "reasoning_control",
    "reasoning_supported",
    "reasoning_effective",
    "reasoning_tokens",
]


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def test_chat_stream_emits_deltas_then_done(build_test_engine):
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = StreamingFakeLLM("你好世界")
    client = _make_client(engine)
    resp = client.post("/api/v1/chat/stream", json={"message": "hi"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    assert events, "无事件输出"
    assert events[0]["type"] == "answer_delta"
    assert events[-1]["type"] == "done"
    joined = "".join(e["data"]["data"] for e in events if e["type"] == "answer_delta")
    done = events[-1]["data"]
    assert joined == "你好世界"
    assert done["final_answer"] == "你好世界"


def test_chat_stream_done_has_complete_runtime_fields(build_test_engine):
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = StreamingFakeLLM("回答")
    client = _make_client(engine)
    resp = client.post("/api/v1/chat/stream", json={"message": "hi"})
    events = _parse_sse(resp.text)
    done = events[-1]["data"]
    for f in CHAT_RESPONSE_FIELDS:
        assert f in done, f"done.data 缺字段 {f}"


def test_chat_stream_engine_error(build_test_engine):
    def boom(_calls):
        raise RuntimeError("fake engine failure")

    engine, _ = build_test_engine([boom])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat/stream", json={"message": "x"})
    events = _parse_sse(resp.text)
    assert events[-1]["type"] == "error"
    assert "fake engine failure" in events[-1]["data"]["detail"]


def test_chat_response_schema_unchanged():
    from pathlib import Path

    schemas = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "llm_loop"
        / "web"
        / "schemas.py"
    ).read_text(encoding="utf-8")
    for f in CHAT_RESPONSE_FIELDS:
        assert f in schemas, f"ChatResponse 缺字段 {f}"


class TestFrontendStreamConsumption:
    """前端真流式消费静态断言（tasks 2.7）."""

    def test_stream_chat_request_defined(self, app_js_src: str):
        assert "async function streamChatRequest" in app_js_src
        assert 'fetch("/api/v1/chat/stream"' in app_js_src
        assert "getReader" in app_js_src
        assert "answer_delta" in app_js_src


def test_chat_stream_background_runner_mode(build_test_engine):
    """审查 P2: 装配后台 runner 时流式端点走订阅路径（done 终态正常送达）."""
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = StreamingFakeLLM("后台回答")
    from llm_loop.core.loop.runner import BackgroundRunner
    engine.runner = BackgroundRunner(engine, enabled=True)
    client = _make_client(engine)
    resp = client.post("/api/v1/chat/stream", json={"message": "hi"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events and events[-1]["type"] == "done", f"后台模式无 done 终态: {events[-1] if events else 'empty'}"
    done = events[-1]["data"]
    assert done["final_answer"] == "后台回答"


def test_chat_stream_background_disabled_fallback(build_test_engine):
    """审查 P2: runner disabled → 回退旧直驱（done 仍正常）."""
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = StreamingFakeLLM("直驱回答")
    from llm_loop.core.loop.runner import BackgroundRunner
    engine.runner = BackgroundRunner(engine, enabled=False)
    client = _make_client(engine)
    resp = client.post("/api/v1/chat/stream", json={"message": "hi"})
    events = _parse_sse(resp.text)
    assert events[-1]["type"] == "done"
    assert events[-1]["data"]["final_answer"] == "直驱回答"


def test_chat_stream_busy_does_not_persist_model_override(build_test_engine):
    """后台 run 拒绝 busy 请求时必须零副作用：不得修改会话模型 override。"""
    engine, _ = build_test_engine([])
    sid = engine.session.create()

    class _BusyRunner:
        enabled = True

        def start(
            self, session_id, message, model=None, reasoning_effort=None, *,
            reasoning_mode=None, resume=False, before_start=None, expected_workspace_epoch=None,
            ingress=None,
        ):
            return None, None

        def get_handle(self, session_id):
            return {"session_id": session_id, "status": "running", "started_at": 1.0}

        def unsubscribe(self, session_id, q):
            return None

    engine.runner = _BusyRunner()
    client = _make_client(engine)
    resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "busy", "session_id": sid, "model": "fake-model"},
    )
    assert "session_busy" in resp.text
    assert engine.session.load(sid).model_override is None


def test_chat_stream_accepted_persists_canonical_model_override(build_test_engine):
    """真正接单的后台流仍持久化 Web 模型选择，供飞书/CLI 后续共享。"""
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = StreamingFakeLLM("ok")
    for pid in list(engine.llm_pool._provider_cache):
        engine.llm_pool._provider_cache[pid] = engine.llm_pool.default_client
    from llm_loop.core.loop.runner import BackgroundRunner

    engine.runner = BackgroundRunner(engine, enabled=True)
    sid = engine.session.create()
    pid, mid = engine.llm_pool.registry.resolve("fake-model")
    expected = f"{pid}/{mid}"
    client = _make_client(engine)
    resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "hi", "session_id": sid, "model": "fake-model"},
    )
    assert resp.status_code == 200
    assert _parse_sse(resp.text)[-1]["type"] == "done"
    assert engine.session.load(sid).model_override == expected


class _EffortRecordingLLM(StreamingFakeLLM):
    def __init__(self, content: str) -> None:
        super().__init__(content)
        self.efforts_seen: list[str] = []

    def chat_stream(self, messages, tools, *, timeout_s=None, model=None):
        from llm_loop.core.run_context import current_reasoning_effort

        self.efforts_seen.append(current_reasoning_effort.get())
        return super().chat_stream(messages, tools, timeout_s=timeout_s, model=model)


def test_chat_stream_reasoning_effort_reaches_background_runner(build_test_engine):
    engine, _ = build_test_engine([])
    recorder = _EffortRecordingLLM("后台 effort")
    engine.llm_pool.default_client = recorder
    from llm_loop.core.loop.runner import BackgroundRunner

    engine.runner = BackgroundRunner(engine, enabled=True)
    client = _make_client(engine)
    resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "hi", "reasoning_effort": "low"},
    )
    assert _parse_sse(resp.text)[-1]["type"] == "done"
    assert recorder.efforts_seen == ["low"]
    assert recorder.reasoning_effort == "high", "请求 override 不得改共享 client 默认"


def test_chat_stream_reasoning_effort_reaches_direct_fallback(build_test_engine):
    engine, _ = build_test_engine([])
    recorder = _EffortRecordingLLM("直驱 effort")
    engine.llm_pool.default_client = recorder
    from llm_loop.core.loop.runner import BackgroundRunner

    engine.runner = BackgroundRunner(engine, enabled=False)
    client = _make_client(engine)
    resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "hi", "reasoning_effort": "medium"},
    )
    assert _parse_sse(resp.text)[-1]["type"] == "done"
    assert recorder.efforts_seen == ["medium"]
    assert recorder.reasoning_effort == "high"


def test_chat_stream_new_session_wins_over_session_id(build_test_engine):
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = StreamingFakeLLM("新会话")
    old_sid = engine.session.create()
    client = _make_client(engine)
    resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "hi", "session_id": old_sid, "new_session": True},
    )
    done = _parse_sse(resp.text)[-1]["data"]
    assert done["session_id"] != old_sid
    assert engine.session.get_shared_current() == done["session_id"]


def test_chat_stream_cross_process_busy_has_no_model_side_effect(build_test_engine):
    from llm_loop.core.loop.runner import BackgroundRunner
    from llm_loop.core.session import SessionStore

    engine, _ = build_test_engine([])
    engine.runner = BackgroundRunner(engine, enabled=True)
    sid = engine.session.create()
    blocker = SessionStore(engine.session._dir)  # noqa: SLF001 — 模拟另一服务进程
    client = _make_client(engine)
    with blocker.run_lease(sid) as acquired:
        assert acquired is True
        resp = client.post(
            "/api/v1/chat/stream",
            json={"message": "busy", "session_id": sid, "model": "fake-model"},
        )
    events = _parse_sse(resp.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["data"]["error"] == "session_busy"
    assert engine.session.load(sid).model_override is None


def test_chat_stream_direct_cross_process_busy_has_no_model_side_effect(build_test_engine):
    from llm_loop.core.loop.runner import BackgroundRunner
    from llm_loop.core.session import SessionStore

    engine, _ = build_test_engine([])
    engine.runner = BackgroundRunner(engine, enabled=False)
    sid = engine.session.create()
    blocker = SessionStore(engine.session._dir)  # noqa: SLF001
    client = _make_client(engine)
    with blocker.run_lease(sid) as acquired:
        assert acquired is True
        resp = client.post(
            "/api/v1/chat/stream",
            json={"message": "busy", "session_id": sid, "model": "fake-model"},
        )
    events = _parse_sse(resp.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["data"]["error"] == "session_busy"
    assert engine.session.load(sid).model_override is None


def test_chat_stream_rejects_session_if_workspace_changes_before_background_admission(
    build_test_engine, tmp_path, monkeypatch
):
    """session在A解析后、runner.start前切到B时必须拒绝，不能把A的sid带入B。"""
    from llm_loop.core.loop.runner import BackgroundRunner

    engine, _ = build_test_engine([])
    workspace_a = tmp_path / "epoch-a"
    workspace_b = tmp_path / "epoch-b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    engine.set_workspace(str(workspace_a), "epoch-a")
    sid = engine.session.create()
    root_a = engine.session.root

    runner = BackgroundRunner(engine, enabled=True)
    engine.runner = runner
    original_start = runner.start
    switched = False

    def switch_then_start(*args, **kwargs):
        nonlocal switched
        if not switched:
            engine.set_workspace(str(workspace_b), "epoch-b")
            switched = True
        return original_start(*args, **kwargs)

    monkeypatch.setattr(runner, "start", switch_then_start)
    client = _make_client(engine)
    resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "must-not-cross-workspace", "session_id": sid},
    )
    events = _parse_sse(resp.text)

    assert switched is True
    assert events[-1]["type"] == "error"
    assert events[-1]["data"]["error"] == "workspace_changed"
    assert (root_a / f"{sid}.json").exists()
    assert not (engine.settings.sessions_dir / "epoch-b" / f"{sid}.json").exists()
