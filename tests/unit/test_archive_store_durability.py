"""ArchiveStore Fleet T2: canonical segment safety versus derived index state.

Injected failures and concurrent writers touch tmp_path only. No production
archive is read or mutated. The JSONL append remains a distinct T1 operation.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from llm_loop.memory import archive as module
from llm_loop.memory.archive import (
    ArchiveCommitUncertainError,
    ArchivePersistError,
    ArchiveStore,
)

SID = "durable-session"


def _store(tmp_path: Path) -> ArchiveStore:
    return ArchiveStore(tmp_path, segment_bytes=0)


def _segment(root: Path) -> Path:
    return root / f"{SID}.jsonl"


def _entries(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _segment_fsync_injector(path: Path, *, always: bool) -> Callable[[int], None]:
    """fsync 注入按目标文件身份（inode）匹配，不按调用序号.

    旧 fail_once 语义是"patch 生效后进程内第 1 次 os.fsync 失败"：窗口期内
    任何其他线程的一次 os.fsync（典型为泄漏的后台写线程，fail-open 路径吞错
    继续）都会消耗掉该次注入，被测 append 的 fsync 反而成功，pytest.raises
    假红（CI 偶发根因，机制已独立复现）。改为仅对被测 segment 的 fd 注入、
    其余 fd 透传真实 fsync：注入结果与进程内并发 fsync 活动完全解耦，外来
    调用者也不再被误伤。always=False 恰好失败一次（append 失败、rollback
    成功 → PersistError）；always=True 恒失败（rollback 也不确认 → Uncertain）。
    """
    original_fsync = module.os.fsync
    seg_stat = path.stat()
    failed = False

    def injected(fd: int) -> None:
        nonlocal failed
        try:
            on_segment = os.path.samestat(os.fstat(fd), seg_stat)
        except OSError:
            on_segment = False
        if on_segment and (always or not failed):
            failed = True
            raise OSError("injected segment fsync failure")
        original_fsync(fd)

    return injected


def test_append_file_fsync_and_derived_index_readback(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = store.archive(SID, role="tool", source="test", content="durable one", tool_call_id="tc1")
    assert _entries(_segment(tmp_path))[0]["id"] == record.id
    assert store.get_by_tool_call_id(SID, "tc1")["id"] == record.id
    assert len((tmp_path / f"{SID}.jsonl.idx").read_text().splitlines()) == 1


def test_append_single_fsync_failure_rolls_back_before_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    store.archive(SID, role="user", source="test", content="original")
    path = _segment(tmp_path)
    old = path.read_bytes()
    seen: list[str] = []
    store.add_post_save_hook(lambda entry: seen.append(entry.id))

    with monkeypatch.context() as m:
        m.setattr(module.os, "fsync", _segment_fsync_injector(_segment(tmp_path), always=False))
        with pytest.raises(ArchivePersistError, match="rolled back"):
            store.archive(SID, role="tool", source="test", content="must not appear")
    assert path.read_bytes() == old
    assert seen == []


def test_append_rollback_failure_is_uncertain_and_hook_not_called(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    store.archive(SID, role="user", source="test", content="original")
    seen: list[str] = []
    store.add_post_save_hook(lambda entry: seen.append(entry.id))
    with monkeypatch.context() as m:
        m.setattr(module.os, "fsync", _segment_fsync_injector(_segment(tmp_path), always=True))
        with pytest.raises(ArchiveCommitUncertainError) as error:
            store.archive(SID, role="tool", source="test", content="maybe visible")
    assert error.value.operation == "archive_append"
    assert error.value.visible_state in {"matches", "mismatch", "unreadable"}
    assert seen == []


def test_atomic_summary_rewrite_failure_preserves_whole_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    first = store.archive(SID, role="user", source="test", content="first")
    store.archive(SID, role="user", source="test", content="second")
    path = _segment(tmp_path)
    old = path.read_bytes()
    original_replace = module.os.replace

    def fail_segment(source: Path, dest: Path) -> None:
        if Path(dest) == path:
            raise OSError("injected replace refusal")
        original_replace(source, dest)

    with monkeypatch.context() as m:
        m.setattr(module.os, "replace", fail_segment)
        assert store.update_summary(first.id, "new summary", "llm") is False
    assert path.read_bytes() == old
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_summary_post_replace_dir_fsync_uncertainty_has_exact_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    first = store.archive(SID, role="user", source="test", content="canonical")
    path = _segment(tmp_path)
    original_fsync = module._fsync_directory

    def fail_parent(directory: Path) -> None:
        if directory == tmp_path:
            raise OSError("dir fsync unavailable")
        original_fsync(directory)

    with monkeypatch.context() as m:
        m.setattr(module, "_fsync_directory", fail_parent)
        assert store.update_summary(first.id, "updated but durability unconfirmed", "llm") is False
    rows = _entries(path)
    assert rows[0]["summary"] == "updated but durability unconfirmed"
    assert rows[0]["content"] == "canonical"


def test_atomic_replace_uncertain_error_contains_expected_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "one.jsonl"
    path.write_bytes(b"old\n")
    payload = b"new whole bytes\n"
    with monkeypatch.context() as m:
        m.setattr(module, "_fsync_directory", lambda _p: (_ for _ in ()).throw(OSError("dir fence")))
        with pytest.raises(ArchiveCommitUncertainError) as exc:
            module._atomic_replace_bytes(path, payload, operation="test_replace")
    assert exc.value.operation == "test_replace"
    assert exc.value.expected_sha256 == hashlib.sha256(payload).hexdigest()
    assert exc.value.visible_state == "matches"
    assert path.read_bytes() == payload


def test_rebuild_index_failure_preserves_old_index_and_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    record = store.archive(SID, role="tool", source="test", content="source fact", tool_call_id="tc1")
    path = _segment(tmp_path)
    idx = store._index_path(path)
    old_idx, old_primary = idx.read_bytes(), path.read_bytes()
    original_replace = module.os.replace

    def fail_index(source: Path, dest: Path) -> None:
        if Path(dest) == idx:
            raise OSError("index replace blocked")
        original_replace(source, dest)

    with monkeypatch.context() as m:
        m.setattr(module.os, "replace", fail_index)
        assert store.rebuild_segment_index(path) == 0
    assert idx.read_bytes() == old_idx
    assert path.read_bytes() == old_primary
    assert store.get_by_tool_call_id(SID, "tc1")["id"] == record.id


def test_stale_sidecar_offset_never_yields_wrong_tool_result(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = store.archive(SID, role="tool", source="test", content="original receipt", tool_call_id="tc-original")
    other = store.archive(SID, role="tool", source="test", content="different receipt", tool_call_id="tc-other")
    idx = store._index_path(_segment(tmp_path))
    rows = _entries(idx)
    rows[0]["offset"] = rows[1]["offset"]  # stale index points at different canonical line
    idx.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    found = store.get_by_tool_call_id(SID, "tc-original")
    assert found is not None and found["id"] == original.id
    assert found["id"] != other.id
    assert found["content"] == "original receipt"


def test_stale_sidecar_search_offset_never_returns_unrelated_source(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.archive(SID, role="user", source="test", content="needle first")
    store.archive(SID, role="user", source="test", content="unrelated other")
    idx = store._index_path(_segment(tmp_path))
    rows = _entries(idx)
    rows[0]["offset"] = rows[1]["offset"]
    idx.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    hits = store.search(SID, "needle", limit=1)
    assert len(hits) == 1
    assert hits[0]["id"] == first.id
    assert hits[0]["content_preview"] == "needle first"


def test_corrupt_derived_negative_offset_falls_back_to_fulltext(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.archive(SID, role="user", source="test", content="recoverable text")
    idx = store._index_path(_segment(tmp_path))
    rows = _entries(idx)
    rows[0]["offset"] = -1
    idx.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    assert store.search(SID, "recoverable")[0]["id"] == first.id
    assert store.get_by_id(SID, first.id)["id"] == first.id


def test_two_store_instances_append_concurrently_without_lost_records(tmp_path: Path) -> None:
    stores = [_store(tmp_path), _store(tmp_path)]
    barrier = threading.Barrier(12)

    def worker(i: int) -> str:
        barrier.wait()
        return stores[i % 2].archive(
            SID, role="tool", source="test", content=f"payload-{i}", tool_call_id=f"tc-{i}",
        ).id

    with ThreadPoolExecutor(max_workers=12) as pool:
        ids = list(pool.map(worker, range(12)))
    rows = _entries(_segment(tmp_path))
    assert len(rows) == len(set(ids)) == 12
    assert {r["id"] for r in rows} == set(ids)
    assert {r["content"] for r in rows} == {f"payload-{i}" for i in range(12)}
    assert len(_entries(stores[0]._index_path(_segment(tmp_path)))) == 12


def test_independent_processes_share_archive_writer_flock(tmp_path: Path) -> None:
    if module.fcntl is None:
        pytest.skip("POSIX flock required")
    script = (
        "import sys\n"
        "from llm_loop.memory.archive import ArchiveStore\n"
        "store=ArchiveStore(sys.argv[1], segment_bytes=0)\n"
        "for i in range(6):\n"
        " store.archive('durable-session',role='tool',source='process',"
        "content=f'p{sys.argv[2]}-{i}',tool_call_id=f'tc-{sys.argv[2]}-{i}')\n"
    )
    env = os.environ.copy()
    source_dir = Path(__file__).resolve().parents[2] / "src"
    env["PYTHONPATH"] = str(source_dir) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path), str(i)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for i in range(2)
    ]
    for worker in workers:
        _stdout, stderr = worker.communicate(timeout=18)
        assert worker.returncode == 0, stderr
    records = _entries(_segment(tmp_path))
    assert len(records) == 12
    assert {entry["content"] for entry in records} == {
        f"p{pid}-{i}" for pid in range(2) for i in range(6)
    }
    assert len(_entries(tmp_path / f"{SID}.jsonl.idx")) == 12


def test_cleanup_rewrite_replace_failure_is_fail_open_no_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    for i in range(4):
        store.archive(SID, role="user", source="test", content=f"payload {i}")
    path = _segment(tmp_path)
    before = path.read_bytes()
    original_replace = module.os.replace

    def fail_primary(source: Path, dest: Path) -> None:
        if Path(dest) == path:
            raise OSError("cannot replace primary")
        original_replace(source, dest)

    with monkeypatch.context() as m:
        m.setattr(module.os, "replace", fail_primary)
        report = store.cleanup(max_entries=2)
    assert report["pruned_entries"] == report["pruned_files"] == 0
    assert path.read_bytes() == before


def test_cleanup_and_new_append_do_not_race_on_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    stores = [_store(tmp_path), _store(tmp_path)]
    for i in range(4):
        stores[0].archive(SID, role="tool", source="test", content=f"old-{i}")
    path = _segment(tmp_path)
    entered = threading.Event()
    allow = threading.Event()
    append_done = threading.Event()
    replacement = module._atomic_replace_bytes

    def gated(dest: Path, payload: bytes, *, operation: str) -> None:
        if dest == path and operation == "cleanup_rewrite":
            entered.set()
            assert allow.wait(timeout=4)
        return replacement(dest, payload, operation=operation)

    monkeypatch.setattr(module, "_atomic_replace_bytes", gated)
    reports: list[dict] = []
    retained: list[str] = []
    cleaner = threading.Thread(target=lambda: reports.append(stores[0].cleanup(max_entries=2)))
    cleaner.start()
    assert entered.wait(timeout=4)

    def newer_append() -> None:
        retained.append(stores[1].archive(SID, role="tool", source="test", content="newer").id)
        append_done.set()

    writer = threading.Thread(target=newer_append)
    writer.start()
    assert not append_done.wait(timeout=0.2)
    allow.set()
    cleaner.join(timeout=4)
    writer.join(timeout=4)
    assert not cleaner.is_alive() and not writer.is_alive()
    assert reports[0]["pruned_entries"] == 2
    rows = _entries(path)
    assert len(rows) == 3
    assert any(row["id"] == retained[0] for row in rows)
    assert any(row["content"] == "old-3" for row in rows)


def test_file_lock_failure_is_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if module.fcntl is None:
        pytest.skip("POSIX flock required")
    store = _store(tmp_path)

    def fail_lock(_fd: int, _op: int) -> None:
        raise OSError("simulated lock denial")

    with monkeypatch.context() as m:
        m.setattr(module.fcntl, "flock", fail_lock)
        with pytest.raises(ArchivePersistError, match="lock unavailable"):
            store.archive(SID, role="user", source="test", content="not written")
    assert not _segment(tmp_path).exists()


def test_delete_session_serialized_and_removes_primary_and_index(tmp_path: Path) -> None:
    stores = [_store(tmp_path), _store(tmp_path)]
    stores[0].archive(SID, role="user", source="test", content="delete once")
    assert stores[1].delete_session(SID) == 2
    assert not _segment(tmp_path).exists()
    assert not stores[0]._index_path(_segment(tmp_path)).exists()


def test_summary_rewrite_preserves_reasoning_and_rebuilds_sidecar(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.archive(
        SID, role="assistant", source="test", content="source original",
        reasoning_content="reasoning original",
    )
    assert store.update_summary(first.id, "new summary marker", "llm") is True
    original = _entries(_segment(tmp_path))[0]
    assert original["content"] == "source original"
    assert original["reasoning_content"] == "reasoning original"
    idx = _entries(store._index_path(_segment(tmp_path)))
    assert idx[0]["summary"] == "new summary marker"
    assert store.search(SID, "new summary marker")[0]["id"] == first.id
