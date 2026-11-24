"""GLM1305-20261124: provider_admin.test_provider 探测合同回归.

- wire 档位真实性（预审④）: 模型支持 low 时 payload["reasoning_effort"]=="low"
  （不再被 registry 默认档 max 覆盖），且等于返回的 reasoning_effort_resolved
  （always_on_effort 契约下二者为同一序列化值）;
- 模型不支持 low 时保留 registry 默认档——不伪造档位、不谎称关闭推理;
- 单次物理请求合同（预审③）: 断连重试与繁忙重试显式禁用——429/1305 探测
  失败不放大请求数，保持 one bounded request / ≤30s 原合同。
"""
import json
from types import SimpleNamespace
from unittest import mock

import pytest

import llm_loop.web.provider_admin as provider_admin_module

# 模块属性绑定（避免 pytest 把导入的 test_provider 误收集为用例）
_test_provider = provider_admin_module.test_provider
_ProviderAdminError = provider_admin_module.ProviderAdminError


class _OKCtx:
    status_code = 200
    reason_phrase = "OK"
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_lines(self):
        yield 'data: {"choices": [{"delta": {"content": "OK"}}]}'
        yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}'
        yield "data: [DONE]"

    def read(self) -> bytes:
        return b""


class _BusyCtx:
    status_code = 429
    reason_phrase = "Too Many Requests"
    headers: dict = {}

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._body

    def iter_lines(self):
        yield from ()


def _registry(efforts, default_effort):
    mspec = SimpleNamespace(temperature=None, top_p=None, top_k=None, min_p=None)
    spec = SimpleNamespace(default_model="glm-5.4", models={"glm-5.4": mspec})

    class _Reg:
        providers = {"glm": spec}

        def client_params(self, provider_id, model_id):
            return {
                "base_url": "https://fake.local/v1",
                "model": model_id,
                "api_key": "k",
                "timeout_s": 30.0,
                "wire_protocol": "openai",
                "reasoning_efforts": tuple(efforts),
                "reasoning_default_effort": default_effort,
                "reasoning_effort_map": None,
                "send_tool_choice": True,
                "reasoning_split": False,
            }

        def reasoning_contract(self, provider_id, model_id):
            return True, "always_on_effort"

        def supports_thinking(self, provider_id, model_id):
            return True

    return _Reg()


def _engine(registry):
    return SimpleNamespace(
        llm_pool=SimpleNamespace(registry_snapshot=lambda: registry)
    )


def test_probe_uses_low_when_supported_and_matches_wire_payload():
    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = [_OKCtx()]
        result = _test_provider(
            _engine(_registry(("low", "medium", "high", "max"), "max")),
            "glm",
            "glm-5.4",
        )
    payload = stream.call_args.kwargs["json"]
    # 预审④: registry 默认档 max 不再覆盖探测意图 low
    assert payload["reasoning_effort"] == "low"
    assert result["reasoning_effort_resolved"] == "low"
    # always_on_effort 契约：canonical 解析档 == wire 序列化值
    assert payload["reasoning_effort"] == result["reasoning_effort_resolved"]
    assert stream.call_count == 1  # 单次物理请求
    assert result["ok"] is True
    assert result["response_received"] is True
    assert isinstance(result["latency_ms"], int)


def test_probe_keeps_registry_default_when_low_unsupported():
    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = [_OKCtx()]
        result = _test_provider(
            _engine(_registry(("medium", "high", "max"), "high")),
            "glm",
            "glm-5.4",
        )
    payload = stream.call_args.kwargs["json"]
    assert payload["reasoning_effort"] == "high"  # 不伪造模型拒绝的 low 档
    assert result["reasoning_effort_resolved"] == "high"
    assert stream.call_count == 1


def test_probe_busy_429_failure_stays_single_request():
    """预审③: 探测遇 429/1305 不得原地重试（繁忙/断连重试均已禁用）。"""
    body = json.dumps(
        {"error": {"code": "1305", "message": "模型并发负载已满，请稍后重试"}}
    ).encode("utf-8")
    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = [_BusyCtx(body)]
        with pytest.raises(_ProviderAdminError) as exc_info:
            _test_provider(
                _engine(_registry(("low", "medium", "high", "max"), "max")),
                "glm",
                "glm-5.4",
            )
    assert stream.call_count == 1
    # 机械失败事实仍带真实 HTTP 状态，不泄露 provider 响应正文
    assert "HTTP 429" in str(exc_info.value)
    assert "模型并发负载已满" not in str(exc_info.value)


def test_probe_disconnect_failure_stays_single_request():
    with mock.patch("httpx.Client") as client_cls:
        import httpx

        stream = client_cls.return_value.stream
        stream.side_effect = httpx.ConnectError("boom")
        with pytest.raises(_ProviderAdminError):
            _test_provider(
                _engine(_registry(("low", "medium", "high", "max"), "max")),
                "glm",
                "glm-5.4",
            )
    assert stream.call_count == 1  # retry_disconnect=0 生效
