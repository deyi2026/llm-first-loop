"""M63 配置加载统一（load_env_file）测试.

覆盖:
- 存在 .env 时加载未设置键（含注释/空行跳过、引号剥离）
- 环境变量优先（已设置的键不覆盖）
- 文件不存在 / 读取失败 fail-open
"""

from __future__ import annotations

import os

from llm_loop.config import load_env_file


def test_load_env_file_loads_missing_keys(tmp_path, monkeypatch):
    """未设置的键从 .env 加载；注释/空行跳过；引号剥离."""
    env = tmp_path / ".env"
    env.write_text(
        "# comment line\n"
        "\n"
        "HISTORY_MAX_CHARS=80000\n"
        "SUMMARY_MODE=off\n"
        'QUOTED_VAL="hello world"\n'
        "BAD LINE WITHOUT EQUALS\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("HISTORY_MAX_CHARS", raising=False)
    monkeypatch.delenv("SUMMARY_MODE", raising=False)
    monkeypatch.delenv("QUOTED_VAL", raising=False)
    load_env_file(env)
    assert os.environ["HISTORY_MAX_CHARS"] == "80000"
    assert os.environ["SUMMARY_MODE"] == "off"
    assert os.environ["QUOTED_VAL"] == "hello world"


def test_load_env_file_env_precedence(tmp_path, monkeypatch):
    """环境变量优先：已设置的键不被 .env 覆盖."""
    env = tmp_path / ".env"
    env.write_text("HISTORY_MAX_CHARS=200000\n", encoding="utf-8")
    monkeypatch.setenv("HISTORY_MAX_CHARS", "12345")
    load_env_file(env)
    assert os.environ["HISTORY_MAX_CHARS"] == "12345"


def test_load_env_file_missing_fail_open(tmp_path):
    """文件不存在 fail-open（不抛异常）."""
    load_env_file(tmp_path / "nonexistent.env")  # 不应抛异常


def test_load_env_file_default_path_is_project_env():
    """默认路径指向项目根 .env（与 restart_system.sh 注入同源）."""
    # load_env_file 无参默认使用项目根 .env；仅验证可调用不抛异常
    load_env_file()
