"""工作区注册表单元测试（对齐 DSH Workspace：目录绑定 + 会话分区）."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from llm_loop.workspace.store import WorkspaceStore, workspace_key


def test_workspace_key_encoding():
    assert workspace_key("/w/dev/My-Project") == "--w-dev-My-Project--"
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


def test_workspace_key_collision_does_not_alias_registered_workspaces(tmp_path):
    """legacy DSH key可碰撞，但内部注册表必须为不同真实路径分配不同稳定ID。"""
    store = WorkspaceStore(tmp_path / "data")
    ws_a = tmp_path / "a-b" / "c"
    ws_b = tmp_path / "a" / "b-c"
    ws_a.mkdir(parents=True)
    ws_b.mkdir(parents=True)

    assert workspace_key(ws_a) == workspace_key(ws_b), "测试前置：legacy key必须构造碰撞"
    a = store.register(ws_a)
    b = store.register(ws_b)

    assert a.path == str(ws_a.resolve())
    assert b.path == str(ws_b.resolve())
    assert a.id != b.id
    assert len(store.list()) == 2
    assert store.get(a.id).path == a.path
    assert store.get(b.id).path == b.path


def test_collision_workspace_ids_persist_and_reload(tmp_path):
    data = tmp_path / "data"
    a_path = tmp_path / "a-b" / "c"
    b_path = tmp_path / "a" / "b-c"
    a_path.mkdir(parents=True)
    b_path.mkdir(parents=True)
    store = WorkspaceStore(data)
    a = store.register(a_path)
    b = store.register(b_path)
    store.switch(b.id)

    reloaded = WorkspaceStore(data)
    assert reloaded.get(a.id).path == str(a_path.resolve())
    assert reloaded.get(b.id).path == str(b_path.resolve())
    assert reloaded.get_current().id == b.id
    assert reloaded.register(b_path).id == b.id


def test_workspace_store_skips_unsafe_persisted_id(tmp_path, caplog):
    import json

    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    path = tmp_path / "workspace"
    path.mkdir()
    (data / "workspaces.json").write_text(
        json.dumps(
            {
                "version": 1,
                "current": "../escape",
                "workspaces": [{"id": "../escape", "path": str(path), "created_at": "x"}],
            }
        ),
        encoding="utf-8",
    )

    with caplog.at_level("WARNING", logger="llm_loop.workspace.store"):
        store = WorkspaceStore(data)

    assert store.list() == []
    assert store.get_current() is None
    assert any("不安全ID" in record.message for record in caplog.records)


def test_stale_workspace_store_instances_do_not_lose_updates(tmp_path):
    """两个长寿命实例先读旧快照后依次写，也不能用stale RMW覆盖另一方注册。"""
    data = tmp_path / "data"
    a_path = tmp_path / "proc-a"
    b_path = tmp_path / "proc-b"
    a_path.mkdir()
    b_path.mkdir()
    store_a = WorkspaceStore(data)
    store_b = WorkspaceStore(data)  # 模拟另一进程在A写入前已加载旧快照

    a = store_a.register(a_path)
    b = store_b.register(b_path)

    final = WorkspaceStore(data)
    assert final.get(a.id) is not None
    assert final.get(b.id) is not None
    assert len(final.list()) == 2


def test_stale_workspace_store_switch_reloads_registry_before_mutation(tmp_path):
    """stale实例切换时应先重载磁盘，能看到另一实例新注册的workspace且不覆盖列表。"""
    data = tmp_path / "data"
    a_path = tmp_path / "proc-a"
    b_path = tmp_path / "proc-b"
    a_path.mkdir()
    b_path.mkdir()
    stale = WorkspaceStore(data)
    writer = WorkspaceStore(data)
    a = writer.register(a_path)
    b = writer.register(b_path)

    switched = stale.switch(b.id)

    assert switched.id == b.id
    final = WorkspaceStore(data)
    assert final.get(a.id) is not None
    assert final.get(b.id) is not None
    assert final.get_current().id == b.id


def test_workspace_mutation_refuses_to_overwrite_corrupt_registry(tmp_path):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    registry = data / "workspaces.json"
    registry.write_text("{broken", encoding="utf-8")
    store = WorkspaceStore(data)  # 初始化仍fail-open
    ws = tmp_path / "workspace"
    ws.mkdir()
    before = registry.read_bytes()

    with pytest.raises(ValueError, match="注册表损坏"):
        store.register(ws)

    assert registry.read_bytes() == before


def test_cross_process_concurrent_workspace_register_keeps_both(tmp_path):
    """两个独立Python进程同一barrier后注册，flock内reload必须保留双方更新。"""
    data = tmp_path / "data"
    ws_a = tmp_path / "proc-a"
    ws_b = tmp_path / "proc-b"
    ws_a.mkdir()
    ws_b.mkdir()
    go = tmp_path / "go"
    ready_a = tmp_path / "ready-a"
    ready_b = tmp_path / "ready-b"
    script = r"""
import sys, time
from pathlib import Path
from llm_loop.workspace.store import WorkspaceStore

data, workspace, ready, go = map(Path, sys.argv[1:])
store = WorkspaceStore(data)
ready.write_text("1", encoding="utf-8")
deadline = time.monotonic() + 10
while not go.exists():
    if time.monotonic() > deadline:
        raise SystemExit("barrier timeout")
    time.sleep(0.01)
store.register(workspace)
"""
    env = os.environ.copy()
    repo_src = Path(__file__).resolve().parents[2] / "src"
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(repo_src) + (
        os.pathsep + existing_pythonpath if existing_pythonpath else ""
    )
    proc_a = subprocess.Popen(
        [sys.executable, "-c", script, str(data), str(ws_a), str(ready_a), str(go)],
        env=env,
    )
    proc_b = subprocess.Popen(
        [sys.executable, "-c", script, str(data), str(ws_b), str(ready_b), str(go)],
        env=env,
    )
    deadline = time.monotonic() + 10
    while not (ready_a.exists() and ready_b.exists()):
        if time.monotonic() > deadline:
            proc_a.kill()
            proc_b.kill()
            raise AssertionError("child processes did not reach barrier")
        time.sleep(0.01)
    go.write_text("1", encoding="utf-8")
    assert proc_a.wait(timeout=10) == 0
    assert proc_b.wait(timeout=10) == 0

    final = WorkspaceStore(data)
    paths = {w.path for w in final.list()}
    assert str(ws_a.resolve()) in paths
    assert str(ws_b.resolve()) in paths
    assert len(paths) == 2


def test_workspace_register_save_failure_rolls_back_memory_and_disk(tmp_path, monkeypatch):
    """持久化失败时register不得返回仅存在于内存的“成功”workspace。"""
    import llm_loop.workspace.store as workspace_store_mod

    data = tmp_path / "data"
    a_path = tmp_path / "a"
    b_path = tmp_path / "b"
    a_path.mkdir()
    b_path.mkdir()
    store = WorkspaceStore(data)
    a = store.register(a_path)
    before = (data / "workspaces.json").read_bytes()

    def fail_replace(_src, _dst):
        raise OSError("disk replace failed")

    monkeypatch.setattr(workspace_store_mod.os, "replace", fail_replace)
    with pytest.raises(RuntimeError, match="持久化失败"):
        store.register(b_path)

    assert store.get(a.id) is not None
    assert store.get_by_path(b_path) is None
    assert (data / "workspaces.json").read_bytes() == before


def test_workspace_switch_save_failure_rolls_back_current(tmp_path, monkeypatch):
    """current写盘失败时内存current也必须回滚，不能与重启后registry分裂。"""
    import llm_loop.workspace.store as workspace_store_mod

    data = tmp_path / "data"
    a_path = tmp_path / "a"
    b_path = tmp_path / "b"
    a_path.mkdir()
    b_path.mkdir()
    store = WorkspaceStore(data)
    a = store.register(a_path)
    b = store.register(b_path)
    store.switch(a.id)
    before = (data / "workspaces.json").read_bytes()

    def fail_replace(_src, _dst):
        raise OSError("disk replace failed")

    monkeypatch.setattr(workspace_store_mod.os, "replace", fail_replace)
    with pytest.raises(RuntimeError, match="持久化失败"):
        store.switch(b.id)

    assert store.get_current() is not None
    assert store.get_current().id == a.id
    assert (data / "workspaces.json").read_bytes() == before


def test_migrate_legacy_sessions_does_not_silently_strand_conflicting_source(tmp_path):
    """部分迁移后同名source/dest内容不同，不能永久跳过旧根而让engine只看旧dest。"""
    data = tmp_path / "data"
    store = WorkspaceStore(data)
    ws = tmp_path / "proj"
    ws.mkdir()
    w = store.register(ws)
    sessions = data / "sessions"
    target = sessions / w.id
    target.mkdir(parents=True)
    source = sessions / "same.json"
    dest = target / "same.json"
    source.write_text('{"version":"SOURCE-NEWER"}', encoding="utf-8")
    dest.write_text('{"version":"DEST-OLDER"}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="迁移冲突"):
        store.migrate_legacy_sessions(data, w)

    assert source.read_text(encoding="utf-8") == '{"version":"SOURCE-NEWER"}'
    assert dest.read_text(encoding="utf-8") == '{"version":"DEST-OLDER"}'


def test_migrate_legacy_sessions_identical_existing_json_is_idempotent(tmp_path):
    """同名JSON内容相同属于安全幂等，不应误报冲突。"""
    data = tmp_path / "data"
    store = WorkspaceStore(data)
    ws = tmp_path / "proj"
    ws.mkdir()
    w = store.register(ws)
    sessions = data / "sessions"
    target = sessions / w.id
    target.mkdir(parents=True)
    source = sessions / "same.json"
    dest = target / "same.json"
    source.write_text('{"same":true}', encoding="utf-8")
    dest.write_text('{"same":true}', encoding="utf-8")

    assert store.migrate_legacy_sessions(data, w) == 0
    assert source.exists()
    assert dest.exists()


def test_reregister_removed_collision_workspace_reuses_original_id(tmp_path):
    """注销不删会话数据，因此同一路径再次注册必须复用原ID，不能因碰撞集合变化换分区。"""
    data = tmp_path / "data"
    a_path = tmp_path / "a-b" / "c"
    b_path = tmp_path / "a" / "b-c"
    a_path.mkdir(parents=True)
    b_path.mkdir(parents=True)
    store = WorkspaceStore(data)
    a = store.register(a_path)
    b = store.register(b_path)
    assert a.id != b.id

    assert store.remove(b.id) is True
    assert store.remove(a.id) is True
    b_again = store.register(b_path)

    assert b_again.id == b.id, "注销后重注册必须回到原session分区"


def test_removed_workspace_id_tombstone_prevents_collision_path_from_stealing_partition(tmp_path):
    """A注销后其ID仍保留；碰撞B不能趁legacy ID空闲抢走A的session分区。"""
    data = tmp_path / "data"
    a_path = tmp_path / "a-b" / "c"
    b_path = tmp_path / "a" / "b-c"
    a_path.mkdir(parents=True)
    b_path.mkdir(parents=True)
    store = WorkspaceStore(data)
    a = store.register(a_path)
    assert store.remove(a.id) is True

    b = store.register(b_path)
    a_again = store.register(a_path)

    assert b.id != a.id
    assert a_again.id == a.id


def test_removed_workspace_id_tombstone_survives_reload(tmp_path):
    data = tmp_path / "data"
    path = tmp_path / "workspace"
    path.mkdir()
    store = WorkspaceStore(data)
    original = store.register(path)
    assert store.remove(original.id) is True

    reloaded = WorkspaceStore(data)
    restored = reloaded.register(path)

    assert restored.id == original.id


def test_switch_registered_workspace_with_missing_path_fails_without_changing_current(tmp_path):
    from llm_loop.workspace.store import WorkspacePathUnavailableError

    data = tmp_path / "data"
    a_path = tmp_path / "a"
    b_path = tmp_path / "b"
    a_path.mkdir()
    b_path.mkdir()
    store = WorkspaceStore(data)
    a = store.register(a_path)
    b = store.register(b_path)
    store.switch(a.id)
    b_path.rmdir()

    with pytest.raises(WorkspacePathUnavailableError, match="目录当前不可用"):
        store.switch(b.id)

    assert store.get_current() is not None
    assert store.get_current().id == a.id


def test_register_and_switch_precommit_failure_restores_retired_tombstone(tmp_path):
    """复活retired workspace的runtime预检失败时，active/retired与磁盘都必须回到原快照。"""
    data = tmp_path / "data"
    path = tmp_path / "workspace"
    path.mkdir()
    store = WorkspaceStore(data)
    original = store.register(path)
    assert store.remove(original.id) is True
    before = (data / "workspaces.json").read_bytes()

    def fail_precommit(_workspace):
        raise OSError("runtime precommit failed")

    with pytest.raises(OSError, match="runtime precommit failed"):
        store.register_and_switch(path, precommit=fail_precommit)

    assert store.get(original.id) is None
    assert store.get_current() is None
    assert (data / "workspaces.json").read_bytes() == before
    reloaded = WorkspaceStore(data)
    restored = reloaded.register(path)
    assert restored.id == original.id


def test_switch_precommit_failure_does_not_persist_current(tmp_path):
    """已有workspace的runtime预检失败时，current内存与registry文件都不得变化。"""
    data = tmp_path / "data"
    a_path = tmp_path / "a"
    b_path = tmp_path / "b"
    a_path.mkdir()
    b_path.mkdir()
    store = WorkspaceStore(data)
    a = store.register(a_path)
    b = store.register(b_path)
    store.switch(a.id)
    before = (data / "workspaces.json").read_bytes()

    def fail_precommit(_workspace):
        raise OSError("runtime precommit failed")

    with pytest.raises(OSError, match="runtime precommit failed"):
        store.switch(b.id, precommit=fail_precommit)

    assert store.get_current() is not None
    assert store.get_current().id == a.id
    assert (data / "workspaces.json").read_bytes() == before
    assert WorkspaceStore(data).get_current().id == a.id
