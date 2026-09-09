"""P2-6(2026-08-15)：fallback 引擎级集成测试（审计补强项）.

构造真实 `_try_fallback_chain` 触发路径（非单测直接调 mixin）：
FakeLLM 主模型首轮抛 HTTP 500 → 引擎沿 MODEL_FALLBACKS 链降级成功。
断言：回答来自降级模型 + 当前用户结构化 fallback_receipt + architecture_status 快照
降级态可见；成功降级事实不写入会话 prompt；4xx 不进入 availability failover。
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.core.message import Message, MessageSource
from llm_loop.llm.client import LLMResponse
from llm_loop.llm.errors import LLMHTTPError
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import load_registry
from tests.conftest import FakeLLM


def _wire_fallback_pool(engine, fake_primary, fake_settings, monkeypatch):
    """把引擎的 llm_pool 换成"主 fake 失败 + fb provider 成功"的真实注册表池."""
    import dataclasses

    # client_params 从环境变量读 key（密钥不出域语义）——测试进程补 fake env
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    new_settings = dataclasses.replace(  # Settings frozen → replace 重建（非打补丁）
        fake_settings,
        model_providers_raw=json.dumps(
            {
                "primary": {
                    "api_key_env": "LLM_API_KEY",
                    "base_url": "https://fake.local/v1",
                    "models": {"fake-model": {}},
                },
                "fb": {
                    "api_key_env": "LLM_API_KEY",
                    "base_url": "https://fake-fb.local/v1",
                    "models": {"fb-model": {}},
                },
            }
        ),
        model_fallbacks_raw="fb/fb-model",
    )
    engine.settings = new_settings  # 引擎状态维度（config_status）读新配置
    registry = load_registry(new_settings)
    fake_primary.model = "fake-model"  # pool.get_default_model() 读 default_client.model
    fake_fb = FakeLLM([LLMResponse(content="降级模型回答", tool_calls=[], provider="fake")])
    pool = ModelClientPool(  # type: ignore[arg-type] — FakeLLM duck typing
        registry=registry,
        default_client=fake_primary,
        model_fallbacks_raw=new_settings.model_fallbacks_raw,
    )
    pool._provider_cache["fb"] = fake_fb  # type: ignore[assignment]  # noqa: SLF001 — test duck client
    engine.llm_pool = pool
    return fake_fb, new_settings


def test_fallback_500_triggers_chain_success(build_test_engine, fake_settings, monkeypatch):
    """主模型 500 → 降级链成功：回答来自降级模型 + 回执/状态/配置计数三可见."""

    def raise_500(calls):  # noqa: ARG001
        raise LLMHTTPError("upstream boom", status_code=500, provider="fake")

    engine, fake = build_test_engine([raise_500])
    fake_fb, new_settings = _wire_fallback_pool(engine, fake, fake_settings, monkeypatch)

    sid = engine.session.create()
    result = engine.run(sid, "hello")

    # ① 回答来自降级模型
    assert result.final_answer == "降级模型回答"
    assert fake_fb.calls, "降级候选未被调用"
    assert result.fallback_receipt == {
        "from": "primary/fake-model",
        "to": "fb/fb-model",
        "reason": "HTTP 500 上游错误",
    }
    # ② R8.9: fallback call 已经完成后不再把 notice 写进未来 prompt history。
    sess = engine.session.load(sid)
    assert not any("[模型降级:" in (m.content or "") for m in sess.messages)
    assert not (Path(new_settings.data_dir) / "state" / "fallback_notice_stamps.json").exists()
    # ③ architecture_status 快照降级态仍可见
    snap = engine.status.snapshot(session_id=sid)
    fb_state = snap.get("model_fallback") or snap.get("fallback") or {}
    assert fb_state.get("active") is True, f"快照降级态不可见: {list(snap)[:8]}"
    assert fb_state.get("to") == "fb/fb-model"
    # ④ config_status 降级链计数可见
    cfg = new_settings.to_status_dict()
    assert cfg["model_fallbacks_count"] == 1


def test_fallback_400_not_eligible(build_test_engine, fake_settings, monkeypatch):
    """零回归：4xx（非 429）不降级——如实反馈路径，降级候选不被调用."""

    def raise_400(calls):  # noqa: ARG001
        raise LLMHTTPError("bad request", status_code=400, provider="fake")

    engine, fake = build_test_engine([raise_400])
    fake_fb, _ns = _wire_fallback_pool(engine, fake, fake_settings, monkeypatch)

    sid = engine.session.create()
    result = engine.run(sid, "hello")

    assert not fake_fb.calls, "4xx 错误不应触发降级链"
    assert "[LLM 调用异常]" in result.final_answer


def test_fallback_chain_all_failed_summary(build_test_engine, fake_settings, monkeypatch):
    """链全失败：注入汇总消息（含各候选失败原因），回答走原异常如实反馈."""

    def raise_500(calls):  # noqa: ARG001
        raise LLMHTTPError("upstream boom", status_code=500, provider="fake")

    engine, fake = build_test_engine([raise_500])
    fake_fb, _ns = _wire_fallback_pool(engine, fake, fake_settings, monkeypatch)
    # 降级候选也失败
    fake_fb._responses = [raise_500]  # noqa: SLF001

    sid = engine.session.create()
    result = engine.run(sid, "hello")

    sess = engine.session.load(sid)
    assert not any(
        m.role == "system" and "[模型降级] 事实" in (m.content or "") for m in sess.messages
    )
    assert "[LLM 调用异常]" in result.final_answer
    assert "降级链全部失败" in result.final_answer


def test_cross_provider_fallback_rebuilds_reasoning_projection(
    build_test_engine, fake_settings, monkeypatch
):
    """R8.21: GLM primary -> DeepSeek fallback must rebuild provider-specific history."""
    import dataclasses

    def raise_500(calls):  # noqa: ARG001
        raise LLMHTTPError("glm upstream boom", status_code=500, provider="fake")

    engine, primary = build_test_engine([raise_500])
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    settings = dataclasses.replace(
        fake_settings,
        model_providers_raw=json.dumps(
            {
                "glm": {
                    "api_key_env": "LLM_API_KEY",
                    "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
                    "models": {"glm-primary": {"thinking": True}},
                },
                "deepseek": {
                    "api_key_env": "LLM_API_KEY",
                    "base_url": "https://api.deepseek.com/v1",
                    "models": {"deepseek-backup": {"thinking": True}},
                },
            }
        ),
        model_fallbacks_raw="deepseek/deepseek-backup",
    )
    engine.settings = settings
    registry = load_registry(settings)
    primary.model = "glm-primary"
    backup = FakeLLM([LLMResponse(content="fallback-ok", tool_calls=[], provider="fake")])
    pool = ModelClientPool(  # type: ignore[arg-type]
        registry=registry,
        default_client=primary,
        model_fallbacks_raw=settings.model_fallbacks_raw,
    )
    pool._provider_cache["deepseek"] = backup  # type: ignore[assignment]  # noqa: SLF001 — test duck client
    engine.llm_pool = pool

    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.messages.extend(
        [
            Message(role="user", content="OLD-Q", source=MessageSource.USER),
            Message(
                role="assistant",
                content="OLD-A",
                reasoning_content="OLD-NON-TOOL-REASONING",
                source=MessageSource.USER,
                model_used="legacy/model",
            ),
        ]
    )
    engine.session.save(sess)

    result = engine.run(sid, "NEXT-Q")

    assert result.final_answer == "fallback-ok"
    assert primary.calls and backup.calls
    primary_history = primary.calls[0]["messages"]
    fallback_history = backup.calls[0]["messages"]
    primary_assistant = next(
        m for m in primary_history if m.get("role") == "assistant" and m.get("content") == "OLD-A"
    )
    fallback_assistant = next(
        m for m in fallback_history if m.get("role") == "assistant" and m.get("content") == "OLD-A"
    )
    assert primary_assistant["reasoning_content"] == "OLD-NON-TOOL-REASONING", (
        "GLM interleaved thinking keeps still-visible historical reasoning; "
        "fallback rebuild must not rely on a stale strip policy"
    )
    assert fallback_assistant["reasoning_content"] == "OLD-NON-TOOL-REASONING", (
        "DeepSeek fallback must rebuild from session truth rather than reuse GLM-projected messages"
    )
