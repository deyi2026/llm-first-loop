"""P1-1 思考过程渲染 Web 集成测试（tasks 4.4/4.5/4.6/4.7/4.8）.

断言:
4. SSE 流含 reasoning_delta 事件 + done 携带 reasoning_content（终态兜底）
5. 非流式 POST /api/v1/chat 响应含 reasoning_content
6. 历史消息 GET /api/v1/sessions/{id}/messages 含 reasoning_content
7. 旧前端兼容（reasoning_delta 事件被忽略，answer_delta/done 不受影响）
8. 思考模式关闭零回归（无 reasoning_delta、done reasoning_content=null、正文正常）
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from llm_loop.web import build_app
from tests.unit.test_stream_equivalence import StreamingFakeLLM


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def test_sse_reasoning_delta_and_done(build_test_engine):
    """4.4: SSE 流推送 reasoning_delta + done 携带 reasoning_content."""
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = StreamingFakeLLM("回答", reasoning_content="思考过程")
    client = _make_client(engine)
    resp = client.post("/api/v1/chat/stream", json={"message": "hi"})
    events = _parse_sse(resp.text)
    reasoning_events = [e for e in events if e["type"] == "reasoning_delta"]
    assert reasoning_events, "无 reasoning_delta 事件"
    joined = "".join(e["data"]["data"] for e in reasoning_events)
    assert joined == "思考过程"
    done = events[-1]["data"]
    assert done["reasoning_content"] == "思考过程"  # 终态兜底


def test_non_stream_chat_reasoning_content(build_test_engine):
    """4.5: 非流式 POST /api/v1/chat 透传 reasoning_content."""
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = StreamingFakeLLM("回答", reasoning_content="思考")
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={"message": "hi"})
    assert resp.json()["reasoning_content"] == "思考"


def test_history_messages_reasoning_content(build_test_engine):
    """4.6: 历史消息回传 reasoning_content."""
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = StreamingFakeLLM("回答", reasoning_content="思考")
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={"message": "hi"})
    sid = resp.json()["session_id"]
    hist = client.get(f"/api/v1/sessions/{sid}/messages")
    msgs = hist.json()["messages"]
    assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
    assert any(m.get("reasoning_content") for m in assistant_msgs), "历史 assistant 消息无 reasoning_content"


def test_old_frontend_compat_static(app_js_src: str):
    """4.7: 旧前端兼容静态断言（onReasoningDelta 可选，reasoning_delta 事件可忽略）."""
    assert "onReasoningDelta" in app_js_src
    assert 'evt.type === "reasoning_delta"' in app_js_src
    # 旧调用方不传第三参数 → reasoning_delta 被忽略（onReasoningDelta falsy 判定存在）
    assert "if (onReasoningDelta)" in app_js_src


def test_thinking_off_zero_regression(build_test_engine):
    """4.8: 思考模式关闭零回归（无 reasoning_delta、done reasoning_content=null、正文正常）."""
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = StreamingFakeLLM("回答")  # 无 reasoning
    client = _make_client(engine)
    resp = client.post("/api/v1/chat/stream", json={"message": "hi"})
    events = _parse_sse(resp.text)
    reasoning_events = [e for e in events if e["type"] == "reasoning_delta"]
    assert not reasoning_events, "思考模式关闭不应有 reasoning_delta 事件"
    done = events[-1]["data"]
    assert done["reasoning_content"] is None
    answer_events = [e for e in events if e["type"] == "answer_delta"]
    assert answer_events, "正文应正常渲染"
    joined = "".join(e["data"]["data"] for e in answer_events)
    assert joined == "回答"
