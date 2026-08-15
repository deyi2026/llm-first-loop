"""M47 Provider 注册表测试（design §5.1/§5.2/§5.5）.

覆盖: env JSON 解析 / providers.json 文件通道 / LLM_* 合成零回归 /
malformed JSON fail-soft / resolve 全限定+裸名唯一+歧义+未知 /
supports_thinking 元数据驱动 / 密钥仅存 env 名 / client_params 缺失如实报错。
P1-3（审计 #14）: 严格布尔解析（bool("false")==True 陷阱）/ 单条目非法独立跳过 +
warning 如实标注 / context 缺失回退默认值。

全部 Mock/构造输入, 零真实网络。
"""

from __future__ import annotations

import json
import logging

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


def test_l0_synthesis_zero_regression(tmp_path) -> None:
    """L0 合成路径: 无注册表配置时从 LLM_* env 合成单 provider（零回归）."""
    # data_dir 指向隔离目录，避免工作区 data/providers.json 影响（走 L0 通道）
    reg = load_registry(_settings(data_dir=str(tmp_path / "data")))
    assert not reg.degraded
    assert set(reg.providers) == {"deepseek"}
    spec = reg.providers["deepseek"]
    assert spec.api_key_env == "LLM_API_KEY"
    # 零回归语义: deepseek.com URL → thinking=True（对齐原 _thinking_supported 行为）
    assert spec.models["deepseek-v4-flash"].thinking is True
    assert spec.default_model == "deepseek-v4-flash"


def test_l0_synthesis_non_deepseek_no_thinking(tmp_path) -> None:
    """L0 合成: 非 deepseek URL → thinking=False（对齐原行为）."""
    reg = load_registry(
        _settings(
            llm_base_url="https://api.minimax.chat/v1",
            llm_model="MiniMax-M3",
            data_dir=str(tmp_path / "data"),
        )
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


# ── provider 级超时（timeout_s, 本地慢模型接入）──


def _timeout_provider_json(timeout: object) -> str:
    return json.dumps(
        {
            "local": {
                "base_url": "http://localhost:1234/v1",
                "api_key_env": "",
                "timeout_s": timeout,
                "models": {"qwen3.6-27b": {"context": 131072}},
                "default_model": "qwen3.6-27b",
            }
        }
    )


def test_provider_timeout_s_parsed() -> None:
    """provider 级 timeout_s 正常解析（本地慢模型接入）."""
    reg = load_registry(_settings(model_providers_raw=_timeout_provider_json(600)))
    assert reg.providers["local"].timeout_s == 600.0


def test_provider_timeout_s_absent_defaults_none() -> None:
    """未配置 timeout_s → None（全局 LLM_TIMEOUT_S 兜底, 零回归）."""
    reg = load_registry(_settings(model_providers_raw=_TWO_PROVIDER_JSON))
    assert reg.providers["local"].timeout_s is None
    assert reg.providers["deepseek"].timeout_s is None
    # client_params 不含 timeout_s 键（与既有返回契约零差异）
    assert "timeout_s" not in reg.client_params("local", "qwen3.6-27b")


def test_client_params_includes_timeout_when_set() -> None:
    """显式配置 timeout_s → client_params 下发（pool 据此构造 client）."""
    reg = load_registry(_settings(model_providers_raw=_timeout_provider_json(600)))
    params = reg.client_params("local", "qwen3.6-27b")
    assert params["timeout_s"] == 600.0


@pytest.mark.parametrize("bad", ["abc", -10, 0, "12x"])
def test_provider_timeout_s_invalid_warns_and_defaults(
    bad, caplog: pytest.LogCaptureFixture
) -> None:
    """非法 timeout_s → warning 如实告警 + 回退 None（全局兜底, 不拖垮注册表）."""
    with caplog.at_level(logging.WARNING, logger="llm_loop.llm.providers"):
        reg = load_registry(_settings(model_providers_raw=_timeout_provider_json(bad)))
    assert reg.providers["local"].timeout_s is None
    assert not reg.degraded
    assert any("timeout_s" in r.message and "local" in r.message for r in caplog.records)


def test_catalog_summary_shows_provider_timeout() -> None:
    """catalog_summary 标注 provider 级超时（model_catalog 可感知本地慢模型配置）."""
    reg = load_registry(_settings(model_providers_raw=_timeout_provider_json(600)))
    assert "timeout=600s" in reg.catalog_summary()


# ── provider 级历史预算（history_budget_chars, 本地慢模型收紧上下文）──


def _budget_provider_json(budget: object) -> str:
    return json.dumps(
        {
            "local": {
                "base_url": "http://localhost:1234/v1",
                "api_key_env": "",
                "history_budget_chars": budget,
                "models": {"qwen3.6-27b": {"context": 131072}},
                "default_model": "qwen3.6-27b",
            }
        }
    )


def test_provider_history_budget_parsed() -> None:
    """provider 级 history_budget_chars 正常解析."""
    reg = load_registry(_settings(model_providers_raw=_budget_provider_json(12000)))
    assert reg.providers["local"].history_budget_chars == 12000


def test_provider_history_budget_absent_defaults_none() -> None:
    """未配置 → None（全局 HISTORY_MAX_CHARS 兜底, 零回归）."""
    reg = load_registry(_settings(model_providers_raw=_TWO_PROVIDER_JSON))
    assert reg.providers["local"].history_budget_chars is None
    assert reg.providers["deepseek"].history_budget_chars is None


@pytest.mark.parametrize("bad", ["abc", -5, 0, "12k"])
def test_provider_history_budget_invalid_warns_and_defaults(
    bad, caplog: pytest.LogCaptureFixture
) -> None:
    """非法 history_budget_chars → warning 如实告警 + 回退 None（不拖垮注册表）."""
    with caplog.at_level(logging.WARNING, logger="llm_loop.llm.providers"):
        reg = load_registry(_settings(model_providers_raw=_budget_provider_json(bad)))
    assert reg.providers["local"].history_budget_chars is None
    assert not reg.degraded
    assert any("history_budget_chars" in r.message and "local" in r.message for r in caplog.records)


def test_catalog_summary_shows_provider_history_budget() -> None:
    """catalog_summary 标注 provider 级历史预算."""
    reg = load_registry(_settings(model_providers_raw=_budget_provider_json(12000)))
    assert "history_budget=12000" in reg.catalog_summary()


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


# ── P1-3（审计 #14）: 严格布尔解析 + 单条目非法独立跳过 ──


def test_strict_bool_string_false_not_enabled(caplog: pytest.LogCaptureFixture) -> None:
    """P1-3: 字符串 "false" 不再被 bool() 误判为 True（禁用配置不被静默启用）."""
    raw = json.dumps(
        {
            "p1": {
                "base_url": "http://a",
                "api_key_env": "",
                "models": {
                    "m1": {"thinking": "false", "reasoning": "false"},
                    "m2": {"thinking": "FALSE", "long_context": "off"},
                },
            }
        }
    )
    reg = load_registry(_settings(model_providers_raw=raw))
    assert reg.providers["p1"].models["m1"].thinking is False
    assert reg.providers["p1"].models["m1"].reasoning is False
    assert reg.providers["p1"].models["m2"].thinking is False
    assert reg.providers["p1"].models["m2"].long_context is False
    # 白名单内的字符串属合法值, 不产生告警
    assert not any("非合法布尔" in r.message for r in caplog.records)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (True, True),  # 真正 bool 直通（零回归）
        (False, False),
        (1, True),  # 整数 1/0 与 bool() 一致（零回归）
        (0, False),
        ("1", True),
        ("0", False),
        ("true", True),
        ("false", False),
        ("TRUE", True),  # 大小写不敏感
        ("FALSE", False),
        ("yes", True),
        ("no", False),
        ("on", True),
        ("off", False),
    ],
)
def test_strict_bool_whitelist(raw, expected) -> None:
    """P1-3: 严格布尔白名单解析（仅 bool / 整数 1/0 / 白名单字符串）."""
    reg = load_registry(
        _settings(
            model_providers_raw=json.dumps(
                {"p1": {"base_url": "http://a", "api_key_env": "", "models": {"m1": {"thinking": raw}}}}
            )
        )
    )
    assert reg.providers["p1"].models["m1"].thinking is expected


def test_invalid_bool_string_warns_and_defaults(caplog: pytest.LogCaptureFixture) -> None:
    """P1-3: 白名单外字符串 → warning 如实告警 + 回退默认 False（不静默 bool()）."""
    raw = json.dumps(
        {"p1": {"base_url": "http://a", "api_key_env": "", "models": {"m1": {"thinking": "maybe"}}}}
    )
    with caplog.at_level(logging.WARNING, logger="llm_loop.llm.providers"):
        reg = load_registry(_settings(model_providers_raw=raw))
    assert reg.providers["p1"].models["m1"].thinking is False
    assert any(
        "m1" in r.message and "thinking" in r.message and "非合法布尔" in r.message
        for r in caplog.records
    )


def test_invalid_context_entry_skipped_others_load(caplog: pytest.LogCaptureFixture) -> None:
    """P1-3（审计 #14）: 单模型 context 非法 → 跳过该条 + warning, 不拖垮整个注册表.

    此前 int("abc") ValueError 会触发 fail-soft 回落 L0, 所有 provider 全灭;
    修复后仅该条被跳过, 同 provider 其余模型与其他 provider 正常加载, 且不标记 degraded.
    """
    raw = json.dumps(
        {
            "p1": {
                "base_url": "http://a",
                "api_key_env": "",
                "models": {
                    "bad": {"context": "abc", "thinking": True},
                    "good": {"context": 12345, "thinking": True},
                },
            },
            "p2": {"base_url": "http://b", "api_key_env": "", "models": {"m2": {"context": 999}}},
        }
    )
    with caplog.at_level(logging.WARNING, logger="llm_loop.llm.providers"):
        reg = load_registry(_settings(model_providers_raw=raw))
    # 非法条目被跳过
    assert "bad" not in reg.providers["p1"].models
    # 其余条目正常加载（同 provider 的 good + 其他 provider）
    assert reg.providers["p1"].models["good"].context == 12345
    assert reg.providers["p2"].models["m2"].context == 999
    # 不再回落 L0 / 标记 degraded（单条非法不拖垮注册表）
    assert not reg.degraded
    # warning 含条目 name/model 与原因
    assert any(
        "p1" in r.message and "bad" in r.message and "context" in r.message
        for r in caplog.records
    )


def test_missing_context_uses_default() -> None:
    """P1-3: context 缺失 → 回退 131072（与 ModelSpec.context 默认一致, 全项目既有默认值）."""
    reg = load_registry(
        _settings(
            model_providers_raw=json.dumps(
                {"p1": {"base_url": "http://a", "api_key_env": "", "models": {"m1": {"thinking": True}}}}
            )
        )
    )
    assert reg.providers["p1"].models["m1"].context == 131072


def test_non_dict_provider_warns_and_skipped(caplog: pytest.LogCaptureFixture) -> None:
    """P1-3: 非 dict provider 条目 → warning + 跳过（此前静默跳过, 现如实标注）."""
    raw = json.dumps(
        {
            "p1": "not-a-dict",
            "p2": {"base_url": "http://b", "api_key_env": "", "models": {}},
        }
    )
    with caplog.at_level(logging.WARNING, logger="llm_loop.llm.providers"):
        reg = load_registry(_settings(model_providers_raw=raw))
    assert "p1" not in reg.providers
    assert "p2" in reg.providers
    assert not reg.degraded
    assert any("p1" in r.message and "非 dict" in r.message for r in caplog.records)


# ── 2026-08-15: provider 级 max_tokens 输出预算 ──

def test_provider_max_tokens_parsed_and_passed() -> None:
    """provider 条目 max_tokens → ProviderSpec + client_params 下发（pool 优先用它）."""
    reg = load_registry(
        _settings(
            model_providers_raw=json.dumps(
                {"p1": {"base_url": "http://a", "api_key_env": "", "max_tokens": 16384, "models": {"m1": {}}}}
            )
        )
    )
    assert reg.providers["p1"].max_tokens == 16384
    params = reg.client_params("p1", "m1")
    assert params.get("max_tokens") == 16384


def test_provider_max_tokens_invalid_falls_back() -> None:
    """max_tokens 非法（0/负数/非数字）→ None（全局 LLM_MAX_TOKENS 兜底）+ warning."""
    raw = json.dumps(
        {
            "p1": {"base_url": "http://a", "api_key_env": "", "max_tokens": 0, "models": {"m1": {}}},
            "p2": {"base_url": "http://b", "api_key_env": "", "max_tokens": "abc", "models": {"m2": {}}},
        }
    )
    reg = load_registry(_settings(model_providers_raw=raw))
    assert reg.providers["p1"].max_tokens is None
    assert reg.providers["p2"].max_tokens is None
    assert "max_tokens" not in reg.client_params("p1", "m1")


def test_provider_max_tokens_missing_absent() -> None:
    """未配置 max_tokens → client_params 不含该键（零回归契约）."""
    reg = load_registry(
        _settings(
            model_providers_raw=json.dumps(
                {"p1": {"base_url": "http://a", "api_key_env": "", "models": {"m1": {}}}}
            )
        )
    )
    assert "max_tokens" not in reg.client_params("p1", "m1")
