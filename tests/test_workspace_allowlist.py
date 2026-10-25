"""工作区注册白名单（P0-3）: register / register_and_switch 受允许根约束.

允许根 = LFL_WORKSPACE_ALLOWED_ROOTS（os.pathsep 分隔）∪
{代码仓根, cwd（非根/非家目录祖先）, <data_dir>/workspace, 家目录子树}；
显式拒绝 /、家目录及其祖先、任何比允许根更宽的祖先路径。switch
（已注册工作区）不复检白名单（注册即信任决策），但保留路径可用性检查。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from llm_loop.workspace.store import (
    WorkspaceNotAllowedError,
    WorkspacePathUnavailableError,
    WorkspaceStore,
    workspace_key,
)


def _store(tmp_path):
    return WorkspaceStore(tmp_path / "data")


_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _pin_cwd_to_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """固定 cwd 到仓库根，避免 conftest 的 chdir(tmp_path) 夹具改写白名单语义.

    默认允许根包含 cwd；若 cwd 被夹具切到 tmp_path，"白名单外路径"会被
    cwd 意外放行，测出来的是夹具副作用而不是实现行为。
    """
    monkeypatch.chdir(_REPO_ROOT)


def _craft_registry(data_dir: Path, ws_path: Path) -> None:
    """直接写注册表（模拟白名单启用前的历史注册条目）."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "workspaces.json").write_text(
        json.dumps(
            {
                "version": 2,
                "current": "",
                "workspaces": [
                    {"id": workspace_key(ws_path), "path": str(ws_path), "created_at": ""}
                ],
            }
        ),
        encoding="utf-8",
    )


# ── 显式拒绝 ──
def test_register_filesystem_root_rejected(tmp_path):
    with pytest.raises(WorkspaceNotAllowedError) as ei:
        _store(tmp_path).register("/")
    assert "/" in str(ei.value)
    assert "LFL_WORKSPACE_ALLOWED_ROOTS" in str(ei.value)  # 报错写明扩展方式


def test_register_home_and_ancestors_rejected(tmp_path):
    store = _store(tmp_path)
    home = Path.home()
    with pytest.raises(WorkspaceNotAllowedError):
        store.register(home)  # 家目录本身
    with pytest.raises(WorkspaceNotAllowedError):
        store.register(home.parent)  # 家目录祖先（macOS /Users）
    with pytest.raises(WorkspaceNotAllowedError):
        store.register(home.parent.parent)  # 更上层（通常为 /）


def test_register_outside_allowed_roots_rejected(tmp_path):
    store = _store(tmp_path)
    outside = tmp_path / "outside"  # pytest tmp 不在默认允许根之下
    outside.mkdir()
    with pytest.raises(WorkspaceNotAllowedError) as ei:
        store.register(outside)
    assert "LFL_WORKSPACE_ALLOWED_ROOTS" in str(ei.value)
    assert store.list() == []  # 未注册


def test_register_wider_than_allowed_root_rejected(tmp_path, monkeypatch):
    """允许根的父目录（比允许根更宽）必须拒绝，即使环境变量已扩展到子目录."""
    monkeypatch.setenv("LFL_WORKSPACE_ALLOWED_ROOTS", str(tmp_path))
    store = _store(tmp_path)
    with pytest.raises(WorkspaceNotAllowedError) as ei:
        store.register(tmp_path.parent)
    assert "更宽" in str(ei.value)


def test_not_allowed_error_is_valueerror(tmp_path):
    """WorkspaceNotAllowedError(ValueError)：供 routes 层现有 except ValueError 兼容."""
    assert issubclass(WorkspaceNotAllowedError, ValueError)
    with pytest.raises(ValueError):
        _store(tmp_path).register("/")


# ── 允许根内成功 ──
def test_register_env_extension_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("LFL_WORKSPACE_ALLOWED_ROOTS", str(tmp_path))
    store = _store(tmp_path)
    target = tmp_path / "proj"
    target.mkdir()
    ws = store.register(target)
    assert ws.path == str(target.resolve())


def test_register_env_extension_multiple_roots(tmp_path, monkeypatch):
    other_root = tmp_path / "other-root"
    other_root.mkdir()
    monkeypatch.setenv(
        "LFL_WORKSPACE_ALLOWED_ROOTS",
        os.pathsep.join([str(tmp_path / "ws-a"), str(other_root)]),
    )
    (tmp_path / "ws-a").mkdir()
    store = _store(tmp_path)
    assert store.register(tmp_path / "ws-a").path == str((tmp_path / "ws-a").resolve())
    assert store.register(other_root).path == str(other_root.resolve())


def test_register_default_data_workspace_allowed(tmp_path):
    """默认允许根 <data_dir>/workspace：其下与其本身均可注册."""
    store = _store(tmp_path)  # data_dir = tmp_path/data
    target = tmp_path / "data" / "workspace" / "proj"
    target.mkdir(parents=True)
    assert store.register(target).path == str(target.resolve())
    root_itself = tmp_path / "data" / "workspace"
    root_itself.mkdir(parents=True, exist_ok=True)
    assert store.register(root_itself).path == str(root_itself.resolve())


def test_register_repo_root_subtree_allowed(tmp_path):
    """默认允许根"代码仓根"：其子目录（真实存在的 src/）可注册."""
    store = _store(tmp_path)
    repo_root = Path(__file__).resolve().parents[1]
    src = repo_root / "src"
    assert src.is_dir()
    assert store.register(src).path == str(src.resolve())


# ── register_and_switch 同受约束 ──
def test_register_and_switch_enforces_allowlist(tmp_path, monkeypatch):
    store = _store(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(WorkspaceNotAllowedError):
        store.register_and_switch(outside)
    assert store.get_current() is None  # 未注册也未切换
    monkeypatch.setenv("LFL_WORKSPACE_ALLOWED_ROOTS", str(tmp_path))
    ws = store.register_and_switch(outside)
    assert store.get_current().id == ws.id
    assert store.get_current().path == str(outside.resolve())


# ── switch 不复检白名单（注册即信任决策），但保留可用性检查 ──
def test_switch_skips_allowlist_for_registered(tmp_path):
    """历史注册条目（白名单外路径）仍可切换——switch 只做状态切换."""
    legacy = tmp_path / "legacy-ws"
    legacy.mkdir()
    data = tmp_path / "data"
    _craft_registry(data, legacy.resolve())
    store = WorkspaceStore(data)
    ws = store.switch(workspace_key(legacy))
    assert ws.path == str(legacy.resolve())
    assert store.get_current().id == ws.id


def test_switch_unavailable_dir_still_rejected(tmp_path):
    """已注册但目录消失 → WorkspacePathUnavailableError（既有检查保留）."""
    gone = tmp_path / "gone-ws"  # 不创建目录
    data = tmp_path / "data"
    _craft_registry(data, gone.resolve())
    store = WorkspaceStore(data)
    with pytest.raises(WorkspacePathUnavailableError):
        store.switch(workspace_key(gone))


# ── P0-3 验收：home 子树可注册；退化 cwd 不纳入白名单 ──
def test_register_home_subtree_allowed(tmp_path, monkeypatch):
    """验收"home 下新目录可注册"：家目录子树放行，家目录本身仍拒绝."""
    fake_home = tmp_path / "fakehome"
    (fake_home / "proj").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    store = _store(tmp_path)
    assert store.register(fake_home / "proj").path == str((fake_home / "proj").resolve())
    with pytest.raises(WorkspaceNotAllowedError):
        store.register(fake_home)


def test_degenerate_cwd_not_added_as_allowed_root(tmp_path, monkeypatch):
    """R2-5：cwd=文件系统根/家目录祖先时不得纳入允许根（白名单不得退化为全盘）."""
    from llm_loop.workspace.store import _workspace_allowed_roots

    fake_home = tmp_path / "fakehome2"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.chdir("/")
    roots = _workspace_allowed_roots(tmp_path / "data")
    assert Path("/") not in roots

    proj = tmp_path / "proj-cwd"
    proj.mkdir()
    monkeypatch.chdir(proj)
    roots = _workspace_allowed_roots(tmp_path / "data")
    assert proj.resolve() in roots  # 安全 cwd 仍可注册（安装式部署）


# ── P1-3（2026-10-25）默认工作区根 ~/lfl-workspace：注册+switch 断言 ──
def test_default_workspace_root_under_fakehome_register_and_switch(tmp_path, monkeypatch):
    """P1-3 设计 §7.1：HOME→tmp 假家目录时 ~/lfl-workspace 必须可注册可切换.

    默认工作区根迁出代码根后，factory 的 _resolve_default_workspace_root 解析
    出 ~/lfl-workspace 并注册为默认工作区——本用例固化"家目录子树里的
    lfl-workspace 注册+switch 全链路可用"（迁移前后语义不断链）。
    """
    fake_home = tmp_path / "fakehome-lfl"
    ws_root = fake_home / "lfl-workspace"
    ws_root.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    store = _store(tmp_path)

    ws = store.register(str(ws_root))
    assert ws.path == str(ws_root.resolve())
    assert ws.id == workspace_key(ws_root)

    store.switch(ws.id)
    current = store.get_current()
    assert current is not None
    assert current.id == ws.id and current.path == str(ws_root.resolve())
    # 幂等：重复注册同一路径不产生第二个条目
    again = store.register(str(ws_root))
    assert again.id == ws.id
    assert [w.id for w in store.list()] == [ws.id]
