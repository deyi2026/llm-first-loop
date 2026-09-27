"""R4 → R8.24-B: overflow 处理测试.

验证:
- is_overflow_error 模式识别正确
- 退役 overflow 教程生产者不存在于生产源码
- R8.24-B B-D5 集成: 首次 overflow 确定性收缩重发（零注入）、二次终止
"""
from __future__ import annotations

from llm_loop.llm.errors import LLMError, LLMHTTPError, LLMTimeoutError, is_overflow_error


def test_is_overflow_error_patterns():
    """识别常见 overflow 错误模式."""
    assert is_overflow_error(LLMHTTPError("context length exceeded", status_code=400))
    assert is_overflow_error(LLMError("request_too_large"))
    assert is_overflow_error(LLMError("input token count exceeds maximum"))
    assert is_overflow_error(LLMError("maximum context length is 8192"))
    assert is_overflow_error(LLMError("prompt is too long"))
    assert is_overflow_error(LLMError("input too long"))


def test_is_overflow_error_non_overflow():
    """非 overflow 错误返回 False."""
    assert not is_overflow_error(LLMTimeoutError("timeout"))
    assert not is_overflow_error(LLMHTTPError("not found", status_code=404))
    assert not is_overflow_error(LLMError("rate limit exceeded"))
    assert not is_overflow_error(LLMError("internal server error"))


# ── EVO-20260921-51d12fa6: GLM 400 code 1261 分型回归（hev0 P3 t3 实测） ──

_GLM_1261_BODY = '{"error":{"code":"1261","message":"Prompt exceeds max length"}}'


def test_is_overflow_error_glm_1261_code_path():
    """GLM 400 code=1261 识别为 overflow（文案路径 + 码路径）."""
    # 实测签名: 文案命中模式（provider 归属无关，短语明确）
    exc = LLMHTTPError(
        "LLMHTTPError: HTTP 400: Bad Request | " + _GLM_1261_BODY,
        status_code=400, body=_GLM_1261_BODY, provider="glm",
    )
    assert is_overflow_error(exc)
    # 文案改写（本地化/措辞变化）时按 provider+status+码识别
    body2 = '{"error":{"code":"1261","message":"输入长度超过上限"}}'
    assert is_overflow_error(
        LLMHTTPError("HTTP 400 | " + body2, status_code=400, body=body2, provider="glm")
    )
    # 字符串化 body（转义 JSON 一层）同命中——parse_provider_error_code 三层解包
    body3 = '"' + _GLM_1261_BODY.replace('"', '\\"') + '"'
    assert is_overflow_error(
        LLMHTTPError("HTTP 400 | " + body3, status_code=400, body=body3, provider="glm-api")
    )


def test_is_overflow_error_1261_not_hijacked():
    """码保护: 非 GLM 族同码不判 overflow；GLM 族其他 400 业务码不误判."""
    # 非 GLM provider 的 1261 码（异义保护）
    body = '{"error":{"code":"1261","message":"something else entirely"}}'
    assert not is_overflow_error(
        LLMHTTPError("HTTP 400 | " + body, status_code=400, body=body, provider="deepseek")
    )
    # GLM 族其他业务码（如 1210 参数校验）不误判
    body2 = '{"error":{"code":"1210","message":"invalid request body"}}'
    assert not is_overflow_error(
        LLMHTTPError("HTTP 400 | " + body2, status_code=400, body=body2, provider="glm")
    )
    # GLM 族 1261 但非 400 状态不按码判定（文案用非英文短语，隔离码路径）
    body4 = '{"error":{"code":"1261","message":"输入长度超过上限"}}'
    assert not is_overflow_error(
        LLMHTTPError("HTTP 500 | " + body4, status_code=500, body=body4, provider="glm")
    )


# ── R4 → R8.24-B B-D5: overflow 确定性 runtime 处理（零 prompt 注入）集成测试 ──


def test_overflow_first_shrinks_budget_and_continues(build_test_engine):
    """R8.24-B B-D5: 首次 overflow → 确定性收缩重发（continue），sess 零注入."""

    def raise_overflow(history):
        raise LLMHTTPError("context length exceeded", status_code=400)

    engine, fake = build_test_engine([
        raise_overflow,
        {"content": "已处理overflow"},
    ])
    result = engine.run("s1", "你好")
    assert "已处理overflow" in result.final_answer
    assert len(fake.calls) == 2  # continue 后第二次调用在场
    sess = engine.session.load("s1")
    overflow_sys = [m for m in sess.messages if "上下文溢出" in m.content and m.role == "system"]
    assert len(overflow_sys) == 0  # 零注入


def test_overflow_second_time_ends_loop(build_test_engine):
    """R8.24-B B-D5: 第二次 overflow 直接确定性终止（纯事实终态，无注入）."""
    def raise_overflow(history):
        raise LLMHTTPError("context length exceeded", status_code=400)

    engine, _fake = build_test_engine([raise_overflow, raise_overflow])
    result = engine.run("s2", "你好")
    assert result.final_answer.startswith("[上下文窗口超限]")
    sess = engine.session.load("s2")
    overflow_sys = [m for m in sess.messages if "上下文溢出" in m.content and m.role == "system"]
    assert len(overflow_sys) == 0
