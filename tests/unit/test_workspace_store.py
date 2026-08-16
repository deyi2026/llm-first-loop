"""工作区注册表单元测试（对齐 DSH Workspace：目录绑定 + 会话分区）."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.workspace.store import WorkspaceStore, workspace_key


def test_workspace_key_encoding():
    assert workspace_key("/Users/someone/My-Project") == "--Users-someone-My-Project--"
    assert workspace_key("/a/b") == "--a-b--"


def test_register_and_switch(tmp_path):
    store = WorkspaceStore(str(tmp_path / "data"))
    ws_a = Path(tmp_path / "proj-a")
    ws_a.mkdir()
    ws = store.register(ws_a)
    assert ws.id == "--" + str(ws_a).lstrip("/").replace("/", "-") + "--"
    assert store.get_current() is None  # register 不设 current
    store.switch(ws.id)
    assert store.get_current().path == str(ws_a)
    # 幂等注册
    assert store.register(ws_a).id == ws.id
    assert len(store.list()) == 1


def test_register_rejects_non_directory(tmp_path):
    store = WorkspaceStore(str(tmp_path / "data"))
    with pytest.raises(ValueError):
        store.register(str(tmp_path / "not_a_dir"))


def test_switch_unknown_raises(tmp_path):
    store = WorkspaceStore(str(tmp_path / "data"))
    with pytest.raises(ValueError):
        store.switch("no-such-ws")


def test_remove_current_rejected(tmp_path):
    store = WorkspaceStore(str(tmp_path / "data"))
    ws = Path(tmp_path / "p")
    ws.mkdir()
    w = store.register(ws)
    store.switch(w.id)
    assert store.remove(w.id) is False  # 当前不可注销
    assert store.remove("missing") is False


def test_persist_and_reload(tmp_path):
    data = tmp_path / "data"
    store = WorkspaceStore(str(data))
    ws = Path(tmp_path / "proj")
    ws.mkdir()
    w = store.register(ws)
    store.switch(w.id)
    # 重新加载（模拟重启）
    store2 = WorkspaceStore(str(data))
    assert store2.get_current().id == w.id
    assert store2.get(w.id).path == str(ws)


def test_migrate_legacy_sessions(tmp_path):
    data = tmp_path / "data"
    store = WorkspaceStore(str(data))
    ws = Path(tmp_path / "proj")
    ws.mkdir()
    w = store.register(ws)
    # 旧版单根会话文件
    sessions = data / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "s1.json").write_text("{}", encoding="utf-8")
    (sessions / "s2.json").write_text("{}", encoding="utf-8")
    (sessions / "s1.lock").write_text("", encoding="utf-8")
    # 非会话文件不迁移
    (sessions / "README.txt").write_text("x", encoding="utf-8")
    moved = store.migrate_legacy_sessions(str(data), w)
    assert moved == 3
    assert (sessions / w.id / "s1.json").exists()
    assert (sessions / w.id / "s2.json").exists()
    assert (sessions / w.id / "s1.lock").exists()
    assert (sessions / "README.txt").exists()  # 未迁移
    # 幂等：再跑不重复
    assert store.migrate_legacy_sessions(str(data), w) == 0
