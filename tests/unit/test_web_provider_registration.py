"""web-carveout M3 接缝测试：外部 web provider 注册模块（D2/D3）。

旧的两个 registration 测试（deepseek/chatgpt 各一，测中间件内置
load_registry web 分支）随硬编码分支删除改写为本文件——语义从
「settings.web_*_enabled 静态注册」变为「settings.web_providers_module
外部注册模块动态注入」：

- 未配置 → 无 web 条目（等价旧 enabled=0 形态）
- 配置 → ProviderSpec 注入目录 + build_engine 懒挂 factory
- id 冲突 → warning + 不注册
- 配置了但加载/调用失败 → warning + 不注册（degraded，不阻断构建）
- web_providers_module_path → sys.path 注入机制（D3 独立项目免安装加载）
"""

from __future__ import annotations

import sys
import types
from dataclasses import replace

from llm_loop.config import Settings, load_settings
from llm_loop.factory import build_engine
from llm_loop.llm.providers import ModelSpec, ProviderSpec, load_registry


def _base_env(tmp_path):
    return {
        "DATA_DIR": str(tmp_path),
        "LLM_API_KEY": "test-key",
        "LLM_BASE_URL": "https://example.invalid/v1",
        "LLM_MODEL": "default-model",
    }


def _stub_spec(provider_id: str = "deepseek-web", model_id: str = "web-deepseek") -> ProviderSpec:
    return ProviderSpec(
        id=provider_id,
        base_url=f"browser://{provider_id}",
        api_key_env="",
        models={
            model_id: ModelSpec(
                context=131_072,
                reasoning_capable=True,
                reasoning_control="provider_owned",
                reasoning=True,
                reasoning_efforts=("instant", "high"),
                reasoning_default_effort="high",
                cost_tier="subscription",
                runtime_identity=f"{provider_id}-browser-surface",
            )
        },
        default_model=model_id,
        timeout_s=120.0,
    )


def _install_stub_module(monkeypatch, name: str, specs, factories=None, *, fail: bool = False):
    module = types.ModuleType(name)
    if fail:
        def _boom():
            raise RuntimeError("stub registration exploded")

        module.web_provider_specs = _boom
        module.web_client_factories = _boom
    else:
        module.web_provider_specs = lambda: dict(specs)
        module.web_client_factories = (
            lambda settings, *, transport_observer: dict(factories or {})
        )
    monkeypatch.setitem(sys.modules, name, module)
    return module


def test_web_provider_absent_when_module_not_configured(tmp_path):
    registry = load_registry(load_settings(_base_env(tmp_path)))
    assert "deepseek-web" not in registry.providers
    assert "chatgpt-web" not in registry.providers


def test_web_provider_registers_via_external_module(tmp_path, monkeypatch):
    _install_stub_module(
        monkeypatch,
        "stub_web_reg",
        {"deepseek-web": _stub_spec()},
    )
    settings = replace(
        load_settings(_base_env(tmp_path)),
        web_providers_module="stub_web_reg",
    )
    registry = load_registry(settings)
    assert registry.resolve("deepseek-web/web-deepseek") == (
        "deepseek-web",
        "web-deepseek",
    )
    spec = registry.providers["deepseek-web"]
    assert spec.base_url == "browser://deepseek-web"
    capable, control = registry.reasoning_contract("deepseek-web", "web-deepseek")
    assert capable is True and control == "provider_owned"


def test_factory_wires_external_web_client_lazily(tmp_path, monkeypatch):
    built = []

    def _builder():
        built.append(1)
        raise AssertionError("lazy wiring must not call builder at build time")

    _install_stub_module(
        monkeypatch,
        "stub_web_reg",
        {"deepseek-web": _stub_spec()},
        {"deepseek-web/web-deepseek": _builder},
    )
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://example.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        web_providers_module="stub_web_reg",
    )
    engine = build_engine(settings)
    assert engine.llm_pool.registry.resolve("deepseek-web/web-deepseek") == (
        "deepseek-web",
        "web-deepseek",
    )
    assert "deepseek-web/web-deepseek" in engine.llm_pool.external_client_factories
    assert "deepseek-web/web-deepseek" not in engine.llm_pool._provider_cache  # noqa: SLF001
    assert not built


def test_provider_id_conflict_does_not_override_existing(tmp_path, monkeypatch, caplog):
    # 冲突源：MODEL_PROVIDERS env JSON 注入一个 API deepseek 条目（自包含，
    # 不依赖工作区 providers.json——pytest 下 data_dir 为 tmp 隔离目录）。
    import json

    env = _base_env(tmp_path)
    env["MODEL_PROVIDERS"] = json.dumps(
        {
            "deepseek": {
                "enabled": True,
                "base_url": "https://api.deepseek.com/v1",
                "api_key_env": "DEEPSEEK_API_KEY",
                "models": {"deepseek-chat": {}},
                "default_model": "deepseek-chat",
            }
        }
    )
    _install_stub_module(
        monkeypatch,
        "stub_web_reg",
        {"deepseek": _stub_spec("deepseek", "web-x")},
    )
    settings = replace(
        load_settings(env),
        web_providers_module="stub_web_reg",
    )
    registry = load_registry(settings)
    # "deepseek" 是 API provider id；外部 web 条目不得覆盖（warning + 不注册）
    assert "deepseek" in registry.providers
    assert registry.providers["deepseek"].base_url == "https://api.deepseek.com/v1"
    assert "web-x" not in registry.providers["deepseek"].models
    assert any("已被现有配置占用" in r.message for r in caplog.records)


def test_registration_failure_degrades_without_blocking(tmp_path, monkeypatch, caplog):
    _install_stub_module(monkeypatch, "stub_web_reg", {}, fail=True)
    settings = replace(
        load_settings(_base_env(tmp_path)),
        web_providers_module="stub_web_reg",
    )
    registry = load_registry(settings)
    assert "deepseek-web" not in registry.providers
    assert any("web provider 注册模块加载失败" in r.message for r in caplog.records)
    # build_engine 同样不被可选通道失败阻断（degraded 继续构建）
    engine = build_engine(settings)
    assert engine.llm_pool.external_client_factories == {}


def test_missing_module_name_degrades_without_blocking(tmp_path, caplog):
    settings = replace(
        load_settings(_base_env(tmp_path)),
        web_providers_module="definitely_not_a_real_module_xyz",
    )
    registry = load_registry(settings)
    assert "deepseek-web" not in registry.providers
    assert any("web provider 注册模块加载失败" in r.message for r in caplog.records)


def test_invalid_external_provider_spec_is_ignored(tmp_path, monkeypatch, caplog):
    _install_stub_module(monkeypatch, "stub_bad_provider", {"invalid": object()})
    settings = replace(load_settings(_base_env(tmp_path)), web_providers_module="stub_bad_provider")
    registry = load_registry(settings)
    assert "invalid" not in registry.providers
    assert any("返回类型异常" in record.message for record in caplog.records)


def test_module_path_injection_loads_from_directory(tmp_path, monkeypatch):
    # D3：web_providers_module_path 注入 sys.path，独立项目免安装加载
    mod_root = tmp_path / "stubpkg_root"
    mod_root.mkdir()
    (mod_root / "stub_path_reg.py").write_text(
        "from llm_loop.llm.providers import ModelSpec, ProviderSpec\n"
        "SPEC = ProviderSpec(\n"
        "    id='chatgpt-web',\n"
        "    base_url='browser://chatgpt-web',\n"
        "    api_key_env='',\n"
        "    models={'web-gpt': ModelSpec(context=262144, reasoning=True)},\n"
        "    default_model='web-gpt',\n"
        ")\n"
        "def web_provider_specs():\n"
        "    return {'chatgpt-web': SPEC}\n"
        "def web_client_factories(settings, *, transport_observer):\n"
        "    return {}\n",
        encoding="utf-8",
    )
    assert str(mod_root) not in sys.path
    settings = replace(
        load_settings(_base_env(tmp_path)),
        web_providers_module="stub_path_reg",
        web_providers_module_path=str(mod_root),
    )
    registry = load_registry(settings)
    assert "chatgpt-web" in registry.providers
    assert str(mod_root) in sys.path  # 注入生效（进程内驻留，测试进程可接受）
