"""ASSESS-20261008-project-audit rev3 §7 WP1 回归: BUG-02/03/04.

- BUG-03: SSE 流内错误不再把业务码灌入 status_code；HTTP 状态与 provider 业务码
  作为两个独立事实保留（异常扩展 + 结构化 body 保持可解析）。
- BUG-02: 429+GLM 业务码语义分类准确（1302 限流 / 1311 模型权限 / 1113 欠费），
  分类与 availability fallback 消费同一份事实，标签不误导。
- BUG-04: Anthropic/Google 流内 error 事件显式上抛；partial 后 error 不得返回
  成功 completion；已投递 partial 与 attempt 事实保留在异常上。

测试契约: 全部离线 fixture（mock httpx），不触网。
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest

from llm_loop.core.loop.engine_services.fallback import FallbackService
from llm_loop.llm.client import LLMClient
from llm_loop.llm.errors import (
    LLMHTTPError,
    LLMStreamProviderError,
    classify_llm_error,
    parse_provider_error_code,
)

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


class _FakeStreamCtx:
    """模拟 httpx.Client.stream 上下文（iter_lines / read / headers）."""

    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self._lines = list(lines)
        self.status_code = status_code
        self.reason_phrase = "OK"
        self.headers: dict[str, str] = {}
        self.read_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_lines(self):
        yield from self._lines

    def read(self) -> bytes:
        self.read_calls += 1
        return b""


def _sse(data: dict) -> str:
    return "data: " + json.dumps(data, ensure_ascii=False)


def _drive(overrides: dict, lines: list[str], **chat_kwargs):
    """在 httpx patch 上下文内构造并驱动 chat_stream（LLMClient 构造即建连）.

    Returns (deltas, final_response)；异常原样抛出。
    """
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        client = _client(**overrides)
        deltas = []
        result = None
        it = client.chat_stream(messages=_MSGS, tools=[], **chat_kwargs)
        while True:
            try:
                d = next(it)
            except StopIteration as stop:
                result = stop.value
                break
            deltas.append(d)
        return deltas, result


def _drive_exc(overrides: dict, lines: list[str], exc_type=LLMStreamProviderError):
    """同 _drive，但断言以 exc_type 结束; 返回 pytest ExceptionInfo."""
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        client = _client(**overrides)
        with pytest.raises(exc_type) as ei:
            list(client.chat_stream(messages=_MSGS, tools=[]))
    return ei.value


# ───────────────────────── BUG-03: SSE 错误事实分离 ─────────────────────────


def test_sse_error_keeps_http_status_and_provider_code_numeric():
    """HTTP 200 + GLM 业务码 1311: status_code 保持 200，业务码在 provider_code."""
    lines = [
        _sse({"error": {"code": 1311, "message": "您没有调用此模型的权限"}}),
        "data: [DONE]",
    ]
    exc = _drive_exc({}, lines)
    assert isinstance(exc, LLMHTTPError)  # 向后兼容: 仍是 HTTP 异常族
    assert exc.status_code == 200  # 真实 HTTP 状态，不再被业务码 1311 污染
    assert exc.provider_code == "1311"
    # body 保持可解析（结构化 JSON 携带业务码，非裸 message）
    assert parse_provider_error_code(exc.body) == "1311"


def test_sse_error_non_numeric_code_not_500():
    """非数值业务码（如 'model_not_found'）不再被回退成 status_code=500."""
    lines = [_sse({"error": {"code": "model_not_found", "message": "no such model"}})]
    exc = _drive_exc({}, lines)
    assert exc.status_code == 200
    assert exc.provider_code == "model_not_found"


def test_sse_error_missing_code():
    """无 code 字段: 仍以流内失败上抛，provider_code 如实为 None."""
    lines = [_sse({"error": {"message": "boom"}})]
    exc = _drive_exc({}, lines)
    assert exc.status_code == 200
    assert exc.provider_code is None


def test_http_error_carries_provider_code():
    """_raise_for_status 429 路径: 异常携带从 body 解析出的业务码."""
    body = json.dumps({"error": {"code": "1302", "message": "rate limited"}})
    resp = mock.Mock(status_code=429, reason_phrase="Too Many Requests")
    resp.read.return_value = body.encode()
    resp.headers = {}
    client = _client()
    with mock.patch.object(client, "_observe_transport_error"), pytest.raises(LLMHTTPError) as ei:
        client._raise_for_status(resp, model_id="m")
    assert ei.value.status_code == 429
    assert ei.value.provider_code == "1302"


# ───────────────────────── BUG-02: 分类语义 ─────────────────────────


def _glm_http_error(code: str, status: int = 429) -> LLMHTTPError:
    body = json.dumps({"error": {"code": code, "message": "err"}}, ensure_ascii=False)
    return LLMHTTPError(
        f"HTTP {status}: err",
        status_code=status,
        body=body,
        provider="glm-api",
        provider_code=code,
    )


@pytest.mark.parametrize(
    "code,kind,eligible",
    [
        ("1302", "rate_limit", True),        # 速率限制: 瞬时可恢复
        ("1311", "model_permission", True),  # 订阅未含所选模型: 换模型可能可用
        ("1113", "account_billing", False),  # 账户欠费: 账户级，换模型无用
    ],
)
def test_glm_429_business_code_classification(code, kind, eligible):
    sem = classify_llm_error(_glm_http_error(code))
    assert sem.kind == kind
    assert sem.provider_code == code
    assert FallbackService._is_fallback_eligible_error(_glm_http_error(code)) is eligible


def test_glm_429_unknown_code_stays_http_level_rate_limit():
    """未知业务码: 如实保留码事实，不发明语义；HTTP 429 的机械事实仍是限流."""
    exc = _glm_http_error("1399")
    sem = classify_llm_error(exc)
    assert sem.kind == "rate_limit"
    assert sem.provider_code == "1399"
    assert "1399" in sem.label  # 未知码如实出现在标签
    assert FallbackService._is_fallback_eligible_error(exc) is True


def test_non_glm_provider_code_not_hijacked():
    """非 GLM 族同码不按 GLM 语义解释（避免劫持其他 provider 同码异义）."""
    exc = LLMHTTPError(
        "HTTP 429: err",
        status_code=429,
        body=json.dumps({"error": {"code": "1311", "message": "x"}}),
        provider="some-other",
        provider_code="1311",
    )
    sem = classify_llm_error(exc)
    assert sem.kind == "rate_limit"  # 仅 HTTP 层事实
    assert "权限" not in sem.label


def test_403_plain_and_quota_classification():
    plain = LLMHTTPError("HTTP 403: forbidden", status_code=403, body="", provider="kimi")
    assert classify_llm_error(plain).kind == "client_error"
    assert FallbackService._is_fallback_eligible_error(plain) is False
    quota = LLMHTTPError(
        "HTTP 403: access_terminated_error",
        status_code=403,
        body='{"type":"access_terminated_error","message":"usage limit reached"}',
        provider="kimi",
    )
    sem = classify_llm_error(quota)
    assert sem.kind == "account_billing"  # 与 is_quota_error 同一事实来源
    assert FallbackService._is_fallback_eligible_error(quota) is False


def test_5xx_server_error_classification():
    exc = LLMHTTPError("HTTP 503: unavailable", status_code=503, body="", provider="glm-api")
    assert classify_llm_error(exc).kind == "server_error"
    assert FallbackService._is_fallback_eligible_error(exc) is True


def test_labels_not_misleading():
    """1311/1113 的降级标签不得称'限流'（ASSESS-20261008 BUG-02 核心）."""
    label_1302 = FallbackService._fallback_reason_label(_glm_http_error("1302"))
    assert "限流" in label_1302 and "1302" in label_1302
    label_1311 = FallbackService._fallback_reason_label(_glm_http_error("1311"))
    assert "限流" not in label_1311
    assert "1311" in label_1311 and "权限" in label_1311
    label_1113 = FallbackService._fallback_reason_label(_glm_http_error("1113"))
    assert "限流" not in label_1113
    assert "1113" in label_1113 and "欠费" in label_1113


# ───────────────────────── BUG-04: 流内 error 上抛 ─────────────────────────


_ANTH = {"wire_protocol": "anthropic"}


def test_anthropic_stream_error_raises_with_partial_facts():
    lines = [
        _sse({"type": "message_start", "message": {"usage": {"input_tokens": 3, "output_tokens": 0}}}),
        _sse({"type": "content_block_delta", "index": 0,
              "delta": {"type": "text_delta", "text": "部分回答"}}),
        _sse({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
        "data: [DONE]",
    ]
    exc = _drive_exc(_ANTH, lines)
    assert exc.status_code == 200
    assert exc.provider_code == "overloaded_error"
    assert exc.partial_chars == len("部分回答")
    # 语义: overloaded 属服务端瞬时 → 可 failover
    assert classify_llm_error(exc).kind == "server_error"
    assert FallbackService._is_fallback_eligible_error(exc) is True


def test_anthropic_stream_error_zero_output():
    lines = [
        _sse({"type": "message_start", "message": {"usage": {"input_tokens": 3, "output_tokens": 0}}}),
        _sse({"type": "error", "error": {"type": "api_error", "message": "Internal"}}),
    ]
    _drive_exc(_ANTH, lines)  # 上抛即通过（无输出也必须失败，不得静默空成功）


def test_anthropic_stream_error_not_success_completion():
    """partial 后 error 不得以成功 completion 收尾（原来返回半截成功）."""
    lines = [
        _sse({"type": "message_start", "message": {"usage": {"input_tokens": 3, "output_tokens": 0}}}),
        _sse({"type": "content_block_delta", "index": 0,
              "delta": {"type": "text_delta", "text": "半"}}),
        _sse({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
    ]
    result_holder = {"result": "unset"}

    class _SentinelError(Exception):
        pass

    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        client = _client(**_ANTH)
        it = client.chat_stream(messages=_MSGS, tools=[])
        with pytest.raises(LLMStreamProviderError):
            while True:
                try:
                    next(it)
                except StopIteration as stop:
                    result_holder["result"] = stop.value
                    raise _SentinelError from None
    assert result_holder["result"] == "unset"  # 无成功返回值


def test_anthropic_tool_args_half_then_error_raises():
    """工具参数半截 + error: 上抛，不执行不完整工具草稿."""
    lines = [
        _sse({"type": "message_start", "message": {"usage": {"input_tokens": 3, "output_tokens": 0}}}),
        _sse({"type": "content_block_start", "index": 0,
              "content_block": {"type": "tool_use", "id": "t1", "name": "read_file", "input": {}}}),
        _sse({"type": "content_block_delta", "index": 0,
              "delta": {"type": "input_json_delta", "partial_json": '{"pa'}}),
        _sse({"type": "error", "error": {"type": "api_error", "message": "boom"}}),
    ]
    _drive_exc(_ANTH, lines)


def test_anthropic_normal_terminal_unchanged():
    """对照组: 正常终态流不受 error 分支影响."""
    lines = [
        _sse({"type": "message_start", "message": {"usage": {"input_tokens": 10, "output_tokens": 0}}}),
        _sse({"type": "content_block_delta", "index": 0,
              "delta": {"type": "text_delta", "text": "你好"}}),
        _sse({"type": "message_delta", "delta": {"stop_reason": "end_turn"}}),
        "data: [DONE]",
    ]
    deltas, result = _drive(_ANTH, lines)
    assert "".join(d.text for d in deltas) == "你好"
    assert result is not None
    assert result.content == "你好"


def test_google_stream_error_raises_with_partial_facts():
    lines = [
        _sse({"candidates": [{"content": {"parts": [{"text": "答"}]}}]}),
        _sse({"error": {"code": 503, "status": "UNAVAILABLE", "message": "try later"}}),
    ]
    exc = _drive_exc({"wire_protocol": "google"}, lines)
    assert exc.status_code == 200
    assert exc.provider_code == "UNAVAILABLE"
    assert exc.partial_chars == len("答")
    assert classify_llm_error(exc).kind == "server_error"
    assert FallbackService._is_fallback_eligible_error(exc) is True


def test_google_normal_terminal_unchanged():
    lines = [
        _sse({"candidates": [{"content": {"parts": [{"text": "你好"}]}}]}),
        _sse({"candidates": [{"finishReason": "STOP"}]}),
    ]
    deltas, result = _drive({"wire_protocol": "google"}, lines)
    assert "".join(d.text for d in deltas) == "你好"
    assert result is not None
    assert result.content == "你好"
