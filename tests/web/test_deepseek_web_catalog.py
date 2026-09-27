from __future__ import annotations

from fastapi.testclient import TestClient

from llm_loop.config import Settings
from llm_loop.factory import build_engine
from llm_loop.web import build_app


def test_models_catalog_exposes_deepseek_web_display_and_two_reasoning_levels(tmp_path):
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://example.invalid/v1",
        llm_model="default-model",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        deepseek_web_enabled=True,
        deepseek_web_cdp_endpoint="http://127.0.0.1:1",
        deepseek_web_root_url="https://chat.deepseek.com/",
    )
    engine = build_engine(settings)
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
    engine.close()
