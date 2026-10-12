"""ASSESS-20261008-project-audit rev3 §7 WP3 回归: BUG-11/12/15.

- BUG-11: Anthropic message_delta.usage 为累计值——最终用量按协议更新，
  缺字段不清零（原实现只读 message_start，最终 completion_tokens 失真）。
- BUG-12: 断连重试共用 accumulator——一次 transport attempt 的 accumulator/
  工具聚合/finish/truncation 状态须重新初始化；失败 attempt 的 usage 事实
  保留在 attempt journal（观测器逐 attempt 记录）。
- BUG-15: reasoning-only 响应不满足"零 delta 投递"重试前提——已投递思考
  不得触发同模型静默重试（避免两次思考拼接/重复计费），如实上抛空响应
  异常携带事实，由引擎层决定 failover。

测试契约: 全部离线 fixture（mock httpx），不触网。
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import httpx
import pytest

from llm_loop.llm.client import LLMClient
from llm_loop.llm.errors import LLMEmptyResponseError, LLMNetworkError

_MSGS = [{"role": "user", "content": "hi"}]


def _client(**overrides) -> LLMClient:
    kwargs: dict[str, Any] = dict(
        api_key="k",
        base_url="https://fake.local/v1",
        model="m",
        timeout_s=10.0,
        provider="glm-api",
    )
    kwargs.update(overrides)
    return LLMClient(**kwargs)


def _sse(data: Any) -> str:
    return "data: " + json.dumps(data, ensure_ascii=False)


class _FakeStreamCtx:
    def __init__(self, lines, status_code: int = 200) -> None:
        self._lines = list(lines)
        self.status_code = status_code
        self.reason_phrase = "OK"
        self.headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_lines(self):
        yield from self._lines

    def read(self) -> bytes:
        return b""


class _LinesThenError:
    """先产出若干行，随后抛传输级异常（模拟流中断连）."""

    def __init__(self, lines, exc) -> None:
        self._lines = list(lines)
        self._exc = exc

    def __iter__(self):
        yield from self._lines
        raise self._exc


class _DisconnectCtx(_FakeStreamCtx):
    def __init__(self, lines, exc) -> None:
        super().__init__(lines)
        self._iter = _LinesThenError(lines, exc)

    def iter_lines(self):
        yield from self._iter


def _run(overrides, ctxs, expect_exc=None, spy_usage=False):
    """ctxs: 依次出现的 stream 上下文; 返回 (deltas, result) 或捕获异常."""
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.side_effect = ctxs
        client = _client(**overrides)
        if spy_usage:
            obs = mock.patch.object(
                client, "_observe_transport_usage", wraps=client._observe_transport_usage
            )
            obs.start()
        deltas = []
        result = None
        try:
            it = client.chat_stream(messages=_MSGS, tools=[])
            while True:
                try:
                    d = next(it)
                except StopIteration as stop:
                    result = stop.value
                    break
                deltas.append(d)
        finally:
            if spy_usage:
                obs.stop()
        return deltas, result


_ANTH = {"wire_protocol": "anthropic"}


# ───────────────────────── BUG-11: message_delta 累计用量 ─────────────────────────


def test_anthropic_message_delta_usage_cumulative():
    """message_start.output=1 + message_delta.output=15 → 最终 15（原为 1）."""
    lines = [
        _sse({"type": "message_start", "message": {"usage": {"input_tokens": 3, "output_tokens": 1}}}),
        _sse({"type": "content_block_delta", "index": 0,
              "delta": {"type": "text_delta", "text": "你好"}}),
        _sse({"type": "message_delta", "delta": {"stop_reason": "end_turn"},
              "usage": {"output_tokens": 15, "input_tokens": 3}}),
    ]
    deltas, result = _run(_ANTH, [_FakeStreamCtx(lines)])
    assert result is not None
    assert "".join(d.text for d in deltas) == "你好"
    assert result.completion_tokens == 15  # 累计终值（原实现保持 1）
    assert result.prompt_tokens == 3


def test_anthropic_message_delta_missing_fields_do_not_zero():
    """message_delta.usage 缺字段不得清零已有累计（M58 缺失不覆盖契约延续）."""
    lines = [
        _sse({"type": "message_start", "message": {"usage": {"input_tokens": 7, "output_tokens": 2}}}),
        _sse({"type": "content_block_delta", "index": 0,
              "delta": {"type": "text_delta", "text": "x"}}),
        _sse({"type": "message_delta", "delta": {"stop_reason": "end_turn"},
              "usage": {"output_tokens": 9}}),
    ]
    _, result = _run(_ANTH, [_FakeStreamCtx(lines)])
    assert result.completion_tokens == 9
    assert result.prompt_tokens == 7  # 缺 input_tokens 不清零


def test_anthropic_multiple_usage_events_last_cumulative_wins():
    lines = [
        _sse({"type": "message_start", "message": {"usage": {"input_tokens": 3, "output_tokens": 1}}}),
        _sse({"type": "content_block_delta", "index": 0,
              "delta": {"type": "text_delta", "text": "ab"}}),
        _sse({"type": "message_delta", "delta": {}, "usage": {"output_tokens": 5}}),
        _sse({"type": "message_delta", "delta": {"stop_reason": "max_tokens"},
              "usage": {"output_tokens": 6, "input_tokens": 3}}),
    ]
    _, result = _run(_ANTH, [_FakeStreamCtx(lines)])
    assert result.completion_tokens == 6  # 多事件: 末次累计值
    assert result.finish_reason == "max_tokens"
    assert result.truncated is True


# ───────────────────────── BUG-12: attempt 状态重置 ─────────────────────────


def test_openai_disconnect_retry_resets_truncation_state():
    """length-only 后断连 → 重试成功 stop: 最终 truncated=False（原残留 True）."""
    disconnect = httpx.ReadError("peer closed connection")
    attempt1 = _DisconnectCtx(
        [_sse({"choices": [{"delta": {}, "finish_reason": "length"}]})],
        disconnect,
    )
    attempt2 = _FakeStreamCtx([
        _sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": None}]}),
        _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
        "data: [DONE]",
    ])
    _, result = _run({}, [attempt1, attempt2])
    assert result is not None
    assert result.content == "ok"
    assert result.finish_reason == "stop"
    assert result.truncated is False  # BUG-12: 不残留失败 attempt 的截断标志


def test_openai_disconnect_retry_keeps_attempt_usage_in_journal():
    """usage-only 后断连 → 重试成功: 失败 attempt 的 usage 仍被逐 attempt 观测."""
    disconnect = httpx.ReadError("peer closed")
    attempt1 = _DisconnectCtx(
        [_sse({"usage": {"prompt_tokens": 100, "completion_tokens": 5}})],
        disconnect,
    )
    attempt2 = _FakeStreamCtx([
        _sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": None}]}),
        _sse({"usage": {"prompt_tokens": 90, "completion_tokens": 3}}),
        _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
        "data: [DONE]",
    ])
    observed: list[dict] = []
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.side_effect = [attempt1, attempt2]
        client = _client()
        with mock.patch.object(
            client, "_observe_transport_usage", side_effect=lambda u, **k: observed.append(dict(u))
        ):
            deltas = []
            result = None
            it = client.chat_stream(messages=_MSGS, tools=[])
            while True:
                try:
                    d = next(it)
                except StopIteration as stop:
                    result = stop.value
                    break
                deltas.append(d)
    assert result is not None and result.content == "ok"
    # 两个 attempt 的 usage 都进了观测（journal 事实不因重试被丢弃）
    assert len(observed) == 2
    assert observed[0]["prompt_tokens"] == 100
    assert observed[1]["prompt_tokens"] == 90
    # 最终响应用量取成功 attempt 的事实，不混入失败 attempt 残留
    assert result.prompt_tokens == 90
    assert result.completion_tokens == 3


def test_openai_disconnect_no_retry_when_tool_draft_seen():
    """已有 tool 草稿投递后断连: 不重试（避免重复工具执行），如实上抛网络错误."""
    disconnect = httpx.ReadError("peer closed")
    attempt1 = _DisconnectCtx(
        [
            _sse(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "t1",
                                        "function": {"name": "f", "arguments": '{\"a\":'},
                                    }
                                ]
                            }
                        }
                    ]
                }
            )
        ],
        disconnect,
    )
    attempt2 = _FakeStreamCtx([  # 不应被消费
        _sse({"choices": [{"delta": {"content": "dup"}, "finish_reason": None}]}),
        "data: [DONE]",
    ])
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.side_effect = [attempt1, attempt2]
        client = _client()
        with pytest.raises(LLMNetworkError):
            list(client.chat_stream(messages=_MSGS, tools=[]))
    # 只发起一次请求
    assert client_cls.return_value.stream.call_count == 1


def test_openai_disconnect_no_retry_when_text_seen():
    """已有文本投递后断连: 不重试（避免 UI 重复）。"""
    disconnect = httpx.ReadError("peer closed")
    attempt1 = _DisconnectCtx(
        [_sse({"choices": [{"delta": {"content": "部分"}, "finish_reason": None}]})],
        disconnect,
    )
    attempt2 = _FakeStreamCtx([
        _sse({"choices": [{"delta": {"content": "dup"}, "finish_reason": None}]}),
        "data: [DONE]",
    ])
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.side_effect = [attempt1, attempt2]
        client = _client()
        with pytest.raises(LLMNetworkError):
            list(client.chat_stream(messages=_MSGS, tools=[]))
    assert client_cls.return_value.stream.call_count == 1


# ───────────────────────── BUG-15: reasoning-only 不重试 ─────────────────────────


def test_reasoning_only_response_raises_without_same_model_retry():
    """已投递 reasoning 的空响应不满足零 delta 投递前提: 不再同模型重试."""
    lines = [
        _sse({"type": "message_start", "message": {"usage": {"input_tokens": 3, "output_tokens": 0}}}),
        _sse({"type": "content_block_delta", "index": 0,
              "delta": {"type": "thinking_delta", "thinking": "思考r1"}}),
        _sse({"type": "message_delta", "delta": {"stop_reason": "end_turn"}}),
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        client = _client(**_ANTH)
        reasoning_seen = []
        with pytest.raises(LLMEmptyResponseError) as ei:
            it = client.chat_stream(messages=_MSGS, tools=[])
            while True:
                try:
                    d = next(it)
                except StopIteration:
                    break
                if d.reasoning:
                    reasoning_seen.append(d.reasoning)
        # 仅一次请求（原实现会 sleep 后同模型重试 → 第二次请求 + r2 拼接）
        assert client_cls.return_value.stream.call_count == 1
        assert reasoning_seen == ["思考r1"]  # 已投递事实不被抹掉
        assert ei.value.finish_reason == "end_turn"


def test_truly_empty_response_still_retries_once():
    """对照: 零 delta 投递的空响应仍按 EVO-20261007 契约同模型重试一次."""
    empty_lines = [
        _sse({"type": "message_start", "message": {"usage": {"input_tokens": 3, "output_tokens": 0}}}),
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.side_effect = [
            _FakeStreamCtx(empty_lines), _FakeStreamCtx(empty_lines)
        ]
        client = _client(**_ANTH)
        with (
            mock.patch("llm_loop.llm.client.time.sleep"),
            pytest.raises(LLMEmptyResponseError, match="已同模型自动重试"),
        ):
            list(client.chat_stream(messages=_MSGS, tools=[]))
        assert client_cls.return_value.stream.call_count == 2
