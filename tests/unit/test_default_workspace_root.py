"""P1-3 §7.2: 默认工作区根解析语义（factory._resolve_default_workspace_root / _activate_default_workspace）.

覆盖：env 优先级、缺省 ~/lfl-workspace、显式设置不存在 fail-fast、幂等 mkdir、
显式 workspace_root 参数最高优先。所有路径都在 tmp/fakehome 下断言，绝不触
真实 ~/lfl-workspace。
"""
from __future__ import annotations

import os
import stat as stat_mod
from pathlib import Path

import pytest

from llm_loop.factory import (
    DefaultWorkspaceRootError,
    _activate_default_workspace,
    _resolve_default_workspace_root,
)


class _EngineStub:
    def __init__(self) -> None:
        self.workspace_store = None
        self.mounted: tuple[str, str] | None = None

    def set_workspace(self, path: str, ws_id: str) -> None:
        self.mounted = (path, ws_id)


class _SettingsStub:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = str(data_dir)


def test_env_value_wins_over_default_home(tmp_path, monkeypatch):
    env_root = tmp_path / "env-root"
    env_root.mkdir()
    monkeypatch.setenv("LFL_DEFAULT_WORKSPACE_ROOT", str(env_root))
    assert _resolve_default_workspace_root() == env_root.resolve()


def test_missing_env_falls_back_to_home_lfl_workspace(tmp_path, monkeypatch):
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.delenv("LFL_DEFAULT_WORKSPACE_ROOT", raising=False)
    monkeypatch.setenv("HOME", str(fake_home))
    resolved = _resolve_default_workspace_root()
    assert resolved == (fake_home / "lfl-workspace").resolve()
    assert resolved.is_dir()  # 缺省值自动创建
    assert stat_mod.S_IMODE(resolved.stat().st_mode) & 0o777 == 0o700


def test_whitespace_env_treated_as_unset(tmp_path, monkeypatch):
    fake_home = tmp_path / "fakehome2"
    fake_home.mkdir()
    monkeypatch.setenv("LFL_DEFAULT_WORKSPACE_ROOT", "   ")
    monkeypatch.setenv("HOME", str(fake_home))
    assert _resolve_default_workspace_root() == (fake_home / "lfl-workspace").resolve()


def test_explicit_env_missing_dir_fails_fast_without_creation(tmp_path, monkeypatch):
    missing = tmp_path / "not-there"
    monkeypatch.setenv("LFL_DEFAULT_WORKSPACE_ROOT", str(missing))
    with pytest.raises(DefaultWorkspaceRootError, match="LFL_DEFAULT_WORKSPACE_ROOT"):
        _resolve_default_workspace_root()
    assert not missing.exists()  # 显式配置路径绝不静默自动创建


def test_uncreatable_default_root_fails_fast(tmp_path, monkeypatch):
    # HOME 指向普通文件 → ~/lfl-workspace 的 parents mkdir 必然失败（不可建）
    fake_home_file = tmp_path / "home-is-a-file"
    fake_home_file.write_text("not a dir", encoding="utf-8")
    monkeypatch.delenv("LFL_DEFAULT_WORKSPACE_ROOT", raising=False)
    monkeypatch.setenv("HOME", str(fake_home_file))
    with pytest.raises(DefaultWorkspaceRootError, match="不可创建"):
        _resolve_default_workspace_root()


def test_idempotent_mkdir_keeps_existing_dir_and_mode(tmp_path, monkeypatch):
    env_root = tmp_path / "existing-root"
    env_root.mkdir(mode=0o755)
    monkeypatch.setenv("LFL_DEFAULT_WORKSPACE_ROOT", str(env_root))
    first = _resolve_default_workspace_root()
    second = _resolve_default_workspace_root()  # 幂等：重复解析不报错不改权限
    assert first == second == env_root.resolve()
    assert stat_mod.S_IMODE(env_root.stat().st_mode) & 0o777 == 0o755


def test_default_root_created_with_mode_0700(tmp_path, monkeypatch):
    # 缺省路径（未设 env）：~/lfl-workspace 不存在时自动创建且 0700
    fake_home = tmp_path / "fresh-home"
    fake_home.mkdir()
    monkeypatch.delenv("LFL_DEFAULT_WORKSPACE_ROOT", raising=False)
    monkeypatch.setenv("HOME", str(fake_home))
    resolved = _resolve_default_workspace_root()
    assert resolved == (fake_home / "lfl-workspace").resolve()
    assert stat_mod.S_IMODE(resolved.stat().st_mode) & 0o777 == 0o700


def test_env_default_root_registered_when_no_explicit_param(tmp_path, monkeypatch):
    from llm_loop.workspace.store import WorkspaceStore

    env_root = tmp_path / "ws-env"
    env_root.mkdir()
    monkeypatch.setenv("LFL_DEFAULT_WORKSPACE_ROOT", str(env_root))
    monkeypatch.setenv("LFL_WORKSPACE_ALLOWED_ROOTS", str(tmp_path))
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    engine = _EngineStub()
    settings = _SettingsStub(data_dir)
    _activate_default_workspace(engine, settings, workspace_root=None)
    store = WorkspaceStore(data_dir)
    current = store.get_current()
    assert current is not None and Path(current.path) == env_root.resolve()
    assert engine.mounted is not None and Path(engine.mounted[0]) == env_root.resolve()


def test_explicit_workspace_root_param_highest_priority(tmp_path, monkeypatch):
    from llm_loop.workspace.store import WorkspaceStore

    env_root = tmp_path / "ws-env-shadowed"
    env_root.mkdir()
    explicit_root = tmp_path / "ws-explicit"
    explicit_root.mkdir()
    monkeypatch.setenv("LFL_DEFAULT_WORKSPACE_ROOT", str(env_root))
    monkeypatch.setenv("LFL_WORKSPACE_ALLOWED_ROOTS", str(tmp_path))
    data_dir = tmp_path / "data2"
    data_dir.mkdir(exist_ok=True)
    engine = _EngineStub()
    settings = _SettingsStub(data_dir)
    _activate_default_workspace(engine, settings, workspace_root=str(explicit_root))
    store = WorkspaceStore(data_dir)
    current = store.get_current()
    assert current is not None and Path(current.path) == explicit_root.resolve()
    assert engine.mounted is not None and Path(engine.mounted[0]) == explicit_root.resolve()
    # env 默认根未被注册为 current——显式参数最高优先
    assert env_root.resolve() not in {Path(w.path).resolve() for w in store.list()}


def test_chdir_no_longer_affects_default_root(tmp_path, monkeypatch):
    """P1-3 语义固化：默认根不再跟随 cwd（迁出代码根的安全目标本身）."""
    env_root = tmp_path / "ws-env-cwd-immune"
    env_root.mkdir()
    monkeypatch.setenv("LFL_DEFAULT_WORKSPACE_ROOT", str(env_root))
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    assert _resolve_default_workspace_root() == env_root.resolve()
    assert os.getcwd() == str(other_cwd)  # cwd 未被改动；只是不再参与解析
