"""单元测试: 配置装配（T18 / 环境变量读取与校验）."""

from __future__ import annotations

import pytest


def test_load_settings_requires_env(monkeypatch):
    """缺少必填环境变量 → ValueError + 指引."""
    from llm_loop.config import load_settings

    for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        load_settings()


def test_load_settings_full(monkeypatch):
    """完整配置装配 + 默认值."""
    from llm_loop.config import load_settings

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_MAX_ITERATIONS", "30")
    monkeypatch.delenv("DATA_DIR", raising=False)  # 用默认 ./data
    s = load_settings()
    assert s.llm_api_key == "k"
    assert s.max_iterations == 30
    assert s.llm_timeout_s == 120.0
    assert s.data_dir == "./data"
    assert s.self_inspection_enabled is True


def test_load_settings_self_inspection_off(monkeypatch):
    """SELF_INSPECTION_ENABLED=0 → 关闭自省."""
    from llm_loop.config import load_settings

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("SELF_INSPECTION_ENABLED", "0")
    s = load_settings()
    assert s.self_inspection_enabled is False


def test_settings_dirs_and_status():
    """派生目录 + 状态摘要（不含密钥）."""
    from llm_loop.config import Settings

    s = Settings(llm_api_key="k", llm_base_url="u", llm_model="m", data_dir="/tmp/llm-test")
    assert str(s.sessions_dir) == "/tmp/llm-test/sessions"
    st = s.to_status_dict()
    assert "llm_api_key" not in st  # 密钥不出现在状态摘要（DFX-SEC-02）
    assert st["llm_model"] == "m"


def test_evolve_local_exec_levels(monkeypatch):
    """EVOLVE_LOCAL_EXEC 三级解析（EXEC-01）: 0/1/2."""
    from llm_loop.config import load_settings

    def _load(level: str) -> int:
        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
        monkeypatch.setenv("LLM_MODEL", "m")
        monkeypatch.setenv("EVOLVE_LOCAL_EXEC", level)
        return load_settings().evolve_local_exec

    assert _load("0") == 0
    assert _load("1") == 1
    assert _load("2") == 2
    assert _load("") == 0  # 未设置回退默认仅建议


def test_evolve_local_exec_legacy_bool(monkeypatch):
    """旧布尔值兼容: true→1 / false→0（T55 向后兼容）."""
    from llm_loop.config import load_settings

    def _load(level: str) -> int:
        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
        monkeypatch.setenv("LLM_MODEL", "m")
        monkeypatch.setenv("EVOLVE_LOCAL_EXEC", level)
        return load_settings().evolve_local_exec

    assert _load("true") == 1  # 旧 True 平滑升级为级别 1
    assert _load("false") == 0
    assert _load("1") == 1
    assert _load("0") == 0


def test_evolve_local_exec_invalid_fallback(monkeypatch):
    """非法值回退 0（仅建议，fail-open 不越权）."""
    from llm_loop.config import load_settings

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("EVOLVE_LOCAL_EXEC", "abc")
    assert load_settings().evolve_local_exec == 0


def test_to_status_dict_evolve_level():
    """to_status_dict 输出演进执行级别（AI 可查询，EXEC-01 验收）."""
    from llm_loop.config import Settings

    s = Settings(llm_api_key="k", llm_base_url="u", llm_model="m", evolve_local_exec=1)
    assert s.to_status_dict()["evolve_local_exec"] == 1


def test_m12_deep_config_defaults(monkeypatch):
    """T66: M12 深化 9 变量默认值装配（0 回归基线）."""
    from llm_loop.config import load_settings

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.delenv("EVOLVE_LOCAL_EXEC", raising=False)
    monkeypatch.delenv("EVOLVE_EXEC_WHITELIST", raising=False)
    monkeypatch.delenv("SELF_EVAL_ENABLED", raising=False)
    monkeypatch.delenv("SELF_EVAL_REMIND_ENABLED", raising=False)
    monkeypatch.delenv("SELF_EVAL_INTERVAL_ROUNDS", raising=False)
    monkeypatch.delenv("SELF_EVAL_MIN_SAMPLES", raising=False)
    monkeypatch.delenv("SELF_EVAL_SPAN", raising=False)
    s = load_settings()
    assert s.evolve_local_exec == 0
    assert s.evolve_exec_whitelist == ""
    assert s.self_eval_enabled is True
    assert s.self_eval_remind_enabled is True
    assert s.self_eval_interval_rounds == 50
    assert s.self_eval_min_samples == 5
    assert s.self_eval_span == 50


def test_m12_deep_config_env_override(monkeypatch):
    """T66: M12 深化变量 env 覆盖生效."""
    from llm_loop.config import load_settings

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("EVOLVE_EXEC_WHITELIST", "recover_state,clear_cache")
    monkeypatch.setenv("SELF_EVAL_ENABLED", "0")
    monkeypatch.setenv("SELF_EVAL_INTERVAL_ROUNDS", "20")
    monkeypatch.setenv("SELF_EVAL_MIN_SAMPLES", "10")
    monkeypatch.setenv("SELF_EVAL_SPAN", "100")
    s = load_settings()
    assert s.evolve_exec_whitelist == "recover_state,clear_cache"
    assert s.self_eval_enabled is False
    assert s.self_eval_interval_rounds == 20
    assert s.self_eval_min_samples == 10
    assert s.self_eval_span == 100


def test_m12_deep_config_invalid_fallback(monkeypatch):
    """T66: M12 深化非法值回退默认（fail-open 不越权）."""
    from llm_loop.config import load_settings

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("SELF_EVAL_INTERVAL_ROUNDS", "abc")
    monkeypatch.setenv("SELF_EVAL_MIN_SAMPLES", "xyz")
    s = load_settings()
    assert s.self_eval_interval_rounds == 50  # 非法 → 回退默认
    assert s.self_eval_min_samples == 5  # 非法 → 回退默认


def test_to_status_dict_m12_deep_fields():
    """T66: to_status_dict 含 M12 深化配置字段且无密钥（architecture_config 可查）."""
    from llm_loop.config import Settings

    s = Settings(
        llm_api_key="k",
        llm_base_url="u",
        llm_model="m",
        evolve_local_exec=2,
        self_eval_enabled=True,
    )
    st = s.to_status_dict()
    assert st["evolve_local_exec"] == 2
    assert st["evolve_exec_whitelist"] == ""
    assert st["self_eval_enabled"] is True
    assert st["self_eval_remind_enabled"] is True
    assert st["self_eval_interval_rounds"] == 50
    assert "llm_api_key" not in st  # 密钥不出现在状态摘要（DFX-SEC-02）


def test_load_settings_model_default_chain(monkeypatch):
    """M20 CFG-01/02: LLM_MODEL 缺省链 显式 > OPENSYGAI_DEEPSEEK_DEFAULT_MODEL > 内置 v4-flash."""
    from llm_loop.config import load_settings

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    # ① 显式优先
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("OPENSYGAI_DEEPSEEK_DEFAULT_MODEL", "deepseek-v4-flash")
    assert load_settings().llm_model == "deepseek-v4-pro"
    # ② OPENSYGAI 次之
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("OPENSYGAI_DEEPSEEK_DEFAULT_MODEL", "deepseek-v4-flash")
    assert load_settings().llm_model == "deepseek-v4-flash"
    # ③ 内置默认（不降级，无旧 deepseek-chat）
    monkeypatch.delenv("OPENSYGAI_DEEPSEEK_DEFAULT_MODEL", raising=False)
    assert load_settings().llm_model == "deepseek-v4-flash"
    assert load_settings().llm_model != "deepseek-chat"


def test_load_settings_requires_only_key_base(monkeypatch):
    """M20 CFG-01: LLM_MODEL 不再必填（仅 key/base_url 必填）."""
    from llm_loop.config import load_settings

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENSYGAI_DEEPSEEK_DEFAULT_MODEL", raising=False)
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        load_settings()
    # 有 key/base_url 无 model → 用默认 v4-flash
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENSYGAI_DEEPSEEK_DEFAULT_MODEL", raising=False)
    assert load_settings().llm_model == "deepseek-v4-flash"


def test_load_settings_thinking_env(monkeypatch):
    """M20 THK-01: LLM_THINKING_MODE/LLM_REASONING_EFFORT env 解析（非法回退默认）."""
    from llm_loop.config import load_settings

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.delenv("LLM_THINKING_MODE", raising=False)
    monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
    # 默认开启 + high
    s = load_settings()
    assert s.thinking_mode is True
    assert s.reasoning_effort == "high"
    # disabled → False
    monkeypatch.setenv("LLM_THINKING_MODE", "disabled")
    assert load_settings().thinking_mode is False
    # low/max 装配
    monkeypatch.setenv("LLM_THINKING_MODE", "enabled")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "max")
    s = load_settings()
    assert s.reasoning_effort == "max"
    # 非法回退默认
    monkeypatch.setenv("LLM_REASONING_EFFORT", "weird")
    assert load_settings().reasoning_effort == "high"
    monkeypatch.setenv("LLM_THINKING_MODE", "weird")
    assert load_settings().thinking_mode is True


def test_to_status_dict_thinking_fields():
    """M20 DFX-MNT-07: to_status_dict 含思考参数且无密钥."""
    from llm_loop.config import Settings

    s = Settings(llm_api_key="k", llm_base_url="u", llm_model="m", reasoning_effort="max")
    st = s.to_status_dict()
    assert st["thinking_mode"] is True
    assert st["reasoning_effort"] == "max"
    assert "llm_api_key" not in st
