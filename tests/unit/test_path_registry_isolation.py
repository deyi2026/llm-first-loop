"""R9-IMM-02 path_registry 隔离洞回归测试（D6 双修验证）.

场景：workspace_base 不可用（import 失败/抛异常）时——
- _registry_file() 必须抛 RuntimeError（拒绝静默回落相对路径 "data/"）
- 公开面（register_*/query_path/check_known_missing）fail-open 承接，不写真实 data/
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from llm_loop.tools import path_registry


def _break_registry_file(monkeypatch):
    def _raise():
        raise RuntimeError("workspace_base unavailable; refusing implicit data/ fallback")

    monkeypatch.setattr(path_registry, "_registry_file", _raise)
    monkeypatch.setattr(path_registry, "_LOADED", None)
    monkeypatch.setattr(path_registry, "_LOADED_PATH", None)


def test_registry_file_raises_when_import_blocked(monkeypatch):
    """workspace_base import 失败 → RuntimeError 而非相对 data/ 路径."""

    real_import = builtins.__import__

    def _blocked_import(name, *a, **kw):
        if name == "llm_loop.core.run_context":
            raise ImportError("blocked for test")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    monkeypatch.setattr(path_registry, "_REGISTRY_PATH", None)
    with pytest.raises(RuntimeError, match="workspace_base unavailable"):
        path_registry._registry_file()


def test_registry_file_raises_when_workspace_base_raises(monkeypatch):
    """workspace_base() 调用本身抛错 → 同样 RuntimeError（不静默）."""

    import llm_loop.core.run_context as rc

    def _boom():
        raise RuntimeError("no active context")

    monkeypatch.setattr(rc, "workspace_base", _boom)
    monkeypatch.setattr(path_registry, "_REGISTRY_PATH", None)
    with pytest.raises(RuntimeError, match="workspace_base unavailable"):
        path_registry._registry_file()


def test_registry_file_never_returns_relative_data(monkeypatch):
    """任何异常形态下都不返回相对路径 'data/path_registry.json'（洞的回归锚点）."""

    import llm_loop.core.run_context as rc

    monkeypatch.setattr(rc, "workspace_base", lambda: 1 / 0)
    monkeypatch.setattr(path_registry, "_REGISTRY_PATH", None)
    with pytest.raises(RuntimeError):
        path_registry._registry_file()  # 唯一允许出口：显式抛错


def test_public_apis_fail_open_no_real_data_write(monkeypatch, tmp_path):
    """workspace_base 不可用：公开面全部 fail-open，且无真实 data/ 写入."""

    _break_registry_file(monkeypatch)
    monkeypatch.chdir(tmp_path)
    # 写面：不抛、不落盘
    path_registry.register_missing("/abs/never_exists.py")
    path_registry.register_exists("/abs/never_hit.py")
    # 读面：不抛、返回保守结果（query fail-open 语义=exists None + from error，如实上报）
    assert path_registry.check_known_missing("/abs/never_exists.py") is False
    qp = path_registry.query_path("/abs/never_exists.py")
    assert qp["from"] == "error" and qp["exists"] is None
    assert not (tmp_path / "data" / "path_registry.json").exists()


def test_register_fail_open_writes_nothing_when_mutate_raises(monkeypatch, tmp_path):
    """_mutate 内 _registry_file 抛错 → register_missing fail-open 不落盘."""

    monkeypatch.setattr(path_registry, "_LOADED", None)
    monkeypatch.setattr(path_registry, "_LOADED_PATH", None)
    real_registry_file = path_registry._registry_file

    def _raise_only_on_fresh_resolve():
        # _mutate 每次重新解析落点：让第二次以后（mutate 内）抛错
        if getattr(test_register_fail_open_writes_nothing_when_mutate_raises, "armed", False):
            raise RuntimeError("workspace_base unavailable; refusing implicit data/ fallback")
        return real_registry_file()

    monkeypatch.setattr(path_registry, "_registry_file", _raise_only_on_fresh_resolve)
    monkeypatch.chdir(tmp_path)
    test_register_fail_open_writes_nothing_when_mutate_raises.armed = True  # type: ignore[attr-defined]
    try:
        path_registry.register_missing("/abs/x.py")
    finally:
        test_register_fail_open_writes_nothing_when_mutate_raises.armed = False  # type: ignore[attr-defined]
    assert not (tmp_path / "data" / "path_registry.json").exists()
    assert not (Path.cwd() / "path_registry.json").exists()


def test_registry_write_lands_in_workspace(tmp_path, monkeypatch):
    """正常路径：workspace_base 可用时登记落指定 data/（行为不回归）."""

    monkeypatch.setattr(
        path_registry,
        "_REGISTRY_PATH",
        tmp_path / "data" / "path_registry.json",
    )
    monkeypatch.setattr(path_registry, "_LOADED", None)
    monkeypatch.setattr(path_registry, "_LOADED_PATH", None)
    path_registry.register_missing("/abs/gone.py")
    f = tmp_path / "data" / "path_registry.json"
    assert f.exists()
    payload = json.loads(f.read_text(encoding="utf-8"))
    assert any("gone.py" in k for k in payload)
