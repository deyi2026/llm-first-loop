"""ASSESS-20261008-project-audit rev3 §7 WP4b-3 回归: BUG-07.

修复契约: 状态输出区分"配置路由（registry 声明）"与"实际拨号目标（仅当
client 实际构造时观测，local 直连发现改写才记录）"；状态查询只读观测映射，
不触发服务发现、无新副作用；保密字段（userinfo/query/api_key）不泄露。
"""

from __future__ import annotations

from unittest import mock

from llm_loop.factory import assemble_effective_model_status
from llm_loop.llm import providers as providers_mod
from llm_loop.llm.providers import (
    ModelSpec,
    ProviderRegistry,
    ProviderSpec,
    dial_target_observation,
    public_url,
    reset_dial_observations,
)


def _registry() -> ProviderRegistry:
    return ProviderRegistry(
        providers={
            "local": ProviderSpec(
                id="local",
                base_url="http://127.0.0.1:1234/v1",
                api_key_env="",
                models={"small": ModelSpec(context=8192)},
            ),
            "cloud": ProviderSpec(
                id="cloud",
                base_url="https://user:pw@cloud.example/v1?api_key=SECRET",
                api_key_env="CLOUD_KEY",
                models={"big": ModelSpec(context=131072)},
            ),
        },
    )


def setup_function(function):
    reset_dial_observations()


# ───────────────────────── 无凭证地址化 ─────────────────────────


def test_public_url_strips_credentials():
    assert public_url("https://user:pw@h.example/v1?api_key=SECRET") == "https://h.example/v1"
    assert public_url("http://127.0.0.1:9999/v1") == "http://127.0.0.1:9999/v1"
    assert public_url("not a url") == ""


# ───────────────────────── 路由/拨号区分 ─────────────────────────


def test_status_route_and_dial_distinguished():
    reg = _registry()
    # 未实际构造 client: 拨号目标如 None（不虚构）
    s = assemble_effective_model_status(reg, "local/small", "current_run", "run")
    assert s["llm_base_url"] == "http://127.0.0.1:1234/v1"
    assert s["llm_base_url_kind"] == "registry_route"
    assert s["llm_dial_target"] is None
    # client 实际构造时发现改写了拨号目标 → 状态可区分
    _seed_key = providers_mod._observation_key(reg, "local", "small")
    providers_mod._DIAL_OBSERVATIONS[_seed_key] = "http://127.0.0.1:9999/v1"
    s2 = assemble_effective_model_status(reg, "local/small", "current_run", "run")
    assert s2["llm_base_url"] == "http://127.0.0.1:1234/v1"  # 路由声明不变
    assert s2["llm_dial_target"] == "http://127.0.0.1:9999/v1"  # 实际拨号事实


def test_status_no_secrets_in_output():
    reg = _registry()
    s = assemble_effective_model_status(reg, "cloud/big", "settings", "settings")
    blob = str(s)
    assert "SECRET" not in blob
    assert "user:pw" not in blob
    assert s["llm_base_url"] == "https://cloud.example/v1"


def test_status_registry_unavailable_explicit():
    s = assemble_effective_model_status(None, "x/y", "current_run", "run")
    assert s["llm_model"] == "x/y"
    assert s["llm_base_url"] is None
    assert s["llm_config_source"] == "run_registry_unavailable"
    assert s["llm_dial_target"] is None


# ───────────────────────── 拨号观测记录契约 ─────────────────────────


def test_client_params_rewrite_records_sanitized_dial_target(monkeypatch):
    reg = _registry()
    monkeypatch.setenv("LMS_DIRECT", "1")
    with mock.patch.object(
        providers_mod,
        "_discover_llama_server",
        return_value=("http://127.0.0.1:7777/v1?token=SECRET", "sk-local"),
    ):
        params = reg.client_params("local", "small")
    assert params["base_url"] == "http://127.0.0.1:7777/v1?token=SECRET"
    obs = dial_target_observation(reg, "local", "small")
    assert obs == "http://127.0.0.1:7777/v1"  # 无凭证化
    assert "SECRET" not in obs and "token" not in obs


def test_client_params_no_rewrite_no_observation(monkeypatch):
    reg = _registry()
    monkeypatch.setenv("LMS_DIRECT", "1")
    with mock.patch.object(providers_mod, "_discover_llama_server", return_value=None):
        reg.client_params("local", "small")
    assert dial_target_observation(reg, "local", "small") is None


def test_client_params_discovery_failure_fallback_no_observation(monkeypatch):
    reg = _registry()
    monkeypatch.setenv("LMS_DIRECT", "1")
    with mock.patch.object(
        providers_mod, "_discover_llama_server", side_effect=RuntimeError("down")
    ):
        params = reg.client_params("local", "small")  # fail-open 回退路由
    assert params["base_url"] == "http://127.0.0.1:1234/v1"
    assert dial_target_observation(reg, "local", "small") is None


def test_client_params_discovery_failure_invalidates_stale_observation(monkeypatch):
    """rev4: 先成功直连记 7777; 发现失败回退路由后旧观测必须失效.

    复现: dial 回退 1234 而 obs 仍 7777（状态显示失真旧值）。
    """
    reg = _registry()
    monkeypatch.setenv("LMS_DIRECT", "1")
    with mock.patch.object(
        providers_mod,
        "_discover_llama_server",
        return_value=("http://127.0.0.1:7777/v1", "sk-local"),
    ):
        params1 = reg.client_params("local", "small")
    assert params1["base_url"] == "http://127.0.0.1:7777/v1"
    assert dial_target_observation(reg, "local", "small") == "http://127.0.0.1:7777/v1"
    # llama-server 消失 → 发现抛错 → 拨号回退路由
    with mock.patch.object(
        providers_mod, "_discover_llama_server", side_effect=RuntimeError("down")
    ):
        params2 = reg.client_params("local", "small")
    assert params2["base_url"] == "http://127.0.0.1:1234/v1"
    assert dial_target_observation(reg, "local", "small") is None  # 旧 7777 不残留
    s = assemble_effective_model_status(reg, "local/small", "settings", "settings")
    assert s["llm_dial_target"] is None  # 状态不再显示失真旧值


def test_client_params_discovery_none_invalidates_stale_observation(monkeypatch):
    """发现返回 None（无候选）同样失效旧观测."""
    reg = _registry()
    monkeypatch.setenv("LMS_DIRECT", "1")
    _seed_key = providers_mod._observation_key(reg, "local", "small")
    providers_mod._DIAL_OBSERVATIONS[_seed_key] = "http://127.0.0.1:7777/v1"
    with mock.patch.object(providers_mod, "_discover_llama_server", return_value=None):
        params = reg.client_params("local", "small")
    assert params["base_url"] == "http://127.0.0.1:1234/v1"
    assert dial_target_observation(reg, "local", "small") is None


def test_client_params_direct_disabled_invalidates_stale_observation(monkeypatch):
    """LMS_DIRECT=0（或非 local 路由）: 拨号=路由，旧直连观测失效且不触发发现."""
    reg = _registry()
    monkeypatch.setenv("LMS_DIRECT", "0")
    _seed_key = providers_mod._observation_key(reg, "local", "small")
    providers_mod._DIAL_OBSERVATIONS[_seed_key] = "http://127.0.0.1:7777/v1"
    with mock.patch.object(providers_mod, "_discover_llama_server") as disc:
        params = reg.client_params("local", "small")
    disc.assert_not_called()
    assert params["base_url"] == "http://127.0.0.1:1234/v1"
    assert dial_target_observation(reg, "local", "small") is None


def test_client_params_rewrite_but_unparseable_url_no_fabricated_observation(monkeypatch):
    """改写发生但无凭证化失败（public_url 空）: 不虚构观测，也不残留旧值."""
    reg = _registry()
    monkeypatch.setenv("LMS_DIRECT", "1")
    _seed_key = providers_mod._observation_key(reg, "local", "small")
    providers_mod._DIAL_OBSERVATIONS[_seed_key] = "http://127.0.0.1:7777/v1"
    with mock.patch.object(
        providers_mod, "_discover_llama_server", return_value=("not a url", "sk")
    ):
        params = reg.client_params("local", "small")
    assert params["base_url"] == "not a url"  # 拨号确已改写
    assert dial_target_observation(reg, "local", "small") is None  # 但不虚构地址


def test_status_query_does_not_trigger_discovery():
    reg = _registry()
    with mock.patch.object(providers_mod, "_discover_llama_server") as disc:
        assemble_effective_model_status(reg, "local/small", "settings", "settings")
    disc.assert_not_called()  # 状态查询无新副作用


# ---------- ASSESS-20261008 BUG-07 §7.3 follow-up: 观测身份绑定（registry/run 隔离） ----------


def test_two_registries_same_label_do_not_share_dial_observation(monkeypatch):
    """验收1: A 的观测只对 A 可见；同标签 B 读到 None，且互不覆盖."""
    monkeypatch.setenv("LMS_DIRECT", "1")
    reg_a, reg_b = _registry(), _registry()
    with mock.patch.object(
        providers_mod, "_discover_llama_server", return_value=("http://127.0.0.1:7777/v1", "sk")
    ):
        reg_a.client_params("local", "small")
    assert dial_target_observation(reg_a, "local", "small") == "http://127.0.0.1:7777/v1"
    # B 同标签：读不到 A 的观测（直接读与状态组装两条路径）
    assert dial_target_observation(reg_b, "local", "small") is None
    st_b = assemble_effective_model_status(reg_b, "local/small", "settings", "settings")
    assert st_b["llm_dial_target"] is None
    # B 自己拨号后互不覆盖
    with mock.patch.object(
        providers_mod, "_discover_llama_server", return_value=("http://127.0.0.1:8888/v1", "sk")
    ):
        reg_b.client_params("local", "small")
    assert dial_target_observation(reg_a, "local", "small") == "http://127.0.0.1:7777/v1"
    assert dial_target_observation(reg_b, "local", "small") == "http://127.0.0.1:8888/v1"


def test_new_registry_instance_does_not_inherit_observation(monkeypatch):
    """验收2: 新 run 重建 registry（同配置同标签）不继承旧实例观测."""
    monkeypatch.setenv("LMS_DIRECT", "1")
    reg_old = _registry()
    with mock.patch.object(
        providers_mod, "_discover_llama_server", return_value=("http://127.0.0.1:7777/v1", "sk")
    ):
        reg_old.client_params("local", "small")
    reg_new = _registry()  # 新 run 以当前配置新建 registry 实例
    assert dial_target_observation(reg_new, "local", "small") is None
    st = assemble_effective_model_status(reg_new, "local/small", "current_run", "run")
    assert st["llm_dial_target"] is None


def test_registry_fallback_does_not_erase_other_registry_observation(monkeypatch):
    """验收4: B 的解析生命周期只失效 B 自己的观测，A 的事实不被删除/复活."""
    monkeypatch.setenv("LMS_DIRECT", "1")
    reg_a, reg_b = _registry(), _registry()
    with mock.patch.object(
        providers_mod, "_discover_llama_server", return_value=("http://127.0.0.1:7777/v1", "sk")
    ):
        reg_a.client_params("local", "small")
    with mock.patch.object(providers_mod, "_discover_llama_server", return_value=(None, None)):
        reg_b.client_params("local", "small")  # B: 服务未起 → 回退路由，只 pop B 的键
    assert dial_target_observation(reg_b, "local", "small") is None
    assert dial_target_observation(reg_a, "local", "small") == "http://127.0.0.1:7777/v1"


def test_identityless_snapshot_yields_none_without_global_leak(monkeypatch):
    """无身份 duck 快照（None/缺属性）：不虚构、也不回退泄漏旧式全局键."""
    monkeypatch.setenv("LMS_DIRECT", "1")
    reg = _registry()
    providers_mod._DIAL_OBSERVATIONS["local/small"] = "http://legacy/v1"  # 旧式无身份键残留
    with mock.patch.object(
        providers_mod, "_discover_llama_server", return_value=("http://127.0.0.1:7777/v1", "sk")
    ):
        reg.client_params("local", "small")

    class _DuckSnapshot:  # 无 _observation_scope 属性的快照
        pass

    assert dial_target_observation(_DuckSnapshot(), "local", "small") is None
    assert dial_target_observation(None, "local", "small") is None
    # 同身份正路径不受影响（验收3）
    assert dial_target_observation(reg, "local", "small") == "http://127.0.0.1:7777/v1"


def test_status_query_across_registries_has_no_discovery_side_effect(monkeypatch):
    """验收5: 跨 registry 状态查询零发现零副作用."""
    monkeypatch.setenv("LMS_DIRECT", "1")
    reg_a, reg_b = _registry(), _registry()
    with mock.patch.object(
        providers_mod, "_discover_llama_server", return_value=("http://127.0.0.1:7777/v1", "sk")
    ):
        reg_a.client_params("local", "small")
    with mock.patch.object(providers_mod, "_discover_llama_server") as disc:
        assemble_effective_model_status(reg_b, "local/small", "settings", "settings")
        assemble_effective_model_status(reg_a, "local/small", "settings", "settings")
    disc.assert_not_called()
