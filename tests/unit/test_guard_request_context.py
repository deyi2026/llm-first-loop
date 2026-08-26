"""LLM cache_guard 每请求上下文：并发隔离、预算接线、模型切换。"""

from __future__ import annotations

from unittest import mock

import pytest

from llm_loop.cache_guard.guard import CacheGuardBlockedError, PromptGuard
from llm_loop.llm.client import LLMClient, LLMResponse


class _StreamCtx:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.status_code = 200
        self.reason_phrase = "OK"
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_lines(self):
        yield from self._lines

    def read(self) -> bytes:
        return b""


def _guard_ctx(**kwargs):
    from llm_loop.llm import client as client_mod

    cls = getattr(client_mod, "GuardRequestContext", None)
    assert cls is not None, "LLM guard 元数据必须有显式每请求上下文，而非共享 client 字段"
    return cls(**kwargs)


def _consume(it):
    while True:
        try:
            next(it)
        except StopIteration as exc:
            return exc.value


def test_llm_guard_context_wires_history_budget_into_submit_ratio():
    """真实 LLMClient 出口必须把 history_budget 接进规则F，而非只在 validate_request 单测生效。"""
    ctx = _guard_ctx(
        session_id="s-budget",
        system_text="S" * 20,
        history_budget=100,
        provider="fake",
        model="m",
        run_round=1,
    )
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _StreamCtx(
            ['data: {"choices":[{"delta":{"content":"should-not-send"}}]}', "data: [DONE]"]
        )
        client = LLMClient(api_key="k", base_url="https://fake.local/v1", model="m")
        stream = client.chat_stream(
            messages=[
                {"role": "system", "content": "S" * 20},
                {"role": "user", "content": "U" * 90},
            ],
            tools=[],
            guard_context=ctx,
        )
        with pytest.raises(CacheGuardBlockedError):
            next(stream)
        assert client_cls.return_value.stream.call_count == 0, "BLOCK 后不应触网"


def test_shared_client_interleaved_streams_keep_guard_telemetry_session_local():
    """A流暂停→B完整结束→A结束时，A的usage必须仍记到A，不能读取共享字段变成B。"""
    a_lines = [
        'data: {"choices":[{"delta":{"content":"A"}}]}',
        'data: {"usage":{"prompt_tokens":100,"completion_tokens":1,"prompt_cache_hit_tokens":80}}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]
    b_lines = [
        'data: {"choices":[{"delta":{"content":"B"}}]}',
        'data: {"usage":{"prompt_tokens":200,"completion_tokens":1,"prompt_cache_hit_tokens":150}}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.side_effect = [_StreamCtx(a_lines), _StreamCtx(b_lines)]
        client = LLMClient(api_key="k", base_url="https://fake.local/v1", model="m")
        ctx_a = _guard_ctx(
            session_id="s-a", system_text="sys-a", history_budget=10000,
            provider="fake", model="m", run_round=1,
        )
        ctx_b = _guard_ctx(
            session_id="s-b", system_text="sys-b", history_budget=10000,
            provider="fake", model="m", run_round=1,
        )
        a = client.chat_stream(
            messages=[{"role": "system", "content": "sys-a"}], tools=[], guard_context=ctx_a
        )
        assert next(a).text == "A"  # A 停在流中途
        b = client.chat_stream(
            messages=[{"role": "system", "content": "sys-b"}], tools=[], guard_context=ctx_b
        )
        assert _consume(b).content == "B"
        assert _consume(a).content == "A"

        guard = client.ensure_guard()
        assert guard._hit_win["s-a"][-1][:2] == (100, 80)  # noqa: SLF001
        assert guard._hit_win["s-b"][-1][:2] == (200, 150)  # noqa: SLF001


def test_prompt_guard_model_switch_resets_only_that_session(tmp_path):
    """同provider不同model切换应按session重置，不能靠client全局guard_last_model。"""
    guard = PromptGuard(audit_file=tmp_path / "guard.jsonl")
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    guard.check(session_id="s1", system_text="sys", messages=messages, model="model-a")
    guard.check(session_id="s2", system_text="sys", messages=messages, model="model-a")
    guard.record_result("s1", 100, 80)
    guard.record_result("s2", 200, 160)

    guard.check(session_id="s1", system_text="sys", messages=messages, model="model-b")
    assert "s1" not in guard._hit_win  # noqa: SLF001
    assert guard._hit_win["s2"][-1][:2] == (200, 160)  # noqa: SLF001


def test_engine_passes_explicit_guard_context_to_real_llm_client(build_test_engine):
    """Engine 对真实 LLMClient 走显式 request context；FakeLLM duck typing 仍不要求新参数。"""
    engine, _fake = build_test_engine([])

    class SpyClient(LLMClient):
        seen_guard = None

        def chat_stream(self, messages, tools, *, timeout_s=None, model=None, guard_context=None):
            self.seen_guard = guard_context
            yield from ()
            return LLMResponse(content="ok", tool_calls=[], provider="spy")

    with mock.patch("httpx.Client"):
        spy = SpyClient(api_key="", base_url="http://127.0.0.1:9999/v1", model="spy-model")
    engine.llm = spy
    engine.llm_pool.default_client = spy
    sid = engine.session.create()
    result = engine.run(sid, "hello")
    assert result.final_answer == "ok"
    ctx = spy.seen_guard
    assert ctx is not None
    assert ctx.session_id == sid
    assert ctx.history_budget > 0
    assert ctx.run_round == 1
    assert ctx.model == "spy-model"
