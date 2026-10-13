"""web-carveout M3 改写：目录端点的 web 条目经外部注册模块注入（D2）。

原测试（settings.deepseek_web_* 静态注册 → 目录暴露）随内置注册分支删除；
新语义：配置 web_providers_module（stub 注入 deepseek-web spec）后目录端点
照常暴露；未配置则无 web 条目。display_name 硬编码映射保留在 routes.py
（仅展示名，无模块依赖）。
"""

from __future__ import annotations

import sys
import types

from fastapi.testclient import TestClient

from llm_loop.config import Settings
from llm_loop.factory import build_engine
from llm_loop.llm.providers import ModelSpec, ProviderSpec
from llm_loop.web import build_app


def _stub_module(monkeypatch, name: str = "stub_catalog_reg") -> None:
    spec = ProviderSpec(
        id="deepseek-web",
        base_url="browser://deepseek-web",
        api_key_env="",
        models={
            "web-deepseek": ModelSpec(
                context=131_072,
                reasoning_capable=True,
                reasoning_control="provider_owned",
                reasoning=True,
                reasoning_efforts=("instant", "high"),
                reasoning_default_effort="high",
                cost_tier="subscription",
                runtime_identity="deepseek-web-browser-surface",
            )
        },
        default_model="web-deepseek",
        timeout_s=120.0,
    )
    module = types.ModuleType(name)
    module.web_provider_specs = lambda: {"deepseek-web": spec}
    module.web_client_factories = lambda settings, *, transport_observer: {}
    monkeypatch.setitem(sys.modules, name, module)


def _settings(tmp_path, **extra):
    return Settings(
        llm_api_key="k",
        llm_base_url="https://example.invalid/v1",
        llm_model="default-model",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        **extra,
    )


def test_models_catalog_exposes_web_entry_via_external_registration(tmp_path, monkeypatch):
    _stub_module(monkeypatch)
    settings = _settings(tmp_path, web_providers_module="stub_catalog_reg")
    engine = build_engine(settings)
    try:
        client = TestClient(build_app(engine=engine))
        response = client.get("/api/v1/models")
        assert response.status_code == 200
        catalog = {row["id"]: row for row in response.json()["catalog"]}
        row = catalog["deepseek-web/web-deepseek"]
        assert row["display_name"] == "DeepSeek 网页版"
        assert row["reasoning_control"] == "provider_owned"
        assert row["reasoning_control_supported"] is True
        assert row["reasoning_efforts"] == ["instant", "high"]
        assert row["reasoning_default_effort"] == "high"
    finally:
        engine.close()


def test_models_catalog_has_no_web_entry_when_module_not_configured(tmp_path):
    settings = _settings(tmp_path)
    engine = build_engine(settings)
    try:
        client = TestClient(build_app(engine=engine))
        response = client.get("/api/v1/models")
        assert response.status_code == 200
        ids = {row["id"] for row in response.json()["catalog"]}
        assert not any(i.startswith(("deepseek-web/", "chatgpt-web/")) for i in ids)
    finally:
        engine.close()
