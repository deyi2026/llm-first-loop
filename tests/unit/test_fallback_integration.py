"""P2-6(2026-08-15)：fallback 引擎级集成测试（审计补强项）.

构造真实 `_try_fallback_chain` 触发路径（非单测直接调 mixin）：
FakeLLM 主模型首轮抛 HTTP 500 → 引擎沿 MODEL_FALLBACKS 链降级成功。
断言：回答来自降级模型 + 会话注入 `[模型降级]` 回执 + architecture_status 快照
降级态可见 + config_status.model_fallbacks_count 可见；4xx 不降级（零回归）。
"""

from __future__ import annotations

import json

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
    pool._provider_cache["fb"] = fake_fb  # noqa: SLF001 — 预置缓存避免触网
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
    # ② 会话注入 [模型降级] 回执（system 消息，AI 可见）
    sess = engine.session.load(sid)
    assert any("[模型降级:" in (m.content or "") and "fb/fb-model" in m.content for m in sess.messages)
    # ③ architecture_status 快照降级态可见
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
    assert any("[模型降级] 事实" in (m.content or "") and "降级链全部失败" in m.content
               for m in sess.messages), "链全失败汇总未注入会话"
    assert "[LLM 调用异常]" in result.final_answer
