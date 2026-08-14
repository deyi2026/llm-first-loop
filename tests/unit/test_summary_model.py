"""R6: 独立摘要模型配置测试.

验证:
- SUMMARY_MODEL 指定独立模型时, Summarizer 用独立 client
- SUMMARY_MODEL 未配置时回退主模型（零回归）
- 独立模型不在注册表时如实 warning + 回退主模型
"""
from __future__ import annotations

import json

import pytest

from llm_loop.config import Settings

_PROVIDERS = json.dumps(
    {
        "p": {
            "base_url": "https://api.deepseek.com/v1",
            "api_key_env": "DEEPSEEK_API_KEY",
            "models": {
                "m-fast": {"context": 131072, "thinking": False, "cost_tier": "low"},
                "m-pro": {"context": 131072, "thinking": True, "cost_tier": "high"},
            },
            "default_model": "m-fast",
        }
    }
)


def _settings(tmp_path, **overrides) -> Settings:
    base = {
        "llm_api_key": "k",
        "llm_base_url": "https://api.deepseek.com/v1",
        "llm_model": "m-fast",
        "data_dir": str(tmp_path / "data"),
        "extract_enabled": False,
        "summary_mode": "sync",
        "model_providers_raw": _PROVIDERS,
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture(autouse=True)
def _provider_api_key(monkeypatch):
    """provider 注册表 api_key_env=DEEPSEEK_API_KEY 需要环境变量存在（M60 类环境自足修复）."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")


def test_summary_model_not_configured_uses_main(tmp_path):
    """SUMMARY_MODEL 未配置 → Summarizer 用主模型 client（零回归）."""
    from llm_loop.factory import build_engine

    engine = build_engine(_settings(tmp_path))  # type: ignore[arg-type]
    assert engine.summarizer is not None
    assert engine.summarizer.llm is not None
    assert engine.summarizer.llm.model == "m-fast"


def test_summary_model_configured_uses_independent(tmp_path):
    """SUMMARY_MODEL 指定独立模型 → Summarizer 用独立 client."""
    from llm_loop.factory import build_engine

    engine = build_engine(_settings(tmp_path, summary_model="p/m-pro"))  # type: ignore[arg-type]
    assert engine.summarizer is not None
    assert engine.summarizer.llm is not None
    assert engine.summarizer.llm.model == "m-pro"


def test_summary_model_invalid_falls_back_with_warning(tmp_path, caplog):
    """独立模型不在注册表 → 如实 warning + 回退主模型（fail-open）."""
    import logging

    from llm_loop.factory import build_engine

    with caplog.at_level(logging.WARNING):
        engine = build_engine(  # type: ignore[arg-type]
            _settings(tmp_path, summary_model="ghost/not-exist")
        )
    assert engine.summarizer is not None
    assert engine.summarizer.llm is not None
    assert engine.summarizer.llm.model == "m-fast"  # 回退主模型
    assert any("独立摘要模型" in r.message and "回退主模型" in r.message for r in caplog.records)
