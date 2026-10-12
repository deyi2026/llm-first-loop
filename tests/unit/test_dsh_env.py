"""dsh_task DSH_HOME 可写性回退测试（2026-08-16 EPERM 复盘）."""

from pathlib import Path
from unittest import mock

from llm_loop.tools.builtin.dsh_task import _dsh_env


def test_writable_home_kept(tmp_path, monkeypatch):
    """当前 DSH_HOME 可写 → 沿用不回退."""
    home = tmp_path / "writable_home"
    home.mkdir()
    monkeypatch.setenv("DSH_HOME", str(home))
    env = _dsh_env(str(tmp_path))
    assert env["DSH_HOME"] == str(home)


def test_unwritable_home_falls_back(tmp_path, monkeypatch):
    """当前 DSH_HOME 不可写 → 回退 <cwd>/data/dsh-home（存在时）."""
    cwd = tmp_path / "proj"
    fallback = cwd / "data" / "dsh-home"
    fallback.mkdir(parents=True)
    monkeypatch.setenv("DSH_HOME", "/nonexistent-ro-root/dsh")
    with mock.patch.object(Path, "mkdir", side_effect=OSError("EPERM")):
        env = _dsh_env(str(cwd))
    assert env["DSH_HOME"] == str(fallback)


def test_unwritable_no_fallback_keeps_original(tmp_path, monkeypatch):
    """不可写且项目内无回退目录 → 如实保留原值（让 DSH 报错暴露，不伪造环境）."""
    monkeypatch.setenv("DSH_HOME", "/nonexistent-ro-root/dsh")
    with mock.patch.object(Path, "mkdir", side_effect=OSError("EPERM")):
        env = _dsh_env(str(tmp_path))
    assert env["DSH_HOME"] == "/nonexistent-ro-root/dsh"


def test_unset_home_uses_fallback(tmp_path, monkeypatch):
    """DSH_HOME 未设 → 用项目内回退（存在时）."""
    cwd = tmp_path / "proj"
    fallback = cwd / "data" / "dsh-home"
    fallback.mkdir(parents=True)
    monkeypatch.delenv("DSH_HOME", raising=False)
    env = _dsh_env(str(cwd))
    assert env["DSH_HOME"] == str(fallback)
