from __future__ import annotations

from dataclasses import replace

from llm_loop.config import Settings, load_settings
from llm_loop.factory import build_engine
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import load_registry


class _DefaultClient:
    model = "default-model"
    provider = "default"
    timeout_s = 120.0
    max_tokens = 16000
    thinking_mode = True
    reasoning_effort = "high"
    thinking_supported = False

    def close(self):
        return None


def _base_env(tmp_path):
    return {
        "DATA_DIR": str(tmp_path),
        "LLM_API_KEY": "test-key",
        "LLM_BASE_URL": "https://example.invalid/v1",
        "LLM_MODEL": "default-model",
    }


def _configured_settings(tmp_path):
    settings = load_settings(_base_env(tmp_path))
    return replace(
        settings,
        chatgpt_web_enabled=True,
        chatgpt_web_cdp_endpoint="http://127.0.0.1:9229",
        chatgpt_web_project_url="https://chatgpt.com/g/g-project/project",
        chatgpt_web_project_ref="g-project",
        chatgpt_web_project_name="LFL",
    )


def test_chatgpt_web_provider_is_absent_by_default(tmp_path):
    settings = load_settings(_base_env(tmp_path))
    registry = load_registry(settings)
    assert "chatgpt-web" not in registry.providers


def test_chatgpt_web_provider_registers_only_with_complete_explicit_config(tmp_path):
    settings = _configured_settings(tmp_path)
    registry = load_registry(settings)

    assert registry.resolve("chatgpt-web/web-gpt") == ("chatgpt-web", "web-gpt")
    spec = registry.providers["chatgpt-web"]
    assert spec.base_url == "browser://chatgpt-web"
    assert spec.api_key_env == ""
    capable, control = registry.reasoning_contract("chatgpt-web", "web-gpt")
    assert capable is True
    assert control == "provider_owned"


def test_external_browser_client_factory_is_lazy_and_cached(tmp_path):
    settings = _configured_settings(tmp_path)
    registry = load_registry(settings)
    made: list[object] = []

    def build():
        client = object()
        made.append(client)
        return client

    pool = ModelClientPool(
        registry=registry,
        default_client=_DefaultClient(),
        external_client_factories={"chatgpt-web/web-gpt": build},
    )

    assert made == []
    first = pool.get_client("chatgpt-web/web-gpt")
    second = pool.get_client("chatgpt-web/web-gpt")
    assert first is second
    assert made == [first]


def test_incomplete_chatgpt_web_config_does_not_create_dead_model_option(tmp_path):
    settings = replace(
        load_settings(_base_env(tmp_path)),
        chatgpt_web_enabled=True,
        chatgpt_web_project_url="https://chatgpt.com/g/g-project/project",
        chatgpt_web_project_ref="g-project",
        chatgpt_web_project_name="",
    )
    registry = load_registry(settings)
    assert "chatgpt-web" not in registry.providers


def test_factory_wires_chatgpt_web_as_lazy_runtime_model_without_opening_browser(tmp_path):
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://example.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        chatgpt_web_enabled=True,
        chatgpt_web_cdp_endpoint="http://127.0.0.1:1",
        chatgpt_web_project_url="https://chatgpt.com/g/g-project/project",
        chatgpt_web_project_ref="g-project",
        chatgpt_web_project_name="LFL",
    )

    engine = build_engine(settings)
    assert engine.llm_pool.registry.resolve("chatgpt-web/web-gpt") == (
        "chatgpt-web",
        "web-gpt",
    )
    assert "chatgpt-web/web-gpt" in engine.llm_pool.external_client_factories
    assert "chatgpt-web/web-gpt" not in engine.llm_pool._provider_cache  # noqa: SLF001
