"""P2-2 fail-open 数据丢失恢复通道单元测试（tasks 9.1-9.9）.

覆盖：重试编排、备份归档模型、备份存储、恢复通道编排、恢复工具逻辑、architecture_status recovery 维度。
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

from llm_loop.recovery.backup import BackupArchive, BackupStore
from llm_loop.recovery.channel import RecoveryChannel
from llm_loop.recovery.policy import RetryPolicy
from llm_loop.recovery.retry import retry_write

# ── 9.1 retry_write 单测 ──


class TestRetryWrite:
    def test_first_attempt_success(self):
        """首次写入成功 → attempts=1，不重试."""
        calls = 0

        def write_fn():
            nonlocal calls
            calls += 1

        result = retry_write(write_fn)
        assert result.success is True
        assert result.attempts == 1
        assert result.final_error is None
        assert calls == 1

    def test_retry_succeeds_on_later_attempt(self):
        """重试在某次成功 → success=True."""
        calls = 0

        def write_fn():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise OSError("disk busy")

        result = retry_write(write_fn)
        assert result.success is True
        assert result.attempts == 3
        assert calls == 3

    def test_retry_exhausted(self):
        """重试达 MAX_RETRIES 上限仍失败 → success=False, attempts=4（含首次）."""
        calls = 0

        def write_fn():
            nonlocal calls
            calls += 1
            raise OSError("disk full")

        result = retry_write(write_fn)
        assert result.success is False
        assert result.attempts == RetryPolicy.MAX_RETRIES + 1
        assert result.final_error is not None
        assert "OSError" in result.final_error

    def test_retry_interval(self):
        """重试间隔 RETRY_INTERVAL_S."""
        timestamps = []

        def write_fn():
            timestamps.append(time.monotonic())
            raise OSError("fail")

        retry_write(write_fn)
        if len(timestamps) >= 2:
            gap = timestamps[1] - timestamps[0]
            assert gap >= RetryPolicy.RETRY_INTERVAL_S * 0.8  # 容许调度抖动

    def test_no_infinite_retry(self):
        """不无限重试 → 次数上限 + 总耗时上限双重保障."""
        calls = 0

        def write_fn():
            nonlocal calls
            calls += 1
            raise OSError("forever")

        result = retry_write(write_fn)
        assert calls <= RetryPolicy.MAX_RETRIES + 1
        assert result.elapsed_s <= RetryPolicy.RETRY_TOTAL_TIMEOUT_S + RetryPolicy.RETRY_INTERVAL_S


# ── 9.2 BackupArchive 序列化/解析往返单测 ──


class TestBackupArchive:
    def test_to_dict_from_dict_roundtrip(self):
        """to_dict → from_dict 往返还原一致."""
        archive = BackupArchive(
            source_id="abc123",
            backup_at="2026-08-13T10:30:00+08:00",
            target_type="session",
            payload='{"key": "value"}',
            retry_count=3,
            trigger_point="loop_end_save",
            recovered=False,
        )
        d = archive.to_dict()
        restored = BackupArchive.from_dict(d)
        assert restored.source_id == archive.source_id
        assert restored.backup_at == archive.backup_at
        assert restored.target_type == archive.target_type
        assert restored.payload == archive.payload
        assert restored.retry_count == archive.retry_count
        assert restored.trigger_point == archive.trigger_point
        assert restored.recovered == archive.recovered

    def test_backup_id_format(self):
        """backup_id 属性生成正确文件名格式."""
        archive = BackupArchive(
            source_id="abc123",
            backup_at="2026-08-13T10:30:00+08:00",
            target_type="session",
            payload="{}",
            retry_count=1,
            trigger_point="initial_save",
        )
        assert archive.backup_id == "abc123.20260813103000.session.pending.json"

    def test_payload_original_storage(self):
        """payload 原文存储不改写."""
        original = '{"messages": ["hello", "world"], "nested": {"a": 1}}'
        archive = BackupArchive(
            source_id="s1",
            backup_at="2026-08-13T10:30:00+08:00",
            target_type="memory_stats",
            payload=original,
            retry_count=2,
            trigger_point="memory_flush",
        )
        assert archive.payload == original
        assert archive.to_dict()["payload"] == original


# ── 9.3 BackupStore.save_archive 单测 ──


class TestBackupStoreSave:
    def test_sanitize_source_id_path_traversal(self):
        """source_id 含路径穿越 → sanitize 为安全文件名."""
        assert BackupStore.sanitize_source_id("../etc/passwd") == "etc-passwd"
        assert BackupStore.sanitize_source_id("/absolute/path") == "absolute-path"
        assert BackupStore.sanitize_source_id("../../../secret") == "secret"

    def test_sanitize_source_id_kebab_case(self):
        """source_id kebab-case + 截断."""
        assert BackupStore.sanitize_source_id("session 123") == "session-123"
        assert BackupStore.sanitize_source_id("a" * 200) == "a" * 128

    def test_save_archive_writes_file(self, tmp_path):
        """save_archive 写入文件，文件名含 source_id+时间戳+类型."""
        store = BackupStore(tmp_path / ".recovery")
        archive = BackupArchive(
            source_id="abc123",
            backup_at="2026-08-13T10:30:00+08:00",
            target_type="session",
            payload='{"data": 1}',
            retry_count=1,
            trigger_point="initial_save",
        )
        backup_id = store.save_archive(archive)
        assert backup_id == "abc123.20260813103000.session.pending.json"
        assert (tmp_path / ".recovery" / backup_id).exists()

    def test_save_archive_payload_original(self, tmp_path):
        """payload 原文落盘不被改写."""
        store = BackupStore(tmp_path / ".recovery")
        original_payload = '{"original": true, "data": [1, 2, 3]}'
        archive = BackupArchive(
            source_id="s1",
            backup_at="2026-08-13T10:30:00+08:00",
            target_type="session",
            payload=original_payload,
            retry_count=1,
            trigger_point="initial_save",
        )
        backup_id = store.save_archive(archive)
        data = json.loads((tmp_path / ".recovery" / backup_id).read_text("utf-8"))
        assert data["payload"] == original_payload

    def test_save_archive_creates_dir(self, tmp_path):
        """recovery_dir 不存在时 save_archive 自动创建目录."""
        recovery_dir = tmp_path / "nonexistent" / ".recovery"
        store = BackupStore(recovery_dir)
        archive = BackupArchive(
            source_id="s1",
            backup_at="2026-08-13T10:30:00+08:00",
            target_type="session",
            payload="{}",
            retry_count=1,
            trigger_point="initial_save",
        )
        backup_id = store.save_archive(archive)
        assert (recovery_dir / backup_id).exists()


# ── 9.4 BackupStore.list_pending/status_summary 单测 ──


class TestBackupStoreListStatus:
    def test_list_pending_dir_not_exists(self, tmp_path):
        """recovery_dir 不存在 → list_pending 返回空."""
        store = BackupStore(tmp_path / "nonexistent")
        assert store.list_pending() == []

    def test_status_summary_dir_not_exists(self, tmp_path):
        """recovery_dir 不存在 → status_summary 返回 pending_count=0."""
        store = BackupStore(tmp_path / "nonexistent")
        summary = store.status_summary()
        assert summary["pending_count"] == 0
        assert summary["oldest_backup_at"] is None

    def test_list_pending_only_unrecovered(self, tmp_path):
        """list_pending 仅返回 recovered=False 的待恢复备份."""
        store = BackupStore(tmp_path / ".recovery")
        for i in range(3):
            archive = BackupArchive(
                source_id="s1",
                backup_at=f"2026-08-13T10:30:0{i}+08:00",
                target_type="session",
                payload="{}",
                retry_count=1,
                trigger_point="initial_save",
                recovered=(i == 0),
            )
            store.save_archive(archive)
        pending = store.list_pending()
        assert len(pending) == 2
        assert all(not a.recovered for a in pending)

    def test_list_pending_sorted_by_time(self, tmp_path):
        """list_pending 按 backup_at 排序."""
        store = BackupStore(tmp_path / ".recovery")
        for ts in ["2026-08-13T10:30:02+08:00", "2026-08-13T10:30:00+08:00", "2026-08-13T10:30:01+08:00"]:
            archive = BackupArchive(
                source_id="s1",
                backup_at=ts,
                target_type="session",
                payload="{}",
                retry_count=1,
                trigger_point="initial_save",
            )
            store.save_archive(archive)
        pending = store.list_pending()
        assert pending[0].backup_at < pending[1].backup_at < pending[2].backup_at

    def test_status_summary_by_type(self, tmp_path):
        """status_summary 如实返回数量/时间/类型."""
        store = BackupStore(tmp_path / ".recovery")
        timestamps = ["2026-08-13T10:30:00+08:00", "2026-08-13T10:30:01+08:00", "2026-08-13T10:30:02+08:00"]
        for i, target_type in enumerate(["session", "memory_stats", "session"]):
            archive = BackupArchive(
                source_id="s1" if target_type == "session" else "memory",
                backup_at=timestamps[i],
                target_type=target_type,
                payload="{}",
                retry_count=1,
                trigger_point="initial_save",
            )
            store.save_archive(archive)
        summary = store.status_summary()
        assert summary["pending_count"] == 3
        assert summary["by_type"]["session"] == 2
        assert summary["by_type"]["memory_stats"] == 1

    def test_get_archive_corrupt_file(self, tmp_path):
        """备份文件损坏 → get_archive 返回 None."""
        store = BackupStore(tmp_path / ".recovery")
        (tmp_path / ".recovery").mkdir(parents=True)
        (tmp_path / ".recovery" / "bad.pending.json").write_text("not json", "utf-8")
        assert store.get_archive("bad.pending.json") is None


# ── 9.5 BackupStore.cleanup 单测 ──


class TestBackupStoreCleanup:
    def test_cleanup_over_retention(self, tmp_path):
        """备份超保留期 >7 天 → 清理最旧备份."""
        store = BackupStore(tmp_path / ".recovery")
        old_time = datetime.now().astimezone() - timedelta(days=10)
        archive = BackupArchive(
            source_id="s1",
            backup_at=old_time.isoformat(),
            target_type="session",
            payload="{}",
            retry_count=1,
            trigger_point="initial_save",
        )
        store.save_archive(archive)
        result = store.cleanup()
        assert result["pruned"] >= 1
        assert store.list_pending() == []

    def test_cleanup_over_quantity(self, tmp_path):
        """同对象备份数 >5 → 清理最旧至 5 份."""
        store = BackupStore(tmp_path / ".recovery")
        for i in range(7):
            archive = BackupArchive(
                source_id="s1",
                backup_at=f"2026-08-0{i+1}T10:30:00+08:00",
                target_type="session",
                payload="{}",
                retry_count=1,
                trigger_point="initial_save",
            )
            store.save_archive(archive)
        result = store.cleanup()
        assert result["pruned"] >= 2
        assert len(store.list_pending()) <= RetryPolicy.MAX_PER_TARGET

    def test_cleanup_empty_dir(self, tmp_path):
        """空目录 cleanup 返回 pruned=0."""
        store = BackupStore(tmp_path / ".recovery")
        result = store.cleanup()
        assert result["pruned"] == 0


# ── 9.6 RecoveryChannel.persist_with_recovery 单测 ──


class TestPersistWithRecovery:
    def test_retry_success_no_backup(self, tmp_path):
        """重试成功 → status='retried_ok'，不备份."""
        store = BackupStore(tmp_path / ".recovery")
        channel = RecoveryChannel(backup_store=store)

        def write_fn():
            pass

        receipt = channel.persist_with_recovery(
            target_type="session",
            source_id="s1",
            write_fn=write_fn,
            payload="{}",
            trigger_point="initial_save",
        )
        assert receipt.status == "retried_ok"
        assert receipt.backup_id is None
        assert store.list_pending() == []

    def test_retry_exhausted_backup_success(self, tmp_path):
        """重试耗尽 + 备份成功 → status='backed_up'."""
        store = BackupStore(tmp_path / ".recovery")
        channel = RecoveryChannel(backup_store=store)

        def write_fn():
            raise OSError("disk full")

        receipt = channel.persist_with_recovery(
            target_type="session",
            source_id="s1",
            write_fn=write_fn,
            payload='{"data": 1}',
            trigger_point="loop_end_save",
        )
        assert receipt.status == "backed_up"
        assert receipt.backup_id is not None
        assert len(store.list_pending()) == 1

    def test_backup_failed_no_throw(self, tmp_path):
        """重试耗尽 + 备份失败 → status='backup_failed'，不二次抛穿."""
        store = BackupStore(tmp_path / ".recovery")

        def write_fn():
            raise OSError("disk full")

        channel = RecoveryChannel(backup_store=store)

        # Mock save_archive to fail
        original_save = store.save_archive
        store.save_archive = lambda archive: (_ for _ in ()).throw(OSError("backup disk full"))

        receipt = channel.persist_with_recovery(
            target_type="session",
            source_id="s1",
            write_fn=write_fn,
            payload="{}",
            trigger_point="initial_save",
        )
        assert receipt.status == "backup_failed"
        assert receipt.error is not None
        store.save_archive = original_save

    def test_payload_original_backup(self, tmp_path):
        """payload 原文备份不改写."""
        store = BackupStore(tmp_path / ".recovery")
        channel = RecoveryChannel(backup_store=store)
        original = '{"original": true}'

        def write_fn():
            raise OSError("fail")

        receipt = channel.persist_with_recovery(
            target_type="session",
            source_id="s1",
            write_fn=write_fn,
            payload=original,
            trigger_point="initial_save",
        )
        archive = store.get_archive(receipt.backup_id)
        assert archive.payload == original


# ── 9.7 RecoveryChannel.recover 单测 ──


class TestRecoveryChannelRecover:
    def _make_backup(self, store, source_id="s1", target_type="session", payload='{"data": 1}'):
        archive = BackupArchive(
            source_id=source_id,
            backup_at="2026-08-13T10:30:00+08:00",
            target_type=target_type,
            payload=payload,
            retry_count=1,
            trigger_point="initial_save",
        )
        return store.save_archive(archive)

    def test_recover_success(self, tmp_path):
        """恢复成功 → status='recovered' + mark_recovered."""
        store = BackupStore(tmp_path / ".recovery")
        channel = RecoveryChannel(backup_store=store)
        backup_id = self._make_backup(store)

        written = []

        def target_write_fn(payload):
            written.append(payload)

        result = channel.recover(
            backup_id=backup_id,
            target_write_fn=target_write_fn,
            target_exists_fn=lambda: False,
        )
        assert result.status == "recovered"
        assert len(written) == 1
        archive = store.get_archive(backup_id)
        assert archive.recovered is True

    def test_recover_conflict_abort(self, tmp_path):
        """冲突 abort → status='conflict'，不覆盖."""
        store = BackupStore(tmp_path / ".recovery")
        channel = RecoveryChannel(backup_store=store)
        backup_id = self._make_backup(store)

        written = []

        def target_write_fn(payload):
            written.append(payload)

        result = channel.recover(
            backup_id=backup_id,
            target_write_fn=target_write_fn,
            target_exists_fn=lambda: True,
            on_conflict="abort",
        )
        assert result.status == "conflict"
        assert len(written) == 0

    def test_recover_conflict_overwrite(self, tmp_path):
        """冲突 overwrite → 覆盖."""
        store = BackupStore(tmp_path / ".recovery")
        channel = RecoveryChannel(backup_store=store)
        backup_id = self._make_backup(store)

        written = []

        def target_write_fn(payload):
            written.append(payload)

        result = channel.recover(
            backup_id=backup_id,
            target_write_fn=target_write_fn,
            target_exists_fn=lambda: True,
            on_conflict="overwrite",
        )
        assert result.status == "recovered"
        assert len(written) == 1

    def test_recover_not_found(self, tmp_path):
        """备份不存在 → status='not_found'."""
        store = BackupStore(tmp_path / ".recovery")
        channel = RecoveryChannel(backup_store=store)

        result = channel.recover(
            backup_id="nonexistent.pending.json",
            target_write_fn=lambda p: None,
            target_exists_fn=lambda: False,
        )
        assert result.status == "not_found"

    def test_recover_write_failed(self, tmp_path):
        """恢复写入失败 → status='failed'，保留备份."""
        store = BackupStore(tmp_path / ".recovery")
        channel = RecoveryChannel(backup_store=store)
        backup_id = self._make_backup(store)

        def target_write_fn(payload):
            raise OSError("write fail")

        result = channel.recover(
            backup_id=backup_id,
            target_write_fn=target_write_fn,
            target_exists_fn=lambda: False,
        )
        assert result.status == "failed"
        archive = store.get_archive(backup_id)
        assert archive is not None
        assert archive.recovered is False


# ── 9.8 run_recover_from_backup 单测 ──


class TestRunRecoverFromBackup:
    def test_missing_backup_id(self, tmp_path):
        """backup_id 缺失 → [参数错误]."""
        from llm_loop.introspection.tools_recovery import run_recover_from_backup

        store = BackupStore(tmp_path / ".recovery")
        channel = RecoveryChannel(backup_store=store)
        result = run_recover_from_backup(channel, backup_id="")
        assert result.startswith("[参数错误]")

    def test_invalid_on_conflict(self, tmp_path):
        """on_conflict 非法 → [参数错误]."""
        from llm_loop.introspection.tools_recovery import run_recover_from_backup

        store = BackupStore(tmp_path / ".recovery")
        channel = RecoveryChannel(backup_store=store)
        result = run_recover_from_backup(
            channel, backup_id="s1.20260813103000.session.pending.json", on_conflict="bad"
        )
        assert result.startswith("[参数错误]")

    def test_recover_success(self, tmp_path):
        """恢复成功回执."""
        from llm_loop.introspection.tools_recovery import run_recover_from_backup

        store = BackupStore(tmp_path / ".recovery")
        channel = RecoveryChannel(backup_store=store)
        archive = BackupArchive(
            source_id="s1",
            backup_at="2026-08-13T10:30:00+08:00",
            target_type="session",
            payload='{"data": 1}',
            retry_count=1,
            trigger_point="initial_save",
        )
        backup_id = store.save_archive(archive)
        result = run_recover_from_backup(
            channel,
            backup_id=backup_id,
            sessions_dir=tmp_path / "sessions",
        )
        assert result.startswith("[recover_from_backup]")
        assert (tmp_path / "sessions" / "s1.json").exists()

    def test_recover_not_found(self, tmp_path):
        """备份不存在 → [未找到]."""
        from llm_loop.introspection.tools_recovery import run_recover_from_backup

        store = BackupStore(tmp_path / ".recovery")
        channel = RecoveryChannel(backup_store=store)
        result = run_recover_from_backup(
            channel,
            backup_id="nonexistent.20260813103000.session.pending.json",
            sessions_dir=tmp_path / "sessions",
        )
        assert result.startswith("[未找到]")

    def test_recover_conflict_abort(self, tmp_path):
        """冲突 abort → 冲突回执."""
        from llm_loop.introspection.tools_recovery import run_recover_from_backup

        store = BackupStore(tmp_path / ".recovery")
        channel = RecoveryChannel(backup_store=store)
        archive = BackupArchive(
            source_id="s1",
            backup_at="2026-08-13T10:30:00+08:00",
            target_type="session",
            payload='{"data": 1}',
            retry_count=1,
            trigger_point="initial_save",
        )
        backup_id = store.save_archive(archive)
        # 正式位置已有数据
        (tmp_path / "sessions").mkdir(parents=True)
        (tmp_path / "sessions" / "s1.json").write_text('{"existing": true}', "utf-8")
        result = run_recover_from_backup(
            channel,
            backup_id=backup_id,
            sessions_dir=tmp_path / "sessions",
        )
        assert "冲突" in result


# ── 9.9 architecture_status.recovery 维度单测 ──


class TestArchitectureStatusRecovery:
    def test_recovery_dimension_not_injected(self):
        """未注入 _recovery_status_fn → {"note": "数据源未注入"}."""
        from llm_loop.introspection.status import ArchitectureStatusProvider

        provider = ArchitectureStatusProvider()
        snapshot = provider.snapshot()
        assert snapshot["recovery"] == {"note": "数据源未注入"}

    def test_recovery_dimension_injected(self, tmp_path):
        """已注入 → 返回如实备份状态."""
        from llm_loop.introspection.status import ArchitectureStatusProvider

        store = BackupStore(tmp_path / ".recovery")
        archive = BackupArchive(
            source_id="s1",
            backup_at="2026-08-13T10:30:00+08:00",
            target_type="session",
            payload="{}",
            retry_count=1,
            trigger_point="initial_save",
        )
        store.save_archive(archive)

        provider = ArchitectureStatusProvider()
        provider.set_recovery_status_fn(store.status_summary)
        snapshot = provider.snapshot()
        assert snapshot["recovery"]["pending_count"] == 1
        assert snapshot["recovery"]["by_type"]["session"] == 1

    def test_recovery_dimension_empty(self, tmp_path):
        """无备份 → pending_count=0, oldest_backup_at=None."""
        from llm_loop.introspection.status import ArchitectureStatusProvider

        store = BackupStore(tmp_path / ".recovery")
        provider = ArchitectureStatusProvider()
        provider.set_recovery_status_fn(store.status_summary)
        snapshot = provider.snapshot()
        assert snapshot["recovery"]["pending_count"] == 0
        assert snapshot["recovery"]["oldest_backup_at"] is None

    def test_existing_dimensions_unaffected(self):
        """既有维度不受新维度影响."""
        from llm_loop.introspection.status import ArchitectureStatusProvider

        provider = ArchitectureStatusProvider()
        snapshot = provider.snapshot()
        assert "current_phase" in snapshot
        assert "action_trace" in snapshot
        assert "pending_actions" in snapshot
        assert "recovery" in snapshot
