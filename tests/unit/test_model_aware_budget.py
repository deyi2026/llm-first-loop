"""M54 模型窗口感知主动压缩测试（founder 2026-08-11 指令, k3-256k 事故治本）.

核心: 压缩预算从全局静态 1M → min(全局, 模型 context × 2字符/token × 0.5)。
小窗模型 (262144 tokens ≈ 26万字符预算) 提前压缩, 不再等爆了才拒。

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

# 256K 窗口 provider（对齐 kimi/k3-256k 规格）
_K256_JSON = json.dumps(
    {
        "kimi": {
            "base_url": "https://api.kimi.com/coding/v1",
            "api_key_env": "KIMI_API_KEY",
            "models": {
                "k3-256k": {"context": 262144, "thinking": True, "cost_tier": "mid"},
                "k3": {"context": 1000000, "thinking": True, "cost_tier": "mid"},
            },
            "default_model": "k3-256k",
        },
    }
)


def _stuff_history(engine, sid, total_chars: int) -> None:
    """向会话填充指定总量的历史消息（模拟长期对话）."""
    sess = engine.session.load(sid)
    from llm_loop.core.message import Message, MessageSource

    per_msg = 5000
    for i in range(total_chars // per_msg):
        sess.messages.append(
            Message(role="user", content=f"历史消息{i} " + "x" * (per_msg - 20), source=MessageSource.USER)
        )
        sess.messages.append(
            Message(role="assistant", content=f"历史回答{i} " + "y" * (per_msg - 20), source=MessageSource.USER)
        )
    engine.session.save(sess)


def _received_history_chars(fake) -> int:
    """fake 收到的 messages 总字符数（含 system + 历史）."""
    return sum(len(json.dumps(m, ensure_ascii=False)) for m in fake.calls[-1]["messages"])


def test_small_window_model_compresses_proactively(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """256K 窗模型: 30万字符历史 → 主动压缩到 ~26万字符预算内（M54 核心）."""
    monkeypatch.setenv("KIMI_API_KEY", "k")
    settings = _settings(tmp_path, model_providers_raw=_K256_JSON, llm_model="k3-256k", history_max_chars=1_000_000)  # EVO-20260814: 显式 1M 模拟生产环境
    fake = _FakeLLMClient("k3-256k")
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)

    sid = engine.session.create()
    _stuff_history(engine, sid, 300000)  # 30万字符 > 26万预算, < 全局 1M

    result = engine.run(sid, "新问题")
    assert result.final_answer == "默认回答"
    # 全局 1M 预算不会压缩 30万; k3-256k 预算 (262144*2*0.5=262144) 应压缩
    received = _received_history_chars(fake)
    assert received < 290000, f"应压缩到预算内, 实际 {received}"


def test_large_window_model_unchanged(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """1M 窗模型 (kimi/k3): 30万字符历史 → 不压缩（预算 min(1M, 1M)=1M）."""
    monkeypatch.setenv("KIMI_API_KEY", "k")
    settings = _settings(tmp_path, model_providers_raw=_K256_JSON, llm_model="k3-256k")
    fake = _FakeLLMClient("k3-256k")
    pool = _make_pool(settings, fake, cached={"kimi": fake})
    engine = _make_engine(tmp_path, pool, settings)

    sid = engine.session.create()
    # 会话 override 到 1M 窗模型
    sess = engine.session.load(sid)
    sess.model_override = "kimi/k3"
    engine.session.save(sess)
    _stuff_history(engine, sid, 300000)

    result = engine.run(sid, "新问题")
    assert result.final_answer == "默认回答"
    received = _received_history_chars(fake)
    assert received >= 290000, f"1M 窗不应压缩 30万字符, 实际 {received}"


def test_effective_budget_math(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """预算计算: min(全局, context×2×0.5)."""
    monkeypatch.setenv("KIMI_API_KEY", "k")
    settings = _settings(tmp_path, model_providers_raw=_K256_JSON, llm_model="k3-256k")
    fake = _FakeLLMClient("k3-256k")
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)

    # 256K 窗: 262144 × 2 × 0.5 = 262144
    assert engine._effective_history_budget("kimi/k3-256k") == 262144
    # 1M 窗: min(1M全局, 1000000×2×0.5=1M) = 1M 全局
    # EVO-20260814: Settings.history_max_chars 默认 1M，测试 settings 显式不传 → 装配层走 _env_int 默认（无环境变量时 1000000）
    assert engine._effective_history_budget("kimi/k3") == 1_000_000
    # 未知模型 → 全局预算
    assert engine._effective_history_budget("ghost/x") == 1_000_000


def test_no_pool_zero_regression(build_test_engine) -> None:
    """无 pool → 全局预算（零回归）."""
    engine, fake = build_test_engine([{"content": "你好"}])
    fake.model = "fake-model"
    engine.llm_pool = None
    assert engine._effective_history_budget("") == engine._runtime_history_budget()
