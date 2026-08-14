"""CI 环境健壮性回归测试（2026-08-14）.

根因（nightly 首次启用抓到的真实缺陷）: GitHub Actions 未配置的 secrets 注入 env 时
是**空字符串**而非未设置——`os.environ.get("LLM_BASE_URL", 默认)` 对空串返回 `''`，
导致 base_url 为空 → httpx UnsupportedProtocol（"Request URL is missing an 'http://'
or 'https://' protocol"）→ 全部 LLM 请求失败。修复: `or` 回退（空串→默认）。

覆盖: 空串环境变量回退默认（real_llm settings 构造逻辑，无需真实 key）。
"""

from __future__ import annotations

import importlib


def _real_llm_settings_module(name: str):
    """按名加载 integration 模块的 _real_llm_settings（构造逻辑单测，无 key 时验证回退）."""
    return importlib.import_module(name)


def test_empty_string_env_falls_back(monkeypatch, tmp_path):
    """LLM_BASE_URL/LLM_MODEL 空串（CI secrets 未配置形态）→ 回退默认（根因回归）."""


    # 复现 CI 形态：变量存在但为空串
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    from tests.integration.test_real_llm_exec_smoke import _real_llm_settings

    s = _real_llm_settings(tmp_path)  # type: ignore[arg-type]
    assert s.llm_base_url == "https://api.deepseek.com/v1"  # 空串回退
    assert s.llm_model == "deepseek-v4-flash"


def test_empty_string_env_smoke_equivalent(monkeypatch, tmp_path):
    """空串与未设置（真实默认路径）构造结果一致（`or` 语义等价性）."""

    from tests.integration.test_real_llm_smoke import _real_llm_settings

    # 空串形态
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k1")
    s1 = _real_llm_settings(tmp_path)  # type: ignore[arg-type]
    # 未设置形态
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    s2 = _real_llm_settings(tmp_path)  # type: ignore[arg-type]
    assert s1.llm_base_url == s2.llm_base_url
    assert s1.llm_model == s2.llm_model
