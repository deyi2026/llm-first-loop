from __future__ import annotations

from dataclasses import replace

from llm_loop.config import Settings, load_settings
from llm_loop.factory import build_engine
from llm_loop.llm.providers import load_registry


def _base_env(tmp_path):
    return {
        "DATA_DIR": str(tmp_path),
        "LLM_API_KEY": "test-key",
        "LLM_BASE_URL": "https://example.invalid/v1",
        "LLM_MODEL": "default-model",
    }


def _configured(tmp_path):
    return replace(
        load_settings(_base_env(tmp_path)),
        deepseek_web_enabled=True,
        deepseek_web_cdp_endpoint="http://127.0.0.1:9229",
        deepseek_web_root_url="https://chat.deepseek.com/",
        deepseek_web_profile_label="fixture-deepseek",
    )


def test_deepseek_web_provider_is_absent_by_default(tmp_path):
    registry = load_registry(load_settings(_base_env(tmp_path)))
    assert "deepseek-web" not in registry.providers


def test_deepseek_web_provider_registers_independently_from_api_provider(tmp_path):
    settings = _configured(tmp_path)
    registry = load_registry(settings)

    assert registry.resolve("deepseek-web/web-deepseek") == (
        "deepseek-web",
        "web-deepseek",
    )
    spec = registry.providers["deepseek-web"]
    assert spec.base_url == "browser://deepseek-web"
    assert spec.api_key_env == ""
    capable, control = registry.reasoning_contract("deepseek-web", "web-deepseek")
    assert capable is True
    assert control == "provider_owned"
    model = spec.models["web-deepseek"]
    assert model.context == 131_072
    assert model.reasoning_efforts == ("instant", "high")
    assert model.reasoning_default_effort == "high"
    assert model.runtime_identity == "deepseek-web-browser-surface"


def test_chatgpt_and_deepseek_browser_providers_can_coexist(tmp_path):
    settings = replace(
        _configured(tmp_path),
        chatgpt_web_enabled=True,
        chatgpt_web_cdp_endpoint="http://127.0.0.1:9229",
        chatgpt_web_project_url="https://chatgpt.com/g/g-project/project",
        chatgpt_web_project_ref="g-project",
        chatgpt_web_project_name="LFL",
    )
    registry = load_registry(settings)
    assert "chatgpt-web" in registry.providers
    assert "deepseek-web" in registry.providers


def test_incomplete_deepseek_config_does_not_create_dead_model_option(tmp_path):
    settings = replace(
        load_settings(_base_env(tmp_path)),
        deepseek_web_enabled=True,
        deepseek_web_cdp_endpoint="",
    )
    registry = load_registry(settings)
    assert "deepseek-web" not in registry.providers


def test_factory_wires_deepseek_web_lazily_without_opening_browser(tmp_path):
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://example.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        deepseek_web_enabled=True,
        deepseek_web_cdp_endpoint="http://127.0.0.1:1",
        deepseek_web_root_url="https://chat.deepseek.com/",
    )
    engine = build_engine(settings)
    assert engine.llm_pool.registry.resolve("deepseek-web/web-deepseek") == (
        "deepseek-web",
        "web-deepseek",
    )
    assert "deepseek-web/web-deepseek" in engine.llm_pool.external_client_factories
    assert "deepseek-web/web-deepseek" not in engine.llm_pool._provider_cache  # noqa: SLF001


def test_deepseek_web_provider_uses_explicit_budget_and_reasoning(tmp_path):
    settings = replace(
        _configured(tmp_path),
        deepseek_web_context_tokens=262_144,
        deepseek_web_reasoning_effort="instant",
    )
    model = load_registry(settings).providers["deepseek-web"].models["web-deepseek"]
    assert model.context == 262_144
    assert model.long_context is True
    assert model.reasoning_default_effort == "instant"
