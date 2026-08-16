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

CHAT_RESPONSE_FIELDS = [
    "session_id",
    "final_answer",
    "verification_note",
    "rounds",
    "tool_calls",
    "truncated",
    "model_used",
    "tokens_in",
    "tokens_out",
    "tokens_cache_hit",
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


def test_chat_stream_done_has_nine_fields(build_test_engine):
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
