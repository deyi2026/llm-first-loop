"""M47 Provider 注册表测试（design §5.1/§5.2/§5.5）.

覆盖: env JSON 解析 / providers.json 文件通道 / LLM_* 合成零回归 /
malformed JSON fail-soft / resolve 全限定+裸名唯一+歧义+未知 /
supports_thinking 元数据驱动 / 密钥仅存 env 名 / client_params 缺失如实报错。

全部 Mock/构造输入, 零真实网络。
"""

from __future__ import annotations

import json

import pytest

from llm_loop.config import Settings
from llm_loop.llm.providers import load_registry


def _settings(**overrides) -> Settings:
    """构造最小 Settings（仅 M47 相关字段）."""
    base = {
        "llm_api_key": "test-key",
        "llm_base_url": "https://api.deepseek.com/v1",
        "llm_model": "deepseek-v4-flash",
        "data_dir": "./data",
        "model_providers_raw": "",
    }
    base.update(overrides)
    return Settings(**base)


_TWO_PROVIDER_JSON = json.dumps(
    {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "api_key_env": "DEEPSEEK_API_KEY",
            "models": {
                "deepseek-v4-flash": {"context": 1000000, "thinking": True, "cost_tier": "low"},
                "deepseek-v4-pro": {"context": 1000000, "thinking": True, "cost_tier": "high"},
            },
            "default_model": "deepseek-v4-flash",
        },
        "local": {
            "base_url": "http://localhost:1234/v1",
            "api_key_env": "",
            "models": {
                "qwen3.6-27b": {"context": 131072, "thinking": True, "cost_tier": "free"},
            },
            "default_model": "qwen3.6-27b",
        },
    }
)


# ── 加载通道 ──


def test_env_json_channel_parsed() -> None:
    """MODEL_PROVIDERS env JSON 正常解析（优先级 1）."""
    reg = load_registry(_settings(model_providers_raw=_TWO_PROVIDER_JSON))
    assert not reg.degraded
    assert set(reg.providers) == {"deepseek", "local"}
    ds = reg.providers["deepseek"]
    assert ds.base_url == "https://api.deepseek.com/v1"
    assert ds.api_key_env == "DEEPSEEK_API_KEY"
    assert ds.models["deepseek-v4-flash"].thinking is True
    assert ds.models["deepseek-v4-flash"].context == 1000000
    assert ds.models["deepseek-v4-pro"].cost_tier == "high"


def test_file_channel_parsed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """providers.json 文件通道（优先级 2, env 缺省时）."""
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "providers.json").write_text(_TWO_PROVIDER_JSON, encoding="utf-8")
    reg = load_registry(_settings(data_dir=str(data_dir)))
    assert not reg.degraded
    assert set(reg.providers) == {"deepseek", "local"}


def test_env_json_priority_over_file(tmp_path) -> None:
    """env JSON 优先于 providers.json."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "providers.json").write_text(
        json.dumps({"other": {"base_url": "http://x", "api_key_env": "", "models": {}}}),
        encoding="utf-8",
    )
    reg = load_registry(_settings(data_dir=str(data_dir), model_providers_raw=_TWO_PROVIDER_JSON))
    assert "deepseek" in reg.providers
    assert "other" not in reg.providers


def test_l0_synthesis_zero_regression() -> None:
    """L0 合成路径: 无注册表配置时从 LLM_* env 合成单 provider（零回归）."""
    reg = load_registry(_settings())
    assert not reg.degraded
    assert set(reg.providers) == {"deepseek"}
    spec = reg.providers["deepseek"]
    assert spec.api_key_env == "LLM_API_KEY"
    # 零回归语义: deepseek.com URL → thinking=True（对齐原 _thinking_supported 行为）
    assert spec.models["deepseek-v4-flash"].thinking is True
    assert spec.default_model == "deepseek-v4-flash"


def test_l0_synthesis_non_deepseek_no_thinking() -> None:
    """L0 合成: 非 deepseek URL → thinking=False（对齐原行为）."""
    reg = load_registry(
        _settings(llm_base_url="https://api.minimax.chat/v1", llm_model="MiniMax-M3")
    )
    assert set(reg.providers) == {"minimax"}
    assert reg.providers["minimax"].models["MiniMax-M3"].thinking is False


def test_malformed_env_json_fail_soft() -> None:
    """malformed MODEL_PROVIDERS → fail-soft 回退 L0 合成 + degraded 如实标注."""
    reg = load_registry(_settings(model_providers_raw="{not valid json"))
    assert reg.degraded is True
    assert "MODEL_PROVIDERS" in reg.degraded_reason
    # 回退后仍可用（L0 合成）
    assert "deepseek" in reg.providers


def test_non_dict_env_json_fail_soft() -> None:
    """MODEL_PROVIDERS 顶层非 object → fail-soft."""
    reg = load_registry(_settings(model_providers_raw='["a", "b"]'))
    assert reg.degraded is True


# ── resolve ──


def test_resolve_full_qualified() -> None:
    """全限定 provider/model 解析."""
    reg = load_registry(_settings(model_providers_raw=_TWO_PROVIDER_JSON))
    assert reg.resolve("deepseek/deepseek-v4-pro") == ("deepseek", "deepseek-v4-pro")
    assert reg.resolve("local/qwen3.6-27b") == ("local", "qwen3.6-27b")


def test_resolve_bare_unique() -> None:
    """裸模型名唯一匹配."""
    reg = load_registry(_settings(model_providers_raw=_TWO_PROVIDER_JSON))
    assert reg.resolve("deepseek-v4-pro") == ("deepseek", "deepseek-v4-pro")
    assert reg.resolve("qwen3.6-27b") == ("local", "qwen3.6-27b")


def test_resolve_bare_ambiguous() -> None:
    """裸名跨 provider 歧义 → ValueError 列候选."""
    raw = json.dumps(
        {
            "a": {"base_url": "http://a", "api_key_env": "", "models": {"m1": {}}},
            "b": {"base_url": "http://b", "api_key_env": "", "models": {"m1": {}}},
        }
    )
    reg = load_registry(_settings(model_providers_raw=raw))
    with pytest.raises(ValueError, match="多个 provider 匹配"):
        reg.resolve("m1")


def test_resolve_unknown_model_lists_candidates() -> None:
    """未知模型 → ValueError 含候选列表（如实反馈）."""
    reg = load_registry(_settings(model_providers_raw=_TWO_PROVIDER_JSON))
    with pytest.raises(ValueError, match="不在注册表中"):
        reg.resolve("nonexistent-model")


def test_resolve_unknown_provider() -> None:
    """全限定但 provider 未知 → ValueError."""
    reg = load_registry(_settings(model_providers_raw=_TWO_PROVIDER_JSON))
    with pytest.raises(ValueError, match="未知 provider"):
        reg.resolve("ghost/some-model")


# ── supports_thinking ──


def test_supports_thinking_metadata_driven() -> None:
    """思考支持由元数据驱动（消除 deepseek.com 硬编码）."""
    reg = load_registry(_settings(model_providers_raw=_TWO_PROVIDER_JSON))
    assert reg.supports_thinking("deepseek", "deepseek-v4-flash") is True
    assert reg.supports_thinking("local", "qwen3.6-27b") is True
    # 未知条目 → False（安全默认）
    assert reg.supports_thinking("ghost", "x") is False


# ── 密钥安全 ──


def test_api_key_only_env_name_stored() -> None:
    """注册表只存 env var 名字, 不存 key 本体."""
    reg = load_registry(_settings(model_providers_raw=_TWO_PROVIDER_JSON))
    spec = reg.providers["deepseek"]
    assert spec.api_key_env == "DEEPSEEK_API_KEY"
    # 序列化注册表任意字段不应包含真实 key 值
    assert "test-key" not in str(spec.__dict__)


def test_client_params_reads_key_on_demand(monkeypatch: pytest.MonkeyPatch) -> None:
    """client_params 按需从 env 读 key."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key-xyz")
    reg = load_registry(_settings(model_providers_raw=_TWO_PROVIDER_JSON))
    params = reg.client_params("deepseek", "deepseek-v4-flash")
    assert params == {
        "api_key": "real-key-xyz",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
    }


def test_client_params_missing_key_truthful_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """key 缺失 → 如实报错含 env var 名字."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    reg = load_registry(_settings(model_providers_raw=_TWO_PROVIDER_JSON))
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY 未设置"):
        reg.client_params("deepseek", "deepseek-v4-flash")


def test_client_params_no_auth_provider() -> None:
    """api_key_env 为空（本地 provider）→ 无需 key."""
    reg = load_registry(_settings(model_providers_raw=_TWO_PROVIDER_JSON))
    params = reg.client_params("local", "qwen3.6-27b")
    assert params["api_key"] == ""
    assert params["base_url"] == "http://localhost:1234/v1"


# ── catalog_summary ──


def test_catalog_summary_human_readable() -> None:
    """catalog_summary 含 provider/模型/能力（供 M48 model_catalog 工具复用）."""
    reg = load_registry(_settings(model_providers_raw=_TWO_PROVIDER_JSON))
    summary = reg.catalog_summary()
    assert "[deepseek]" in summary
    assert "deepseek-v4-flash" in summary
    assert "thinking=✓" in summary
    assert "[local]" in summary


def test_catalog_summary_degraded_annotated() -> None:
    """degraded 状态在 catalog 中如实标注."""
    reg = load_registry(_settings(model_providers_raw="{bad"))
    assert "[degraded:" in reg.catalog_summary()


# ── Settings 集成 ──


def test_settings_status_dict_exposes_flag_not_json() -> None:
    """to_status_dict 暴露 bool 标志, 不暴露原始 JSON."""
    s = _settings(model_providers_raw=_TWO_PROVIDER_JSON)
    status = s.to_status_dict()
    assert status["model_providers_configured"] is True
    # 原始 JSON 内容（api_key_env 名/models 结构）不暴露
    assert "DEEPSEEK_API_KEY" not in json.dumps(status)
    assert "api_key_env" not in json.dumps(status)


def test_settings_default_no_registry() -> None:
    """默认无 MODEL_PROVIDERS → 标志 False（零回归）."""
    s = _settings()
    assert s.to_status_dict()["model_providers_configured"] is False
