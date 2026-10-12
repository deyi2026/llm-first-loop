"""EVO-20260923 根治：临时 cwd 不得自动注册进生产注册表.

历史事故：pytest tmp_path / mkdtemp（/tmp、/var/folders）下启动的引擎把
一次性目录写进 data/workspaces.json，累计 95 条 retired 垃圾。防线为双条件：
_cwd_in_system_temp（cwd 在系统临时区）且 _registry_is_production_default
（data_dir 未被 DATA_DIR 显式改写）→ 跳过自动注册。隔离运行
（评测/测试显式 DATA_DIR）不受影响。
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


def test_temp_cwd_skips_production_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """临时 cwd + 生产默认 data 目录 → 不注册、不设默认 current."""
    prod_data = _prod_registry(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)  # pytest tmp_path 位于系统临时区
    settings = SimpleNamespace(data_dir=str(prod_data))
    calls: list = []

    factory_mod._activate_default_workspace(_fake_engine(calls), settings)

    from llm_loop.workspace.store import WorkspaceStore

    store = WorkspaceStore(str(prod_data))
    assert store.list() == [], "临时 cwd 不得写入生产注册表"
    assert store.get_current() is None
    assert calls == [], "注册表无 current 时不应调用 set_workspace"


def test_temp_cwd_escape_hatch_registers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LFL_ALLOW_TEMP_WORKSPACE=1 显式要求注册 → 照常注册（逃逸阀）."""
    prod_data = _prod_registry(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LFL_ALLOW_TEMP_WORKSPACE", "1")
    settings = SimpleNamespace(data_dir=str(prod_data))
    calls: list = []

    factory_mod._activate_default_workspace(_fake_engine(calls), settings)

    from llm_loop.workspace.store import WorkspaceStore

    store = WorkspaceStore(str(prod_data))
    assert [w.path for w in store.list()] == [str(tmp_path)]
    assert store.get_current() is not None
    assert calls, "注册后必须激活工作区"


def test_temp_cwd_with_isolated_registry_registers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """临时 cwd + 显式隔离 data 目录（评测语义）→ 照常注册，评测行为不变."""
    prod_data = _prod_registry(tmp_path, monkeypatch)
    iso_data = tmp_path / "iso-data"
    monkeypatch.chdir(tmp_path)
    settings = SimpleNamespace(data_dir=str(iso_data))  # != 生产默认
    calls: list = []

    factory_mod._activate_default_workspace(_fake_engine(calls), settings)

    from llm_loop.workspace.store import WorkspaceStore

    store = WorkspaceStore(str(iso_data))
    assert [w.path for w in store.list()] == [str(tmp_path)]
    assert calls, "隔离注册表注册后必须激活工作区"
    assert prod_data.exists()


def test_temp_cwd_activates_existing_current_without_registering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """生产注册表已有 current 时：临时 cwd 启动不注册，但 current 仍被激活."""
    prod_data = _prod_registry(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
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
