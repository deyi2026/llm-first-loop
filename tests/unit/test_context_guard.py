"""M53 上下文超限前置守卫测试（founder 2026-08-11 拍板 B: kimi/k3-256k 401 教训）.

覆盖:
- 载荷超模型 context 上限 → 如实拒绝, 不发送请求 (fake.calls 为空)
- 载荷未超 → 正常调用
- 无 pool / 裸标签 / 注册表未知模型 → 守卫跳过, 不阻断
- 拒绝文案含模型标签 + 建议 + 估算口径如实说明

全部 Mock, 零真实网络。
"""

from __future__ import annotations

import json

import pytest

from .test_model_attribution import (  # noqa: F401
    _FakeLLMClient,
    _make_engine,
    _make_pool,
    _settings,
)

# 小窗口 provider: context=100 tokens（守卫阈值 90 tokens = 180 chars, system prompt 即超）
_TINY_CTX_JSON = json.dumps(
    {
        "tiny": {
            "base_url": "https://fake.local/v1",
            "api_key_env": "",
            "models": {
                "tiny-model": {"context": 100, "thinking": False, "cost_tier": "free"},
            },
            "default_model": "tiny-model",
        },
    }
)


def test_overflow_refuses_without_llm_call(tmp_path) -> None:
    """载荷超限 → 如实拒绝 + 未发送 LLM 请求."""
    settings = _settings(tmp_path, model_providers_raw=_TINY_CTX_JSON, llm_model="tiny-model")
    fake = _FakeLLMClient("tiny-model")
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)

    result = engine.run(engine.session.create(), "你好")
    assert "[上下文超限]" in result.final_answer
    assert "tiny/tiny-model" in result.final_answer
    assert "未发送请求" in result.final_answer
    assert len(fake.calls) == 0  # 关键: 未发注定失败的请求


def test_overflow_message_has_suggestions(tmp_path) -> None:
    """拒绝文案含可操作建议 + 估算口径如实说明."""
    settings = _settings(tmp_path, model_providers_raw=_TINY_CTX_JSON, llm_model="tiny-model")
    fake = _FakeLLMClient("tiny-model")
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)

    result = engine.run(engine.session.create(), "你好")
    assert "/model" in result.final_answer
    assert "估算" in result.final_answer


def test_under_limit_proceeds(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """载荷未超限 → 正常调用 LLM."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)  # deepseek-v4-flash context=1M
    fake = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)

    result = engine.run(engine.session.create(), "你好")
    assert result.final_answer == "默认回答"
    assert len(fake.calls) == 1


def test_guard_skipped_without_pool(build_test_engine) -> None:
    """无 pool（零回归路径）→ 守卫跳过, 正常调用."""
    engine, fake = build_test_engine([{"content": "你好"}])
    fake.model = "fake-model"
    engine.llm_pool = None
    result = engine.run(engine.session.create(), "你好")
    assert result.final_answer == "你好"


def test_guard_skipped_for_unknown_model(tmp_path) -> None:
    """client 无 model 属性（标签为空）→ 守卫跳过."""
    settings = _settings(tmp_path, model_providers_raw=_TINY_CTX_JSON, llm_model="tiny-model")
    fake = _FakeLLMClient("tiny-model")
    del fake.model  # 模拟无 model 属性的 stub → 标签空 → 守卫跳过
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)

    result = engine.run(engine.session.create(), "你好")
    assert result.final_answer == "默认回答"
    assert len(fake.calls) == 1
