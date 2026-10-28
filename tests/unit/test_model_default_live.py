"""模型默认 live 切换（model-admin design §6.2.1/§6.2.2/§9.2-R4）.

覆盖: pool.set_default_model 先构造后提交 / get_default_ref 展示口径 /
get_client(None) 路由 / replace_registry 后 stale live ref 如实回退 /
routing 默认路径与 override 失效回退都走 live 默认（不再用冻结启动 client）。
零网络：client 构造是惰性的（LLMClient 构造不发请求）。
"""

from __future__ import annotations

import pytest

from llm_loop.llm.client import LLMClient
from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec
from tests.unit.test_model_attribution import _FakeLLMClient, _make_engine, _make_pool, _settings


def _aux_registry(pid: str = "aux", mid: str = "aux-model") -> ProviderRegistry:
    return ProviderRegistry(
        providers={
            pid: ProviderSpec(
                id=pid,
                base_url="https://aux.invalid/v1",
                api_key_env="",
                models={mid: ModelSpec(context=131_072)},
                default_model=mid,
            )
        }
    )


def test_live_default_ref_starts_as_startup_canonical(tmp_path) -> None:
    """未热切换：get_default_ref 返回启动默认 canonical，get_client(None) 零回归."""
    settings = _settings(tmp_path)
    default = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default)
    assert pool.live_default_ref() is None
    assert pool.get_default_ref() == "deepseek/deepseek-v4-flash"
    assert pool.get_client(None) is default


def test_set_default_model_commits_after_construction(tmp_path) -> None:
    """先 resolve+构造成功再提交；get_client(None) 立即路由新默认."""
    settings = _settings(tmp_path)
    default = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default)
    pool.replace_registry(_aux_registry())

    canonical = pool.set_default_model("aux/aux-model")
    assert canonical == "aux/aux-model"
    assert pool.live_default_ref() == "aux/aux-model"
    assert pool.get_default_ref() == "aux/aux-model"
    routed = pool.get_client(None)
    assert routed is not default
    assert isinstance(routed, LLMClient)
    assert routed.model == "aux-model"


def test_set_default_model_rejects_unknown_ref_without_side_effect(tmp_path) -> None:
    settings = _settings(tmp_path)
    default = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default)
    pool.replace_registry(_aux_registry())
    with pytest.raises(ValueError):
        pool.set_default_model("ghost/nope")
    assert pool.live_default_ref() is None, "构造失败不得提交默认"
    assert pool.get_client(None) is default


def test_replace_registry_stale_live_ref_falls_back_with_warning(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    """热切换默认在新表不可解析 → 如实回退启动默认（非静默指向不存在模型）."""
    import logging

    settings = _settings(tmp_path)
    default = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default)
    pool.replace_registry(_aux_registry())
    pool.set_default_model("aux/aux-model")
    assert pool.registry_generation() == 1

    with caplog.at_level(logging.WARNING):
        pool.replace_registry(_aux_registry(pid="other", mid="other-model"))
    assert pool.live_default_ref() is None
    assert pool.get_default_ref() == "deepseek/deepseek-v4-flash"
    assert pool.get_client(None) is default
    assert "aux/aux-model" in caplog.text
    assert pool.registry_generation() == 2


def test_registry_generation_increments_only_on_replace(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")  # 构造 deepseek client 需要 env key
    settings = _settings(tmp_path)
    default = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default)
    assert pool.registry_generation() == 0
    pool.set_default_model("deepseek/deepseek-v4-flash")
    assert pool.registry_generation() == 0, "默认切换不是 registry 变更"
    pool.replace_registry(_aux_registry())
    assert pool.registry_generation() == 1


def test_routing_default_path_and_stale_override_fallback_use_live_default(
    tmp_path,
) -> None:
    """§6.2.2: 主循环默认路径与 override 失效回退都走 pool live 默认."""
    settings = _settings(tmp_path)
    default = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default)
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create()
    sess = engine.session.load(sid)

    # 零回归：未热切换时默认标签仍是启动默认 canonical。
    decision0 = engine._routing._route_model(None, sess)  # noqa: SLF001
    assert decision0.model_used == "deepseek/deepseek-v4-flash"
    assert decision0.llm_client is default

    # 热切换后：默认请求路由到 live 默认，model_used 如实标注新模型。
    pool.replace_registry(_aux_registry())
    pool.set_default_model("aux/aux-model")
    decision1 = engine._routing._route_model(None, sess)  # noqa: SLF001
    assert decision1.model_used == "aux/aux-model"
    assert decision1.llm_client.model == "aux-model"
    assert decision1.llm_client is not default

    # 会话 override 失效（模型已被删）→ 回退 live 默认，而非冻结启动 client。
    stale = engine.session.create()
    engine.session.set_model_override(stale, "ghost/model", source="user")
    stale_sess = engine.session.load(stale)
    decision2 = engine._routing._route_model(None, stale_sess)  # noqa: SLF001
    assert decision2.model_used == "aux/aux-model"
    assert decision2.llm_client is decision1.llm_client
