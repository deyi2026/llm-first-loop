"""读路径切换测试（spec §5.2.1 / design.md §2.4.1）.

全走 tmp_path（M64 防污染真实 data/）。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore


def _build_stores(tmp_path: Path, read_path: str = "session_json") -> tuple[EventStore, SessionStore]:
    event_store = EventStore(tmp_path / "event_logs", enabled=True)
    session_store = SessionStore(
        tmp_path / "sessions",
        event_store=event_store,
        read_path_source=read_path,
    )
    return event_store, session_store


def _seed(session_store: SessionStore) -> str:
    sid = session_store.create()
    session_store.append(sid, Message(role="user", content="hello", source=MessageSource.USER))
    session_store.append(sid, Message(role="assistant", content="world", source=MessageSource.SYSTEM))
    return sid


def test_read_path_session_json_default(tmp_path):
    """READ_PATH_SOURCE=session_json（默认）→ 既有 load 行为（零回归）."""
    _, session_store = _build_stores(tmp_path, "session_json")
    sid = _seed(session_store)
    session = session_store.load(sid)
    assert len(session.messages) == 2
    assert session.messages[0].content == "hello"


def test_read_path_event_log_replay(tmp_path):
    """READ_PATH_SOURCE=event_log → 从事件日志 replay 重建."""
    event_store, session_store = _build_stores(tmp_path, "session_json")
    sid = _seed(session_store)
    # 切换读路径为 event_log
    session_store._read_path_source = "event_log"  # noqa: SLF001
    session = session_store.load(sid)
    assert len(session.messages) == 2
    assert session.messages[0].content == "hello"
    assert session.messages[1].content == "world"


def test_read_path_event_log_fallback_on_missing(tmp_path):
    """event_log 模式下事件日志不存在 → 回退 session JSON."""
    event_store, session_store = _build_stores(tmp_path, "session_json")
    sid = _seed(session_store)
    # 删除事件日志
    event_store._path(sid).unlink()  # noqa: SLF001
    session_store._read_path_source = "event_log"  # noqa: SLF001
    # 应回退到 session JSON
    session = session_store.load(sid)
    assert len(session.messages) == 2


def test_read_path_event_log_fallback_on_corrupt(tmp_path):
    """event_log 模式下事件日志损坏 → 回退 session JSON."""
    event_store, session_store = _build_stores(tmp_path, "session_json")
    sid = _seed(session_store)
    # 损坏事件日志
    event_store._path(sid).write_text("not json\n", encoding="utf-8")  # noqa: SLF001
    session_store._read_path_source = "event_log"  # noqa: SLF001
    session = session_store.load(sid)
    assert len(session.messages) == 2


def test_read_path_switch_reversible(tmp_path):
    """灰度切换可逆：切 event_log → 切回 session_json 行为恢复."""
    event_store, session_store = _build_stores(tmp_path, "session_json")
    sid = _seed(session_store)
    # 切 event_log
    session_store._read_path_source = "event_log"  # noqa: SLF001
    s1 = session_store.load(sid)
    assert s1.messages[0].content == "hello"
    # 切回 session_json
    session_store._read_path_source = "session_json"  # noqa: SLF001
    s2 = session_store.load(sid)
    assert s2.messages[0].content == "hello"



def test_global_session_id_claim_prevents_cross_workspace_event_collision(tmp_path):
    """EventStore按sid全局键；SessionStore必须在第二workspace首次落盘前拒绝重复sid。"""
    import pytest

    from llm_loop.core.message import Message, MessageSource
    from llm_loop.core.session import Session, SessionIdConflictError

    sessions_base = tmp_path / "sessions"
    event_store = EventStore(tmp_path / "event_logs", enabled=True)
    root_a = sessions_base / "workspace-a"
    root_b = sessions_base / "workspace-b"
    sid = "same-session-id"
    store_a = SessionStore(
        root_a, event_store=event_store, identity_root=sessions_base
    )
    store_b = SessionStore(
        root_b, event_store=event_store, identity_root=sessions_base
    )

    store_a.save(
        Session(
            session_id=sid,
            messages=[Message(role="user", content="workspace-A", source=MessageSource.USER)],
        )
    )
    with pytest.raises(SessionIdConflictError, match="其他工作区|占用"):
        store_b.save(
            Session(
                session_id=sid,
                messages=[
                    Message(role="user", content="workspace-B", source=MessageSource.USER)
                ],
            )
        )

    assert (root_a / f"{sid}.json").exists()
    assert not (root_b / f"{sid}.json").exists()
    events = event_store.read(sid)
    assert any(e.payload.get("content") == "workspace-A" for e in events)
    assert all(e.payload.get("content") != "workspace-B" for e in events)


def test_loading_missing_session_does_not_claim_global_id_for_workspace(tmp_path):
    """只读不存在sid不得产生全局owner副作用；真正首次save的workspace才拥有该ID。"""
    from llm_loop.core.session import Session

    sessions_base = tmp_path / "sessions"
    sid = "read-only-missing-id"
    store_a = SessionStore(
        sessions_base / "workspace-a", identity_root=sessions_base
    )
    store_b = SessionStore(
        sessions_base / "workspace-b", identity_root=sessions_base
    )

    missing = store_a.load(sid)
    assert missing.session_id == sid
    assert not (store_a.root / f"{sid}.json").exists()

    store_b.save(Session(session_id=sid))

    assert (store_b.root / f"{sid}.json").exists()
    assert not (store_a.root / f"{sid}.json").exists()


def test_global_session_id_claim_is_cross_process_atomic(tmp_path):
    """不同进程同时在不同workspace claim同sid时必须恰一成功，不能双写全局Event/Archive键。"""
    import json
    import os
    import subprocess
    import sys
    import time

    sessions_base = tmp_path / "sessions"
    sid = "cross-process-global-id"
    start_at = time.time() + 0.5
    root = Path(__file__).resolve().parents[2]
    code = (
        "import sys,time\n"
        "from llm_loop.core.session import Session,SessionIdConflictError,SessionStore\n"
        "base,workspace,sid,start_at=sys.argv[1],sys.argv[2],sys.argv[3],float(sys.argv[4])\n"
        "store=SessionStore(workspace, identity_root=base)\n"
        "while time.time()<start_at: time.sleep(0.002)\n"
        "try:\n"
        "    store.save(Session(session_id=sid))\n"
        "    print('OK')\n"
        "except SessionIdConflictError:\n"
        "    print('CONFLICT')\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    roots = [sessions_base / "workspace-a", sessions_base / "workspace-b"]
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(sessions_base), str(workspace), sid, str(start_at)],
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for workspace in roots
    ]
    results = []
    for proc in procs:
        out, err = proc.communicate(timeout=15)
        assert proc.returncode == 0, err
        results.append(out.strip())

    assert sorted(results) == ["CONFLICT", "OK"]
    existing = [workspace for workspace in roots if (workspace / f"{sid}.json").exists()]
    assert len(existing) == 1
    owner = json.loads((sessions_base / ".identity" / f"{sid}.json").read_text())
    assert owner["owner"] == existing[0].relative_to(sessions_base).as_posix()


def test_global_session_id_claim_rejects_legacy_event_history_without_session_json(tmp_path):
    """旧版本已删session JSON但事件仍在时，sid归属未知，任何workspace都不得重新claim。"""
    import pytest

    from llm_loop.core.session import Session, SessionIdConflictError

    sessions_base = tmp_path / "sessions"
    event_store = EventStore(tmp_path / "event_logs", enabled=True)
    sid = "legacy-deleted-session-id"
    event_store.append(
        sid,
        "session.created",
        {"version": 5, "created_at": "2026-08-20T00:00:00+00:00"},
    )
    assert not (sessions_base / f"{sid}.json").exists()

    store_b = SessionStore(
        sessions_base / "workspace-b",
        event_store=event_store,
        identity_root=sessions_base,
    )

    with pytest.raises(SessionIdConflictError, match="历史|归属|占用"):
        store_b.save(Session(session_id=sid))

    assert not (store_b.root / f"{sid}.json").exists()


def test_global_session_id_claim_rejects_legacy_archive_history_without_session_json(tmp_path):
    """仅剩ArchiveStore历史时也不得把旧sid重新分配到任意workspace。"""
    import pytest

    from llm_loop.core.session import Session, SessionIdConflictError
    from llm_loop.memory.archive import ArchiveStore

    sessions_base = tmp_path / "sessions"
    archive = ArchiveStore(tmp_path / "archives")
    sid = "legacy-archive-only-session-id"
    archive.archive(sid, role="user", source="user", content="legacy-private-history")

    store_b = SessionStore(
        sessions_base / "workspace-b",
        identity_root=sessions_base,
        identity_history_exists_fn=lambda candidate: archive.stats(candidate)["archived_count"] > 0,
    )

    with pytest.raises(SessionIdConflictError, match="历史|归属|占用"):
        store_b.save(Session(session_id=sid))

    assert not (store_b.root / f"{sid}.json").exists()


def test_session_identity_owner_claim_fsyncs_file_and_parent_directory(tmp_path, monkeypatch):
    """全局owner是跨workspace隔离证据；claim成功前必须fsync文件与.identity目录。"""
    import os

    sessions_base = tmp_path / "sessions"
    store = SessionStore(sessions_base / "workspace-a", identity_root=sessions_base)
    real_open = os.open
    real_fsync = os.fsync
    dir_fds: list[int] = []
    fsynced: list[int] = []

    def track_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        if Path(path) == sessions_base / ".identity":
            dir_fds.append(fd)
        return fd

    def track_fsync(fd):
        fsynced.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "open", track_open)
    monkeypatch.setattr(os, "fsync", track_fsync)
    store.claim_session_id("durable-owner-id")

    assert len(fsynced) >= 2, "至少应fsync owner文件与父目录"
    assert dir_fds, "owner replace后应显式打开.identity目录"
    assert any(fd in fsynced for fd in dir_fds), "owner父目录fd必须fsync"


def test_identity_owner_write_oserror_is_not_relabelled_as_lock_failure(tmp_path, monkeypatch):
    """owner业务写OSError必须原样传播，不能被_identity_lock误判成锁获取失败。"""
    import pytest

    sessions_base = tmp_path / "sessions"
    store = SessionStore(sessions_base / "workspace-a", identity_root=sessions_base)

    def fail_durable_write(_path, _content):
        raise OSError("owner-disk-full-sentinel")

    monkeypatch.setattr(store, "_durable_replace_text", fail_durable_write)
    with pytest.raises(OSError, match="owner-disk-full-sentinel"):
        store.claim_session_id("identity-body-oserror")


def test_identity_owner_claim_survives_unsupported_directory_fsync(tmp_path, monkeypatch, caplog):
    """非POSIX/文件系统不支持目录fsync时，owner文件已durable则应降级告警而非禁用SessionStore。"""
    import os

    sessions_base = tmp_path / "sessions"
    identity_dir = sessions_base / ".identity"
    store = SessionStore(sessions_base / "workspace-a", identity_root=sessions_base)
    real_open = os.open

    def fail_directory_open(path, flags, *args, **kwargs):
        if Path(path) == identity_dir:
            raise OSError("directory-fsync-unsupported-sentinel")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", fail_directory_open)
    store.claim_session_id("portable-owner-id")

    assert (identity_dir / "portable-owner-id.json").exists()
    assert "耐久性降级" in caplog.text


def test_physical_delete_purges_event_history_and_prevents_event_log_replay(tmp_path):
    """物理删除后EventStore不得保留旧sid历史，否则event_log读路径可复活已删会话。"""
    from llm_loop.core.message import Message, MessageSource

    event_store = EventStore(tmp_path / "event_logs", enabled=True)
    store = SessionStore(
        tmp_path / "sessions",
        event_store=event_store,
        read_path_source="event_log",
    )
    sid = store.create()
    session = store.load(sid)
    session.messages.append(
        Message(role="user", content="must-be-physically-deleted", source=MessageSource.USER)
    )
    store.save(session)
    assert event_store.exists(sid)
    assert store.delete(sid) is True
    assert not store.exists(sid)

    assert event_store.exists(sid) is False
    import pytest

    from llm_loop.core.session import SessionIdConflictError

    with pytest.raises(SessionIdConflictError, match="删除|不可恢复"):
        store.load(sid)
