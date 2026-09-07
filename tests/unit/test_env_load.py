"""M63 配置加载统一（load_env_file）测试.

覆盖:
- 存在 .env 时加载未设置键（含注释/空行跳过、引号剥离）
- 环境变量优先（已设置的键不覆盖）
- 文件不存在 / 读取失败 fail-open
"""

from __future__ import annotations

import os
from pathlib import Path

import llm_loop.config as config_mod
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


def test_load_env_file_default_path_is_project_env(monkeypatch):
    """默认路径指向项目根 .env，但测试不读取真实运行态配置。"""
    expected = Path(config_mod.__file__).resolve().parent.parent.parent / ".env"
    seen: list[Path] = []
    original_exists = Path.exists
    original_read_text = Path.read_text

    def _exists(path: Path) -> bool:
        if path == expected:
            return True
        return original_exists(path)

    def _read_text(path: Path, *args, **kwargs) -> str:
        if path == expected:
            seen.append(path)
            # 使用已存在键验证 env precedence，避免向进程环境新增测试哨兵。
            return "LFL_DEFAULT_ENV_PATH_PROBE=from-file\n"
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setenv("LFL_DEFAULT_ENV_PATH_PROBE", "preexisting")
    monkeypatch.setattr(Path, "exists", _exists)
    monkeypatch.setattr(Path, "read_text", _read_text)

    load_env_file()

    assert seen == [expected]
    assert os.environ["LFL_DEFAULT_ENV_PATH_PROBE"] == "preexisting"
