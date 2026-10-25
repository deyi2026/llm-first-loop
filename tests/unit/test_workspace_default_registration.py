"""EVO-20260923 根治 + P1-3（2026-10-25）语义迁移：默认根的临时区防注册防线.

历史事故：pytest tmp_path / mkdtemp（/tmp、/var/folders）下启动的引擎把
一次性目录写进 data/workspaces.json，累计 95 条 retired 垃圾。防线为双条件：
_cwd_in_system_temp（默认根在系统临时区）且 _registry_is_production_default
（data_dir 未被 DATA_DIR 显式改写）→ 跳过自动注册。隔离运行
（评测/测试显式 DATA_DIR）不受影响。

P1-3 后默认根不再来自 cwd 而是 LFL_DEFAULT_WORKSPACE_ROOT（缺省
~/lfl-workspace）——本文件用例改为显式 setenv 控制默认根（设计 §7.3），
不再依赖 chdir 传导；防线判定对象随之从「临时 cwd」变为「临时默认根」，
逻辑（factory._cwd_in_system_temp(root)）与逃逸阀不变。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop import factory as factory_mod


def _fake_engine(calls: list) -> SimpleNamespace:
    return SimpleNamespace(
        set_workspace=lambda path, ws_id=None, **_kw: calls.append((str(path), ws_id)),
        workspace_root="",
        session=SimpleNamespace(),
    )


def _prod_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把生产默认目录指向 tmp 下的隔离位置（不触碰真实 data/）."""
    from llm_loop import config as config_mod

    prod_data = tmp_path / "prod-data"
    prod_data.mkdir()
    monkeypatch.setattr(config_mod, "_DEFAULT_DATA_DIR", str(prod_data))
    return prod_data


def _set_default_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> Path:
    """显式钉住默认工作区根（P1-3 语义：env 解析，与 cwd 无关）."""
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LFL_DEFAULT_WORKSPACE_ROOT", str(root))
    return root


def test_temp_default_root_skips_production_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """临时默认根 + 生产默认 data 目录 → 不注册、不设默认 current."""
    prod_data = _prod_registry(tmp_path, monkeypatch)
    _set_default_root(monkeypatch, tmp_path / "tmp-default-root")  # 位于系统临时区
    unrelated_cwd = tmp_path / "unrelated-cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)  # cwd 不再参与解析（P1-3）
    settings = SimpleNamespace(data_dir=str(prod_data))
    calls: list = []

    factory_mod._activate_default_workspace(_fake_engine(calls), settings)

    from llm_loop.workspace.store import WorkspaceStore

    store = WorkspaceStore(str(prod_data))
    assert store.list() == [], "临时默认根不得写入生产注册表"
    assert store.get_current() is None
    assert calls == [], "注册表无 current 时不应调用 set_workspace"


def test_temp_default_root_escape_hatch_registers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LFL_ALLOW_TEMP_WORKSPACE=1 显式要求注册 → 照常注册（逃逸阀）."""
    prod_data = _prod_registry(tmp_path, monkeypatch)
    root = _set_default_root(monkeypatch, tmp_path / "tmp-default-root")
    monkeypatch.setenv("LFL_ALLOW_TEMP_WORKSPACE", "1")
    settings = SimpleNamespace(data_dir=str(prod_data))
    calls: list = []

    factory_mod._activate_default_workspace(_fake_engine(calls), settings)

    from llm_loop.workspace.store import WorkspaceStore

    store = WorkspaceStore(str(prod_data))
    assert [w.path for w in store.list()] == [str(root)]
    assert store.get_current() is not None
    assert calls, "注册后必须激活工作区"


def test_temp_default_root_with_isolated_registry_registers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """临时默认根 + 显式隔离 data 目录（评测语义）→ 照常注册，评测行为不变."""
    prod_data = _prod_registry(tmp_path, monkeypatch)
    iso_data = tmp_path / "iso-data"
    root = _set_default_root(monkeypatch, tmp_path / "tmp-default-root")
    settings = SimpleNamespace(data_dir=str(iso_data))  # != 生产默认
    calls: list = []

    factory_mod._activate_default_workspace(_fake_engine(calls), settings)

    from llm_loop.workspace.store import WorkspaceStore

    store = WorkspaceStore(str(iso_data))
    assert [w.path for w in store.list()] == [str(root)]
    assert calls, "隔离注册表注册后必须激活工作区"
    assert prod_data.exists()


def test_temp_default_root_activates_existing_current_without_registering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """生产注册表已有 current 时：临时默认根启动不注册，但 current 仍被激活."""
    prod_data = _prod_registry(tmp_path, monkeypatch)
    _set_default_root(monkeypatch, tmp_path / "tmp-default-root")
    real_ws_dir = tmp_path / "real-project"
    real_ws_dir.mkdir()
    from llm_loop.workspace.store import WorkspaceStore

    WorkspaceStore(str(prod_data)).register_and_switch(str(real_ws_dir))
    settings = SimpleNamespace(data_dir=str(prod_data))
    calls: list = []

    factory_mod._activate_default_workspace(_fake_engine(calls), settings)

    store = WorkspaceStore(str(prod_data))
    assert [w.path for w in store.list()] == [str(real_ws_dir)], "不得新增注册项"
    assert calls and calls[0][0] == str(real_ws_dir), "已有 current 必须照常激活"


def test_normal_default_root_registers_in_production_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1-3 正常路径：非临时默认根 + 生产注册表 → 注册并设为 current（新语义）.

    ~/lfl-workspace 在生产中恒为非临时目录；单测无法在真实 home 建目录，
    以 monkeypatch _cwd_in_system_temp→False 精确覆盖该分支臂（真实临时臂由
    上面三个用例实测），并用 fakehome 让 allowlist 的 home 子树规则放行。
    """
    prod_data = _prod_registry(tmp_path, monkeypatch)
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    root = _set_default_root(monkeypatch, fake_home / "lfl-workspace")
    monkeypatch.setattr(factory_mod, "_cwd_in_system_temp", lambda _p: False)
    settings = SimpleNamespace(data_dir=str(prod_data))
    calls: list = []

    factory_mod._activate_default_workspace(_fake_engine(calls), settings)

    from llm_loop.workspace.store import WorkspaceStore

    store = WorkspaceStore(str(prod_data))
    assert [w.path for w in store.list()] == [str(root)]
    assert store.get_current() is not None and store.get_current().path == str(root)
    assert calls and calls[0][0] == str(root), "注册后必须激活默认工作区"
