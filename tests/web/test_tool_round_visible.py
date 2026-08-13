"""P2-1 流式期间工具调用可见 Web 集成测试（tasks 4.5-4.11）."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse, StreamDelta
from llm_loop.web import build_app


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


class _MultiRoundStreamFake:
    """多轮流式 FakeLLM（Web 集成测试用）。"""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.model = "fake-model"
        self.timeout_s = 120.0
        self.thinking_mode = True
        self.reasoning_effort = "high"
        self.thinking_supported = True

    def chat(self, messages, tools, *, timeout_s=None, model=None) -> LLMResponse:
        self.calls.append({"messages": messages, "model": model})
        return self._responses.pop(0) if self._responses else LLMResponse(content="", tool_calls=[], provider="fake")

    def chat_stream(self, messages, tools, *, timeout_s=None, model=None):
        self.calls.append({"messages": messages, "model": model})
        resp = self._responses.pop(0) if self._responses else LLMResponse(content="", tool_calls=[], provider="fake")
        for ch in (resp.content or ""):
            yield StreamDelta(text=ch)
        return resp


def test_sse_tool_round_event(build_test_engine, tmp_path):
    """4.5: SSE 流推送 tool_round 事件 + done 含完整 tool_calls。"""
    f = tmp_path / "test.txt"
    f.write_text("content", encoding="utf-8")

    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = _MultiRoundStreamFake([
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": str(f)})], provider="fake"),
        LLMResponse(content="done", tool_calls=[], provider="fake"),
    ])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat/stream", json={"message": "read test.txt"})
    events = _parse_sse(resp.text)

    tool_round_events = [e for e in events if e["type"] == "tool_round"]
    assert len(tool_round_events) == 1
    data = tool_round_events[0]["data"]
    assert data["tool_name"] == "read_file"
    assert data["round_index"] == 1
    assert data["tool_call_id"] == "c1"
    assert "path" in data["args_summary"]

    done = [e for e in events if e["type"] == "done"]
    assert done, "无 done 事件"
    assert len(done[0]["data"]["tool_calls"]) == 1


def test_sse_multi_round_tool_round(build_test_engine, tmp_path):
    """4.6: 多轮工具调用 N 个 tool_round 事件，round_index 递增。"""
    f1 = tmp_path / "a.txt"
    f1.write_text("A", encoding="utf-8")
    f2 = tmp_path / "b.txt"
    f2.write_text("B", encoding="utf-8")

    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = _MultiRoundStreamFake([
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": str(f1)})], provider="fake"),
        LLMResponse(content="", tool_calls=[ToolCall(id="c2", name="read_file", arguments={"path": str(f2)})], provider="fake"),
        LLMResponse(content="done", tool_calls=[], provider="fake"),
    ])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat/stream", json={"message": "read a and b"})
    events = _parse_sse(resp.text)

    tool_round_events = [e for e in events if e["type"] == "tool_round"]
    assert len(tool_round_events) == 2
    assert tool_round_events[0]["data"]["round_index"] == 1
    assert tool_round_events[1]["data"]["round_index"] == 2

    done = [e for e in events if e["type"] == "done"]
    assert len(done[0]["data"]["tool_calls"]) == 2


def test_done_convergence(build_test_engine, tmp_path):
    """4.7: done 后 tool_calls 完整轨迹不变（终态工具链接管）。"""
    f = tmp_path / "test.txt"
    f.write_text("content", encoding="utf-8")

    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = _MultiRoundStreamFake([
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": str(f)})], provider="fake"),
        LLMResponse(content="final answer", tool_calls=[], provider="fake"),
    ])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat/stream", json={"message": "read test.txt"})
    events = _parse_sse(resp.text)

    tool_round_events = [e for e in events if e["type"] == "tool_round"]
    done_events = [e for e in events if e["type"] == "done"]
    assert tool_round_events, "流式期间有 tool_round 事件"
    assert done_events, "有 done 事件"
    assert done_events[0]["data"]["tool_calls"], "done 携带完整 tool_calls"
    assert done_events[0]["data"]["final_answer"] == "final answer"


def test_old_frontend_compat_static():
    """4.8: 旧前端兼容静态断言（onToolRound 可选，tool_round 事件可忽略）。"""
    app_js = (
        Path(__file__).resolve().parents[2] / "src" / "llm_loop" / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    assert "onToolRound" in app_js
    assert 'evt.type === "tool_round"' in app_js
    assert "if (onToolRound)" in app_js


def test_new_frontend_compat_old_backend(build_test_engine):
    """4.9: 新前端遇旧后端（无 tool_round 事件）零回归。"""
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = _MultiRoundStreamFake([
        LLMResponse(content="hello", tool_calls=[], provider="fake"),
    ])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat/stream", json={"message": "hi"})
    events = _parse_sse(resp.text)

    tool_round_events = [e for e in events if e["type"] == "tool_round"]
    assert len(tool_round_events) == 0
    done = [e for e in events if e["type"] == "done"]
    assert done
    assert done[0]["data"]["final_answer"] == "hello"


def test_no_tool_calls_zero_regression(build_test_engine):
    """4.11: 纯文本对话无 tool_round 事件，零回归。"""
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = _MultiRoundStreamFake([
        LLMResponse(content="just text", tool_calls=[], provider="fake"),
    ])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat/stream", json={"message": "hi"})
    events = _parse_sse(resp.text)

    tool_round_events = [e for e in events if e["type"] == "tool_round"]
    assert len(tool_round_events) == 0
    done = [e for e in events if e["type"] == "done"]
    assert done
    assert done[0]["data"]["final_answer"] == "just text"
    assert done[0]["data"]["tool_calls"] == []


def test_tool_round_before_done(build_test_engine, tmp_path):
    """4.5 补充: tool_round 事件在 done 之前到达。"""
    f = tmp_path / "test.txt"
    f.write_text("content", encoding="utf-8")

    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = _MultiRoundStreamFake([
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": str(f)})], provider="fake"),
        LLMResponse(content="done", tool_calls=[], provider="fake"),
    ])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat/stream", json={"message": "read test.txt"})
    events = _parse_sse(resp.text)

    types = [e["type"] for e in events]
    tool_round_idx = types.index("tool_round")
    done_idx = types.index("done")
    assert tool_round_idx < done_idx, "tool_round 事件应在 done 之前"
