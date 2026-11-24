"""GLM1305-20261124: GLM 族 HTTP 429/1305「模型繁忙」有界原地重试回归.

不变量:
- 仅 GLM 族 + HTTP 429 + 业务码 1305 的整响应级显式拒绝触发原地重试;
- 同模型同 payload（wire 请求一致），默认最多 2 次额外尝试（可配 0 禁用）;
- 退避+jitter，尊重 Retry-After：等待将越过 10s 上限或剩余总预算时不早发;
- 跨尝试 monotonic 总截止（per-attempt 流 deadline 不覆盖 _raise_for_status
  抛出点——彼时 _deadline 尚为 None，预审①修复）;
- 畸形 Retry-After（inf 等）fail-closed：放弃重试并保留真实 429;
- 等待中 Stop/取消 → 立即放弃，保留真实错误与既有执行进度;
- 混合失败共享总尝试上限（1 + max(retry_disconnect, overload_retry_max)）;
- 流内 2xx error 事件（LLMStreamProviderError，部分输出已产生）绝不重试;
- 其他 provider 同码 / GLM 非 1305 均不被劫持;
- busy 进度事实以重试序号计数（1/2、2/2），不与全局 attempt 混同（预审②修复）。
探测合同（单次物理请求/档位真实性）见 test_provider_probe_wire_effort.py。
"""
import json
from threading import Event
from unittest import mock

import httpx
import pytest

from llm_loop.core.run_context import child_cancel_event, current_wait_cancel_check
from llm_loop.llm.client import LLMClient, ProviderRetryInfo
from llm_loop.llm.errors import (
    LLMHTTPError,
    LLMNetworkError,
    LLMStreamProviderError,
    classify_llm_error,
    is_glm_busy_http_rejection,
)

_MESSAGES = [{"role": "user", "content": "task"}]


class _FakeClock:
    """client.time 替身：sleep 推进 monotonic——确定性、零真实等待。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def time(self) -> float:
        return self.now


class _BusyResponse:
    """HTTP 429 + GLM 业务码的整响应级拒绝（在 _raise_for_status 抛出）."""

    def __init__(self, code: str | None = "1305", retry_after: str | None = None) -> None:
        self.status_code = 429
        self.reason_phrase = "Too Many Requests"
        self.headers: dict[str, str] = {}
        if retry_after is not None:
            self.headers["Retry-After"] = retry_after
        if code is None:
            error: dict = {"error": {"message": "Too Many Requests"}}
        else:
            error = {"error": {"code": code, "message": "模型并发负载已满，请稍后重试"}}
        self._body = json.dumps(error, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._body

    def iter_lines(self):
        yield from ()


class _StreamCtx:
    """200 成功流（镜像既有测试的 _FakeStreamCtx 契约）。"""

    def __init__(self, lines: list[str]) -> None:
        self.status_code = 200
        self.reason_phrase = "OK"
        self.headers: dict[str, str] = {}
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_lines(self):
        yield from self._lines

    def read(self) -> bytes:
        return b""


class _PartialBusyStream(_StreamCtx):
    """已投递部分正文后才在流内报 1305（HTTP 2xx + error 事件）——不可重试。"""

    def __init__(self) -> None:
        super().__init__([])

    def iter_lines(self):
        yield 'data: {"choices": [{"delta": {"content": "部分"}}]}'
        raise LLMStreamProviderError(
            "SSE 流内错误（HTTP 200 码=1305）: 模型繁忙",
            status_code=200,
            provider_code="1305",
            body='{"error":{"code":"1305"}}',
            provider="glm",
            partial_chars=2,
        )


_SUCCESS_LINES = [
    'data: {"choices": [{"delta": {"content": "已恢复"}}]}',
    'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
    "data: [DONE]",
]


def _client(**overrides) -> LLMClient:
    kwargs = dict(
        api_key="k",
        base_url="https://fake.local/v1",
        model="m",
        timeout_s=10.0,
        provider="glm",
    )
    kwargs.update(overrides)
    return LLMClient(**kwargs)


def _drain(client: LLMClient):
    """消费 chat_stream；返回 busy/timeout 进度事实并让异常按类型穿透。"""
    facts: list[ProviderRetryInfo] = []
    texts: list[str] = []
    for delta in client.chat_stream(_MESSAGES, []):
        if delta.provider_retry is not None:
            facts.append(delta.provider_retry)
        if delta.text:
            texts.append(delta.text)
    return facts, "".join(texts)


def test_busy_retry_succeeds_with_identical_payload_and_progress_facts():
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [_BusyResponse(), _StreamCtx(_SUCCESS_LINES)]
        facts, text = _drain(_client())
    assert facts == [ProviderRetryInfo("busy", 1, 2)]
    assert text == "已恢复"
    assert stream.call_count == 2
    # 同模型同 payload：wire 请求逐字节一致
    assert stream.call_args_list[0] == stream.call_args_list[1]
    assert len(clock.sleeps) >= 1  # 退避确实发生


def test_busy_retry_exhaustion_preserves_real_error_and_stays_bounded():
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [_BusyResponse() for _ in range(4)]
        with pytest.raises(LLMHTTPError) as exc_info:
            _drain(_client())
    exc = exc_info.value
    # 最终失败保留真实错误：状态/业务码/原文摘要不变
    assert exc.status_code == 429
    assert exc.provider_code == "1305"
    assert "模型并发负载已满" in str(exc)
    assert exc.retry_after_seconds is None
    assert stream.call_count == 3  # 1 + 2 次有界重试（总尝试上限）
    assert (
        stream.call_args_list[0] == stream.call_args_list[1] == stream.call_args_list[2]
    )
    assert 2.0 <= sum(clock.sleeps) < 5.0  # 退避 1s→2s + jitter，有界


def test_busy_retry_progress_counts_retry_budget_not_global_attempt():
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [_BusyResponse() for _ in range(4)]
        facts = []
        with pytest.raises(LLMHTTPError):
            for delta in _client().chat_stream(_MESSAGES, []):
                if delta.provider_retry is not None:
                    facts.append(delta.provider_retry)
    # 预审②: 计数是重试预算序号——1/2、2/2；绝不出现 3/2 之类的全局序号
    assert facts == [ProviderRetryInfo("busy", 1, 2), ProviderRetryInfo("busy", 2, 2)]


@pytest.mark.parametrize("source", ["run", "child"])
def test_busy_retry_stop_during_backoff_abandons_with_real_error(source):
    clock = _FakeClock()
    stopped = Event()

    def checker():
        if source == "run":
            return len(clock.sleeps) >= 1  # 首次退避轮询后停止
        return False

    token_run = current_wait_cancel_check.set(checker)
    token_child = child_cancel_event.set(stopped if source == "child" else None)
    try:
        with mock.patch("httpx.Client") as client_cls, mock.patch(
            "llm_loop.llm.client.time", clock
        ):
            stream = client_cls.return_value.stream
            stream.side_effect = [_BusyResponse()]
            it = _client().chat_stream(_MESSAGES, [])
            first = next(it)
            assert first.provider_retry is not None  # busy 进度已通知
            stopped.set()
            with pytest.raises(LLMHTTPError):
                next(it)  # 退避中感知停止 → 放弃，保留真实 429
        assert stream.call_count == 1
        assert clock.sleeps  # 至少进入一次退避轮询
    finally:
        current_wait_cancel_check.reset(token_run)
        child_cancel_event.reset(token_child)


def test_retry_after_window_is_respected_before_next_attempt():
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [_BusyResponse(retry_after="3"), _StreamCtx(_SUCCESS_LINES)]
        _facts, text = _drain(_client())
    assert text == "已恢复"
    assert stream.call_count == 2
    assert abs(sum(clock.sleeps) - 3.0) < 0.01  # 精确等待 Retry-After，不早发


def test_retry_after_beyond_cap_gives_up_without_early_send():
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [_BusyResponse(retry_after="600")]
        with pytest.raises(LLMHTTPError) as exc_info:
            _drain(_client())
    assert exc_info.value.retry_after_seconds == 600.0
    assert stream.call_count == 1  # 预审①: 未提前重发
    assert clock.sleeps == []  # 10s 上限内等不完 → 不等待、不盲发
    assert clock.now == 1000.0  # 消耗零预算


def test_retry_after_within_10s_but_beyond_remaining_budget_gives_up():
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [_BusyResponse(retry_after="9")]
        with pytest.raises(LLMHTTPError):
            _drain(_client(timeout_s=1.0))  # 总预算 = 1s×5，9s 等不完
    assert stream.call_count == 1
    assert clock.sleeps == []


def test_non_finite_retry_after_fails_closed_and_keeps_real_error():
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [_BusyResponse(retry_after="inf")]
        with pytest.raises(LLMHTTPError) as exc_info:
            _drain(_client())
    assert exc_info.value.status_code == 429  # 真实错误保留
    assert stream.call_count == 1  # 预审①: inf 绝不导致无限等待或盲发
    assert clock.sleeps == []


def test_nan_retry_after_header_is_canonicalized_to_absent():
    """nan 头被解析器归一为缺失（既有语义）→ 走标准有界退避。"""
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [_BusyResponse(retry_after="nan"), _StreamCtx(_SUCCESS_LINES)]
        _drain(_client())
    assert stream.call_count == 2


def test_busy_then_disconnect_stays_within_shared_attempt_cap():
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [_BusyResponse(), httpx.RemoteProtocolError("closed")]
        with pytest.raises(LLMNetworkError):
            _drain(_client())
    assert stream.call_count == 2  # 断连预算 1 已被繁忙重试挤占（attempt=2 > 1）


def test_timeout_then_busy_then_success_shares_total_cap():
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [
            httpx.ReadTimeout("slow"),
            _BusyResponse(),
            _StreamCtx(_SUCCESS_LINES),
        ]
        facts, text = _drain(_client())
    assert text == "已恢复"
    assert facts == [
        ProviderRetryInfo("timeout", 1, 1),
        ProviderRetryInfo("busy", 1, 2),
    ]
    assert stream.call_count == 3  # 恰好等于总尝试上限 1 + max(1, 2)


def test_busy_busy_disconnect_never_exceeds_total_cap():
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [
            _BusyResponse(),
            _BusyResponse(),
            httpx.RemoteProtocolError("closed"),
        ]
        facts = []
        with pytest.raises(LLMNetworkError):
            for delta in _client().chat_stream(_MESSAGES, []):
                if delta.provider_retry is not None:
                    facts.append(delta.provider_retry)
    assert facts == [ProviderRetryInfo("busy", 1, 2), ProviderRetryInfo("busy", 2, 2)]
    assert stream.call_count == 3  # 混合失败同样收敛在总上限内


def test_instream_busy_with_partial_output_is_never_retried():
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [_PartialBusyStream()]
        with pytest.raises(LLMStreamProviderError):
            _drain(_client())
    assert stream.call_count == 1  # 部分输出已投递：绝不原地重放


def test_non_glm_provider_same_code_is_not_hijacked():
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [_BusyResponse()]
        with pytest.raises(LLMHTTPError) as exc_info:
            _drain(_client(provider="minimax"))
    assert stream.call_count == 1
    # 分类不被劫持：非 GLM 族同码仍按通用 429 限流语义
    assert classify_llm_error(exc_info.value).kind == "rate_limit"


@pytest.mark.parametrize("code", [None, "1302"])
def test_glm_429_without_1305_code_is_not_retried_in_place(code):
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [_BusyResponse(code=code)]
        with pytest.raises(LLMHTTPError) as exc_info:
            _drain(_client())
    assert stream.call_count == 1  # 仅 1305 有原地重试；1302/无码走既有反馈路径
    semantics = classify_llm_error(exc_info.value)
    assert semantics.kind == "rate_limit"
    if code == "1302":
        assert "1302" in semantics.label


def test_overload_retry_max_zero_disables_in_place_retry():
    """探测合同基础件：overload_retry_max=0 → 单次请求（预审③）。"""
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [_BusyResponse()]
        with pytest.raises(LLMHTTPError):
            _drain(_client(overload_retry_max=0))
    assert stream.call_count == 1
    assert clock.sleeps == []


def test_overload_retry_max_one_is_honored():
    clock = _FakeClock()
    with mock.patch("httpx.Client") as client_cls, mock.patch(
        "llm_loop.llm.client.time", clock
    ):
        stream = client_cls.return_value.stream
        stream.side_effect = [_BusyResponse(), _StreamCtx(_SUCCESS_LINES)]
        _facts, text = _drain(_client(overload_retry_max=1))
        assert text == "已恢复"
        assert stream.call_count == 2  # 独立预算生效：1 + 1

        # 独立上限同样限制第二次繁忙：1 次重试后耗尽，绝不第三次请求
        stream.side_effect = [_BusyResponse(), _BusyResponse()]
        with pytest.raises(LLMHTTPError):
            _drain(_client(overload_retry_max=1))
        assert stream.call_count == 4  # 前段 2 次 + 本段 2 次


def test_predicate_and_semantics_exactness():
    glm_busy = LLMHTTPError(
        "HTTP 429", status_code=429, provider="glm", provider_code="1305"
    )
    assert is_glm_busy_http_rejection(glm_busy)
    for provider in ("glm-api", "zhipu"):
        assert is_glm_busy_http_rejection(
            LLMHTTPError("x", status_code=429, provider=provider, provider_code="1305")
        )
    assert not is_glm_busy_http_rejection(
        LLMHTTPError("x", status_code=429, provider="glm", provider_code="1302")
    )
    assert not is_glm_busy_http_rejection(
        LLMHTTPError("x", status_code=503, provider="glm", provider_code="1305")
    )
    assert not is_glm_busy_http_rejection(
        LLMHTTPError("x", status_code=429, provider="minimax", provider_code="1305")
    )
    assert not is_glm_busy_http_rejection(
        LLMStreamProviderError(
            "x", status_code=200, provider="glm", provider_code="1305"
        )
    )
    semantics = classify_llm_error(glm_busy)
    assert semantics.kind == "provider_busy"
    assert "模型繁忙" in semantics.label
    assert semantics.provider_code == "1305"
    # fallback 三维与既有 429 一致——不改变可用性降级行为
    assert semantics.same_identity_retry
    assert semantics.same_account_other_models
    assert semantics.independent_provider
    assert semantics.fallback_eligible


def test_llm_http_error_carries_retry_after_fact():
    exc = LLMHTTPError(
        "x", status_code=429, provider="glm", provider_code="1305",
        retry_after_seconds=7.5,
    )
    assert exc.retry_after_seconds == 7.5
    assert LLMHTTPError("x", status_code=429).retry_after_seconds is None
