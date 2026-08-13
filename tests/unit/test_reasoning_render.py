"""P1-1 思考过程渲染后端契约单测（tasks 4.1/4.2/4.3）.

断言:
1. StreamDelta.reasoning 字段向后兼容（默认 None）+ 可携带思考分片
2. LoopResult.reasoning_content 透传最终回答轮思考链
3. ChatResponse/MessageItem reasoning_content 字段存在
"""

from __future__ import annotations


def test_stream_delta_reasoning_default_none():
    from llm_loop.llm.client import StreamDelta

    d = StreamDelta(text="hello")
    assert d.reasoning is None  # 默认 None 向后兼容


def test_stream_delta_reasoning_set():
    from llm_loop.llm.client import StreamDelta

    d = StreamDelta(text="", reasoning="思考分片")
    assert d.reasoning == "思考分片"
    assert d.text == ""


def test_loop_result_reasoning_default_none():
    from llm_loop.core.loop.engine import LoopResult

    r = LoopResult(session_id="s", final_answer="answer")
    assert r.reasoning_content is None


def test_loop_result_reasoning_set():
    from llm_loop.core.loop.engine import LoopResult

    r = LoopResult(session_id="s", final_answer="answer", reasoning_content="思考链")
    assert r.reasoning_content == "思考链"


def test_run_reasoning_content_passthrough(build_test_engine):
    from tests.unit.test_stream_equivalence import StreamingFakeLLM

    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = StreamingFakeLLM("回答", reasoning_content="思考过程")
    result = engine.run("s1", "问题")
    assert result.reasoning_content == "思考过程"


def test_run_reasoning_none_when_thinking_off(build_test_engine):
    from tests.unit.test_stream_equivalence import StreamingFakeLLM

    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = StreamingFakeLLM("回答")  # 无 reasoning
    result = engine.run("s1", "问题")
    assert result.reasoning_content is None


def test_chat_response_reasoning_field():
    from llm_loop.web.schemas import ChatResponse

    r = ChatResponse(session_id="s", final_answer="a")
    assert r.reasoning_content is None
    r2 = ChatResponse(session_id="s", final_answer="a", reasoning_content="思考")
    assert r2.reasoning_content == "思考"


def test_message_item_reasoning_field():
    from llm_loop.web.schemas import MessageItem

    m = MessageItem(role="assistant", content="a")
    assert m.reasoning_content is None
    m2 = MessageItem(role="assistant", content="a", reasoning_content="思考")
    assert m2.reasoning_content == "思考"
