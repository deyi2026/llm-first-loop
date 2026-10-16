"""BackupStore durability fault-injection 资格化测试（DRC T2，Fleet 批次1，2026-10-08）.

验收口径（docs/DESIGN-20261007-durable-run-contract.md rev9）：
- 原子可见性：最终文件只可能整体旧或整体新，无撕裂中间态；
- file fsync + directory fsync（目录 fsync 有界重试，耗尽→typed uncertain）；
- 失败分型：definitely_not_committed（BackupPersistError / FileExistsError）与
  commit_outcome_uncertain（BackupCommitUncertainError，含 backup_id/expected_sha256/
  visible_state readback 字段）明确区分；
- uncertain 后禁止盲重放：先 readback reconcile（同 payload 幂等）；
- 并发/锁语义：store flock 单写者，同 backup_id 并发保存恰一胜者，并发 mark 不撕裂；
- 孤儿 tmp 与锁文件不入 *.pending.json 扫描面。
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path

import pytest

import llm_loop.recovery.backup as backup_module
from llm_loop.recovery.backup import (
    BackupArchive,
    BackupCommitUncertainError,
    BackupPersistError,
    BackupStore,
)

BACKUP_AT = "2026-10-08T10:00:00"


def make_archive(**overrides) -> BackupArchive:
    fields = {
        "source_id": "sess-durability",
        "backup_at": BACKUP_AT,
        "target_type": "session",
        "payload": '{"state": "alpha"}',
        "retry_count": 0,
        "trigger_point": "initial_save",
    }
    fields.update(overrides)
    return BackupArchive(**fields)


def archive_content(archive: BackupArchive) -> str:
    return json.dumps(archive.to_dict(), ensure_ascii=False, indent=2)


def tmp_residue(store_dir: Path) -> list[str]:
    return [p.name for p in store_dir.glob("*.tmp")]


# ---------------------------------------------------------------- happy path

def test_save_happy_path_atomic_and_readable(tmp_path):
    store = BackupStore(tmp_path)
    archive = make_archive()
    backup_id = store.save_archive(archive)

    path = tmp_path / backup_id
    assert path.read_text(encoding="utf-8") == archive_content(archive)
    assert store.get_archive(backup_id) == archive
    assert tmp_residue(tmp_path) == []
    assert [a.backup_id for a in store.list_pending()] == [backup_id]


def test_save_idempotent_same_payload_no_second_write(tmp_path):
    store = BackupStore(tmp_path)
    archive = make_archive()
    backup_id = store.save_archive(archive)
    first_mtime_ns = (tmp_path / backup_id).stat().st_mtime_ns

    assert store.save_archive(archive) == backup_id

    # 幂等路径不产生第二次写入：mtime 不变、仍只有一个数据文件
    assert (tmp_path / backup_id).stat().st_mtime_ns == first_mtime_ns
    assert len([p for p in tmp_path.iterdir() if p.name.endswith(".pending.json")]) == 1


def test_save_conflict_never_overwrites_first_backup_wins(tmp_path):
    store = BackupStore(tmp_path)
    first = make_archive(payload='{"state": "first"}')
    backup_id = store.save_archive(first)

    second = make_archive(payload='{"state": "second"}')
    with pytest.raises(FileExistsError) as excinfo:
        store.save_archive(second)
    assert "拒绝覆盖" in str(excinfo.value)
    assert not isinstance(excinfo.value, BackupPersistError)

    # 先到的备份保真
    assert json.loads((tmp_path / backup_id).read_text(encoding="utf-8"))["payload"] == '{"state": "first"}'
    assert tmp_residue(tmp_path) == []


# ------------------------------------------------------- definitely_not_committed

def test_save_definitely_not_committed_before_link_no_residue_retryable(tmp_path, monkeypatch):
    store = BackupStore(tmp_path)
    archive = make_archive()
    backup_id = archive.backup_id

    def boom_link(src, dst, **kwargs):
        raise OSError("simulated link failure")

    monkeypatch.setattr(backup_module.os, "link", boom_link)
    with pytest.raises(BackupPersistError):
        store.save_archive(archive)

    # 确定未提交：无目标文件、无 tmp 残留、锁文件之外目录无变化
    assert not (tmp_path / backup_id).exists()
    assert tmp_residue(tmp_path) == []
    monkeypatch.undo()

    # 同一 payload 重试安全（DRC：definitely_not_committed 可重试）
    assert store.save_archive(archive) == backup_id
    assert store.get_archive(backup_id) == archive


def test_mark_recovered_definitely_not_committed_preserves_original(tmp_path, monkeypatch):
    store = BackupStore(tmp_path)
    archive = make_archive()
    backup_id = store.save_archive(archive)
    original = (tmp_path / backup_id).read_text(encoding="utf-8")

    def boom_replace(src, dst, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(backup_module.os, "replace", boom_replace)
    assert store.mark_recovered(backup_id) is False

    # 原文件逐字节保真，无 tmp 残留
    assert (tmp_path / backup_id).read_text(encoding="utf-8") == original
    assert tmp_residue(tmp_path) == []
    monkeypatch.undo()

    # bool 契约下语义动作幂等，重试成功
    assert store.mark_recovered(backup_id) is True
    assert store.get_archive(backup_id).recovered is True


# --------------------------------------------------------- commit_outcome_uncertain

def test_save_uncertain_after_link_typed_fields_and_reconcile(tmp_path, monkeypatch):
    store = BackupStore(tmp_path)
    archive = make_archive()
    backup_id = archive.backup_id
    expected = archive_content(archive)

    calls = {"n": 0}

    def boom_dir_fsync(directory):
        calls["n"] += 1
        raise OSError("simulated dir fsync failure")

    monkeypatch.setattr(backup_module, "_fsync_directory", boom_dir_fsync)
    with pytest.raises(BackupCommitUncertainError) as excinfo:
        store.save_archive(archive)

    err = excinfo.value
    assert err.backup_id == backup_id
    assert err.expected_sha256 == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert err.visible_state == "matches"
    assert calls["n"] == backup_module._DIR_FSYNC_ATTEMPTS

    # link 已生效：文件原子完整可见，无 tmp 残留
    assert (tmp_path / backup_id).read_text(encoding="utf-8") == expected
    assert tmp_residue(tmp_path) == []

    # uncertain 后禁止盲重放：同 payload 再保存走 readback reconcile，幂等成功
    assert store.save_archive(archive) == backup_id
    assert len([p for p in tmp_path.iterdir() if p.name.endswith(".pending.json")]) == 1


def test_mark_recovered_uncertain_readback_reconciles_true(tmp_path, monkeypatch):
    store = BackupStore(tmp_path)
    archive = make_archive()
    backup_id = store.save_archive(archive)

    def boom_dir_fsync(directory):
        raise OSError("simulated dir fsync failure")

    monkeypatch.setattr(backup_module, "_fsync_directory", boom_dir_fsync)
    assert store.mark_recovered(backup_id) is True  # readback 匹配 → 已提交

    data = json.loads((tmp_path / backup_id).read_text(encoding="utf-8"))
    assert data["recovered"] is True
    assert store.list_pending() == []
    assert tmp_residue(tmp_path) == []


def test_mark_recovered_uncertain_mismatch_returns_false_no_replay(tmp_path, monkeypatch):
    store = BackupStore(tmp_path)
    backup_id = store.save_archive(make_archive())

    def boom_dir_fsync(directory):
        raise OSError("simulated dir fsync failure")

    monkeypatch.setattr(backup_module, "_fsync_directory", boom_dir_fsync)
    monkeypatch.setattr(backup_module, "_visible_state", lambda path, expected: "mismatch")
    assert store.mark_recovered(backup_id) is False  # uncertain 且 readback 不匹配：不盲重放
    assert tmp_residue(tmp_path) == []


# ------------------------------------------------------------------- concurrency

def test_concurrent_save_same_id_exactly_one_winner(tmp_path):
    store_a = BackupStore(tmp_path)
    store_b = BackupStore(tmp_path)  # 双实例模拟双写者（独立对象、共享目录/锁）
    alpha = make_archive(payload='{"state": "alpha"}')
    beta = make_archive(payload='{"state": "beta"}')
    barrier = threading.Barrier(2)
    outcomes: list[object] = []

    def run(store: BackupStore, archive: BackupArchive) -> None:
        barrier.wait()
        try:
            outcomes.append(store.save_archive(archive))
        except FileExistsError as exc:
            outcomes.append(exc)

    threads = [
        threading.Thread(target=run, args=(store_a, alpha)),
        threading.Thread(target=run, args=(store_b, beta)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(outcomes) == 2
    winners = [o for o in outcomes if isinstance(o, str)]
    losers = [o for o in outcomes if isinstance(o, FileExistsError)]
    assert len(winners) == 1 and len(losers) == 1
    assert winners[0] == alpha.backup_id

    files = [p for p in tmp_path.iterdir() if p.name.endswith(".pending.json")]
    assert len(files) == 1
    saved_payload = json.loads(files[0].read_text(encoding="utf-8"))["payload"]
    assert saved_payload in ('{"state": "alpha"}', '{"state": "beta"}')
    assert tmp_residue(tmp_path) == []


def test_concurrent_mark_recovered_no_tearing(tmp_path):
    store = BackupStore(tmp_path)
    backup_id = store.save_archive(make_archive())
    barrier = threading.Barrier(8)
    results: list[bool] = []

    def run() -> None:
        barrier.wait()
        results.append(store.mark_recovered(backup_id))

    threads = [threading.Thread(target=run) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8 and all(results)
    data = json.loads((tmp_path / backup_id).read_text(encoding="utf-8"))  # 完整 JSON，无撕裂
    assert data["recovered"] is True
    assert data["payload"] == '{"state": "alpha"}'
    assert tmp_residue(tmp_path) == []


# ---------------------------------------------------------------- fail-open reads

def test_mark_recovered_missing_or_corrupt_fail_open_untouched(tmp_path):
    store = BackupStore(tmp_path)
    assert store.mark_recovered("missing.20260101000000.session.pending.json") is False

    backup_id = store.save_archive(make_archive())
    path = tmp_path / backup_id
    corrupt = "{not-json"
    path.write_text(corrupt, encoding="utf-8")
    assert store.mark_recovered(backup_id) is False
    assert path.read_text(encoding="utf-8") == corrupt  # 损坏文件原样保留


def test_orphan_tmp_and_lock_invisible_to_scan_surfaces(tmp_path, monkeypatch):
    # This test verifies scan invisibility, not age-based retention.  The
    # archive fixture is dated 2026-10-08 and expires after 7 days; freeze only
    # this cleanup clock to prevent a calendar-dependent false test failure.
    monkeypatch.setattr(
        backup_module, "system_local_now",
        lambda: datetime.fromisoformat("2026-10-09T10:00:00"),
    )
    store = BackupStore(tmp_path)
    # This is a fresh-backup test: do not let the fixed 2026-10-08 fixture
    # silently cross the real seven-day retention boundary over time.
    # （合并注：与前一条已合分支的同位注释同义，取更详版。）
    backup_id = store.save_archive(make_archive(backup_at=backup_module.system_local_now().isoformat()))
    (tmp_path / f"{backup_id}.abcdef123456.tmp").write_text("orphan", encoding="utf-8")

    # 孤儿 tmp 不入扫描面
    assert [a.backup_id for a in store.list_pending()] == [backup_id]
    assert store.status_summary()["pending_count"] == 1
    assert store.cleanup() == {"pruned": 0}
    assert store.delete_source("sess-durability") == 1
    assert len([p for p in tmp_path.iterdir() if p.name.endswith(".pending.json")]) == 0
    # 锁文件仍在（不属于扫描面）
    assert (tmp_path / ".__backup_store.lock").exists()


def test_typed_errors_are_oserror_subclasses_for_fail_open_absorption(tmp_path):
    # channel 侧 except Exception 吸收面契约：typed 异常同为 OSError 子类
    assert issubclass(BackupPersistError, OSError)
    assert issubclass(BackupCommitUncertainError, OSError)
    err = BackupCommitUncertainError(
        "msg", backup_id="b", expected_sha256="0" * 64, visible_state="matches"
    )
    assert (err.backup_id, err.expected_sha256, err.visible_state) == ("b", "0" * 64, "matches")
