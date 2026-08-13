"""P2-2 fail-open 数据丢失恢复通道集成测试（tasks 10.1-10.4）.

覆盖：端到端写失败→重试→备份→恢复流程、fail-open 全失败路径、零回归、既有标注格式语义不变。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from llm_loop.recovery.backup import BackupStore
from llm_loop.recovery.channel import RecoveryChannel


@pytest.fixture
def recovery_setup(isolated_data_dir):
    """构造 BackupStore + RecoveryChannel（测试用）."""
    recovery_dir = isolated_data_dir / ".recovery"
    backup_store = BackupStore(recovery_dir)
    channel = RecoveryChannel(backup_store=backup_store)
    return backup_store, channel, recovery_dir


# ── 10.1 engine 三个 fail-open 写失败点端到端集成测 ──


class TestEngineFailOpenRecovery:
    def test_loop_end_save_failure_triggers_recovery(self, build_test_engine, recovery_setup):
        """轮末会话保存抛异常 → 触发 persist_with_recovery，重试+备份."""
        backup_store, channel, _ = recovery_setup
        engine, fake = build_test_engine([{"content": "test answer"}])
        engine.recovery = channel

        # 第一次 save 成功（初始保存），第二次 save 失败（轮末保存）
        original_save = engine.session.save
        call_count = 0

        def failing_save(sess):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                original_save(sess)
            else:
                raise OSError("disk full on loop end")

        with patch.object(engine.session, "save", side_effect=failing_save):
            result = engine.run("test-session", "hello")

        assert "test answer" in result.final_answer
        assert "[程序异常]" in result.final_answer
        pending = backup_store.list_pending()
        assert len(pending) >= 1
        assert pending[0].target_type == "session"

    def test_initial_save_failure_triggers_recovery(self, build_test_engine, recovery_setup):
        """初始会话保存抛异常 → 触发 persist_with_recovery."""
        backup_store, channel, _ = recovery_setup
        engine, fake = build_test_engine([{"content": "test answer"}])
        engine.recovery = channel

        with patch.object(engine.session, "save", side_effect=OSError("disk full")):
            result = engine.run("test-session", "hello")

        assert "test answer" in result.final_answer
        pending = backup_store.list_pending()
        assert len(pending) >= 1

    def test_memory_flush_failure_triggers_recovery(self, build_test_engine, recovery_setup):
        """记忆统计落盘抛异常 → 触发 persist_with_recovery."""
        backup_store, channel, _ = recovery_setup
        engine, fake = build_test_engine([{"content": "test answer"}])
        engine.recovery = channel

        with patch.object(engine.memory, "flush", side_effect=OSError("memory disk full")):
            result = engine.run("test-session", "hello")

        assert "test answer" in result.final_answer
        pending = backup_store.list_pending(target_type="memory_stats")
        assert len(pending) >= 1

    def test_main_loop_continues_on_all_failure(self, build_test_engine, recovery_setup):
        """重试+备份全失败 → 仍 fail-open，主循环继续，回答仍输出."""
        _, channel, _ = recovery_setup
        engine, fake = build_test_engine([{"content": "final answer"}])
        engine.recovery = channel

        # save 和 backup 都失败
        with (
            patch.object(engine.session, "save", side_effect=OSError("disk full")),
            patch.object(BackupStore, "save_archive", side_effect=OSError("backup disk full")),
        ):
            result = engine.run("test-session", "hello")

        assert "final answer" in result.final_answer


# ── 10.2 recover_from_backup → 正式位置恢复端到端集成测 ──


class TestRecoverFromBackupEndToEnd:
    def test_recover_session_backup(self, build_test_engine, recovery_setup):
        """写失败产生备份 → recover_from_backup 恢复 → 正式位置已写入."""
        backup_store, channel, recovery_dir = recovery_setup
        engine, fake = build_test_engine([{"content": "test answer"}])
        engine.recovery = channel

        # 触发写失败产生备份
        with patch.object(engine.session, "save", side_effect=OSError("disk full")):
            engine.run("test-session", "hello")

        pending = backup_store.list_pending()
        assert len(pending) >= 1
        backup_id = pending[0].backup_id

        # AI 触发恢复
        from llm_loop.introspection.tools_recovery import run_recover_from_backup

        result = run_recover_from_backup(
            channel,
            backup_id=backup_id,
            sessions_dir=engine.settings.sessions_dir,
        )
        assert result.startswith("[recover_from_backup]")

        # 验证正式位置已写入
        archive = backup_store.get_archive(backup_id)
        assert archive.recovered is True

    def test_recover_conflict_abort(self, build_test_engine, recovery_setup):
        """冲突 abort → 不覆盖，决策归 AI."""
        backup_store, channel, _ = recovery_setup
        engine, fake = build_test_engine([{"content": "test answer"}])
        engine.recovery = channel

        with patch.object(engine.session, "save", side_effect=OSError("disk full")):
            engine.run("test-session", "hello")

        pending = backup_store.list_pending()
        backup_id = pending[0].backup_id

        # 正式位置已有数据
        sessions_dir = engine.settings.sessions_dir
        sessions_dir.mkdir(parents=True, exist_ok=True)
        source_id = pending[0].source_id
        (sessions_dir / f"{source_id}.json").write_text('{"existing": true}', "utf-8")

        from llm_loop.introspection.tools_recovery import run_recover_from_backup

        result = run_recover_from_backup(
            channel,
            backup_id=backup_id,
            sessions_dir=sessions_dir,
        )
        assert "冲突" in result

    def test_recover_conflict_overwrite(self, build_test_engine, recovery_setup):
        """冲突 overwrite → 覆盖，AI 显式决策."""
        backup_store, channel, _ = recovery_setup
        engine, fake = build_test_engine([{"content": "test answer"}])
        engine.recovery = channel

        with patch.object(engine.session, "save", side_effect=OSError("disk full")):
            engine.run("test-session", "hello")

        pending = backup_store.list_pending()
        backup_id = pending[0].backup_id

        sessions_dir = engine.settings.sessions_dir
        sessions_dir.mkdir(parents=True, exist_ok=True)
        source_id = pending[0].source_id
        (sessions_dir / f"{source_id}.json").write_text('{"existing": true}', "utf-8")

        from llm_loop.introspection.tools_recovery import run_recover_from_backup

        result = run_recover_from_backup(
            channel,
            backup_id=backup_id,
            sessions_dir=sessions_dir,
            on_conflict="overwrite",
        )
        assert result.startswith("[recover_from_backup]")

    def test_no_auto_recovery(self, build_test_engine, recovery_setup):
        """无 AI 主动触发 → 程序不自动恢复."""
        backup_store, channel, _ = recovery_setup
        engine, fake = build_test_engine([{"content": "test answer"}])
        engine.recovery = channel

        with patch.object(engine.session, "save", side_effect=OSError("disk full")):
            engine.run("test-session", "hello")

        pending = backup_store.list_pending()
        assert len(pending) >= 1
        # 备份仍处于 pending 状态（未自动恢复）
        assert all(not a.recovered for a in pending)


# ── 10.3 data/.recovery/ 目录不存在零回归集成测 ──


class TestRecoveryDirNotExists:
    def test_engine_works_without_recovery(self, build_test_engine):
        """recovery=None 时 engine 正常工作（零回归）."""
        engine, fake = build_test_engine([{"content": "test answer"}])
        # engine.recovery 默认为 None（build_test_engine 不注入 recovery）

        result = engine.run("test-session", "hello")
        assert "test answer" in result.final_answer

    def test_fail_open_without_recovery(self, build_test_engine):
        """recovery=None 时写失败仍 fail-open（既有行为）."""
        engine, fake = build_test_engine([{"content": "test answer"}])
        assert engine.recovery is None

        with patch.object(engine.session, "save", side_effect=OSError("disk full")):
            result = engine.run("test-session", "hello")

        assert "test answer" in result.final_answer
        assert "[程序异常]" in result.final_answer

    def test_recovery_dimension_zero_when_empty(self, build_test_engine, isolated_data_dir):
        """recovery 目录为空 → architecture_status recovery 维度如实为零."""
        from llm_loop.introspection.status import ArchitectureStatusProvider

        backup_store = BackupStore(isolated_data_dir / ".recovery")
        provider = ArchitectureStatusProvider()
        provider.set_recovery_status_fn(backup_store.status_summary)
        snapshot = provider.snapshot()
        assert snapshot["recovery"]["pending_count"] == 0
        assert snapshot["recovery"]["oldest_backup_at"] is None


# ── 10.4 既有 fail-open 标注格式语义不变集成测 ──


class TestAnnotationFormatUnchanged:
    def test_loop_end_save_annotation_contains_program_exception(self, build_test_engine, recovery_setup):
        """轮末会话保存失败 → [程序异常] 标注格式不变（仅补充重试/备份结果）."""
        _, channel, _ = recovery_setup
        engine, fake = build_test_engine([{"content": "test answer"}])
        engine.recovery = channel

        original_save = engine.session.save
        call_count = 0

        def failing_save(sess):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                original_save(sess)
            else:
                raise OSError("disk full")

        with patch.object(engine.session, "save", side_effect=failing_save):
            result = engine.run("test-session", "hello")

        assert "[程序异常]" in result.final_answer
        assert "会话保存失败" in result.final_answer
        assert "本次回答仍有效" in result.final_answer

    def test_recovery_none_annotation_unchanged(self, build_test_engine):
        """recovery=None 时标注格式与既有完全一致（零回归）."""
        engine, fake = build_test_engine([{"content": "test answer"}])

        original_save = engine.session.save
        call_count = 0

        def failing_save(sess):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                original_save(sess)
            else:
                raise OSError("disk full")

        with patch.object(engine.session, "save", side_effect=failing_save):
            result = engine.run("test-session", "hello")

        assert "[程序异常]" in result.final_answer
        assert "会话保存失败" in result.final_answer
        assert "本次回答仍有效" in result.final_answer
        # 无恢复通道标注
        assert "[恢复通道]" not in result.final_answer
