"""ASSESS-20261008-project-audit rev3 §7 WP4b 回归: BUG-13a/b/c（配置解析窄修）.

- 13a: 非法布尔回退传入 default（原硬编码 False），告警不泄露原值;
- 13b: 小数 timeout 字符串走 float parser（原经 _env_int 拒绝后回退 120）;
- 13c: 引号内的 ' #' 不是注释（原把 X="abc #def" 截成 "abc 且保留引号）。
"""

from __future__ import annotations

import pytest

from llm_loop.config import _env_bool, _env_float, _raw_env, load_env_file

# ───────────────────────── 13a: 非法布尔回退 default ─────────────────────────


@pytest.mark.parametrize("default", [True, False])
def test_env_bool_invalid_falls_back_to_default(default):
    assert _env_bool("X_FLAG", default, env={"X_FLAG": "typo"}) is default


def test_env_bool_valid_values_unchanged():
    assert _env_bool("B1", False, env={"B1": "1"}) is True
    assert _env_bool("B2", True, env={"B2": "0"}) is False
    assert _env_bool("B3", True, env={}) is True  # 空 → default


def test_env_bool_warning_does_not_leak_raw_value(caplog):
    import logging

    caplog.set_level(logging.WARNING, logger="llm_loop.config")
    _env_bool("SECRET_FLAG", True, env={"SECRET_FLAG": "hunter2-secret"})
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "hunter2-secret" not in joined
    assert "SECRET_FLAG" in joined  # 记录项名与回退结果


# ───────────────────────── 13b: 小数 timeout ─────────────────────────


def test_env_float_accepts_decimal_timeout():
    assert _env_float("LLM_TIMEOUT_S", 120.0, env={"LLM_TIMEOUT_S": "0.5"}) == 0.5
    assert _env_float("LLM_TIMEOUT_S", 120.0, env={"LLM_TIMEOUT_S": "30"}) == 30.0
    assert _env_float("LLM_TIMEOUT_S", 120.0, env={"LLM_TIMEOUT_S": "abc"}) == 120.0


def test_settings_llm_timeout_uses_float_parser(monkeypatch, tmp_path):
    """load_settings: LLM_TIMEOUT_S=0.5 → llm_timeout_s=0.5（原回退 120）."""
    from llm_loop.config import load_settings

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_TIMEOUT_S", "0.5")
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    settings = load_settings()
    assert settings.llm_timeout_s == 0.5


# ───────────────────────── 13c: 引号内 # 不破坏值 ─────────────────────────


def test_raw_env_quoted_hash_not_comment():
    assert _raw_env("QV", env={"QV": '"abc #def"'}) == "abc #def"
    assert _raw_env("QV2", env={"QV2": "'a # b'"}) == "a # b"


def test_raw_env_unquoted_comment_still_stripped():
    assert _raw_env("CV", env={"CV": "1  # 注释"}) == "1"
    assert _raw_env("CV2", env={"CV2": "1#nospace"}) == "1#nospace"  # 无空格 # 不截


def test_load_env_file_quoted_hash_preserved(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        'X_A="abc #def"\n'
        "Y_B='1 2 3'\n"
        "Z_C=plain  # trailing comment\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("X_A", raising=False)
    monkeypatch.delenv("Y_B", raising=False)
    monkeypatch.delenv("Z_C", raising=False)
    load_env_file(env_file)
    import os

    assert os.environ.get("X_A") == "abc #def"
    assert os.environ.get("Y_B") == "1 2 3"
    assert os.environ.get("Z_C") == "plain"


def test_load_env_file_env_priority_over_dotenv(tmp_path, monkeypatch):
    """既有契约: 进程环境优先于 dotenv（回归对照）."""
    env_file = tmp_path / ".env"
    env_file.write_text("PRIORITY_KEY=from_dotenv\n", encoding="utf-8")
    monkeypatch.setenv("PRIORITY_KEY", "from_env")
    load_env_file(env_file)
    import os

    assert os.environ["PRIORITY_KEY"] == "from_env"
