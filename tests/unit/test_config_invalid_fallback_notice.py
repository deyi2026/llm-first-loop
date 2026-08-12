"""配置非法回退如实标注测试（spec 5.1 / design §2.4.1 / tasks 1.4）.

断言:
1. 非法 LLM_MAX_ITERATIONS=abc → invalid_fallbacks 含 config_name/fallback_value/invalid_value_type
2. 非法 LLM_THINKING_MODE=weird → thinking_mode is True + 标注（回退语义不变）
3. 非法 TOOL_TRIM_ENABLED=abc → tool_trim_enabled is False + 标注（_env_bool 区分合法 false 与非法）
4. 非法 EVOLVE_LOCAL_EXEC/EXEC_MODE/LLM_REASONING_EFFORT → 标注 + 返回值与现状一致
5. to_status_dict 的 config_invalid_fallbacks 不含密钥/raw 原文
6. 未设置不产生标注（invalid_fallbacks 为空）
7. caplog 捕获 warning 含配置项名 + 回退结果，不含 raw 原文
"""

from __future__ import annotations

import logging


def _load(monkeypatch, **envs) -> object:
    from llm_loop.config import load_settings

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    for k, v in envs.items():
        monkeypatch.setenv(k, v)
    return load_settings()


def _names(settings) -> list[str]:
    return [n.config_name for n in settings.invalid_fallbacks]


class TestInvalidFallbackNotice:
    def test_int_invalid_noticed(self, monkeypatch):
        s = _load(monkeypatch, LLM_MAX_ITERATIONS="abc")
        assert s.max_iterations == 20  # 回退语义不变
        notes = list(s.invalid_fallbacks)
        assert any(
            n.config_name == "LLM_MAX_ITERATIONS"
            and n.fallback_value == 20
            and n.invalid_value_type == "非整数字符串"
            for n in notes
        )

    def test_thinking_mode_invalid_falls_back_true(self, monkeypatch):
        s = _load(monkeypatch, LLM_THINKING_MODE="weird")
        assert s.thinking_mode is True  # 非法回退 enabled，与现状一致
        assert "LLM_THINKING_MODE" in _names(s)

    def test_bool_distinguishes_legal_false_from_invalid(self, monkeypatch):
        # 合法 false 不标注
        s_off = _load(monkeypatch, TOOL_TRIM_ENABLED="off")
        assert s_off.tool_trim_enabled is False
        assert "TOOL_TRIM_ENABLED" not in _names(s_off)
        # 非法值标注 + 返回 False（与现状一致）
        s_bad = _load(monkeypatch, TOOL_TRIM_ENABLED="abc")
        assert s_bad.tool_trim_enabled is False
        assert any(
            n.config_name == "TOOL_TRIM_ENABLED" and n.invalid_value_type == "非布尔字符串"
            for n in s_bad.invalid_fallbacks
        )

    def test_evolve_level_effort_exec_mode_invalid_noticed(self, monkeypatch):
        s = _load(
            monkeypatch,
            EVOLVE_LOCAL_EXEC="xyz",
            EXEC_MODE="weird",
            LLM_REASONING_EFFORT="weird",
        )
        assert s.evolve_local_exec == 0
        assert s.exec_mode == "blocked"
        assert s.reasoning_effort == "high"
        names = _names(s)
        assert "EVOLVE_LOCAL_EXEC" in names
        assert "EXEC_MODE" in names
        assert "LLM_REASONING_EFFORT" in names

    def test_to_status_dict_exposes_without_secrets(self, monkeypatch):
        s = _load(monkeypatch, LLM_MAX_ITERATIONS="abc")
        st = s.to_status_dict()
        assert "config_invalid_fallbacks" in st
        entries = st["config_invalid_fallbacks"]
        assert any(e["config_name"] == "LLM_MAX_ITERATIONS" for e in entries)
        for e in entries:
            assert "config_name" in e and "fallback_value" in e and "invalid_value_type" in e
        # 密钥与 raw 原文不出域
        assert "llm_api_key" not in st
        assert "embedding_api_key" not in st

    def test_unset_produces_no_note(self, monkeypatch):
        s = _load(monkeypatch)
        assert s.invalid_fallbacks == ()

    def test_warning_logged_without_raw(self, monkeypatch, caplog):
        with caplog.at_level(logging.WARNING, logger="llm_loop.config"):
            _load(monkeypatch, LLM_MAX_ITERATIONS="sk-secret-raw-value")
        assert any("LLM_MAX_ITERATIONS" in r.message for r in caplog.records)
        assert all("sk-secret-raw-value" not in r.message for r in caplog.records)
