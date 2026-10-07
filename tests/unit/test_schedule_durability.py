"""DRC T2 首迁 client 验收：ScheduleStore 主状态原子提交的故障注入测试.

对应 DESIGN-20261007-durable-run-contract §6 实施记录：六点打断
（temp 前 / temp 半写 / fsync 后 replace 前 / replace 后 dirfsync 前 /
损坏旧 state 重启 / 重试耗尽与瞬态自愈）+ recover() 自检。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_loop.core import scheduler as sched
from llm_loop.core.scheduler import (
    ScheduleCommitUncertainError,
    SchedulePersistError,
    ScheduleStore,
    rearm_wake_grants,
)
from llm_loop.core.trace_leak.ingress_token import (
    delegate_ingress,
    issue_ingress,
)
from llm_loop.tools.builtin.schedule import ScheduleCancelTool, ScheduleTool


def _seed(path: Path, entries: list) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(entries, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return text


def _entry(sid: str = "old-1", trigger_at: float = 1.0) -> dict:
    return {"sid": sid, "message": "旧提醒", "trigger_at": trigger_at}


def _tmp_files(path: Path) -> list[Path]:
    return sorted(path.parent.glob(path.name + ".*.tmp"))


def _is_target_temp(temp: Path, path: Path) -> bool:
    return (
        temp.parent == path.parent
        and temp.name.startswith(path.name + ".")
        and temp.name.endswith(".tmp")
    )


def test_atomic_commit_normal_path_and_no_tmp_leftover(tmp_path):
    """正常路径：提交后文件为合法 JSON、无 tmp 残留；双实例合并不丢。"""
    path = tmp_path / "schedule.json"
    s1 = ScheduleStore(path)
    sid1 = s1.add("a", after=60)
    s2 = ScheduleStore(path)
    sid2 = s2.add("b", after=60)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert {d["sid"] for d in data} == {sid1, sid2}
    assert _tmp_files(path) == []


def test_fault_before_temp_write_keeps_old_state(tmp_path, monkeypatch):
    """打断点1（写 temp 前）：旧文件逐字不变、无 tmp、显式抛错不吞。"""
    path = tmp_path / "schedule.json"
    old_text = _seed(path, [_entry()])

    original = sched._write_temp_exclusive

    def boom(temp, text):
        if _is_target_temp(temp, path):
            raise OSError(28, "No space left on device")
        return original(temp, text)

    monkeypatch.setattr(sched, "_write_temp_exclusive", boom)
    store = ScheduleStore(path)
    with pytest.raises(SchedulePersistError):
        store.add("new", after=60)
    assert path.read_text(encoding="utf-8") == old_text
    assert _tmp_files(path) == []


def test_fault_mid_temp_torn_write_stays_in_tmp(tmp_path, monkeypatch):
    """打断点2（temp 写一半）：撕裂内容只可能存在于 tmp，且提交失败后被清理。"""
    path = tmp_path / "schedule.json"
    old_text = _seed(path, [_entry()])

    original = sched._write_temp_exclusive

    def torn(temp: Path, text: str):
        if _is_target_temp(temp, path):
            temp.write_text(text[: max(1, len(text) // 2)], encoding="utf-8")
            raise OSError(5, "I/O error mid-write")
        return original(temp, text)

    monkeypatch.setattr(sched, "_write_temp_exclusive", torn)
    store = ScheduleStore(path)
    with pytest.raises(SchedulePersistError):
        store.add("new", after=60)
    assert path.read_text(encoding="utf-8") == old_text
    assert _tmp_files(path) == []


def test_fault_after_fsync_before_replace(tmp_path, monkeypatch):
    """打断点3（file fsync 后、replace 前）：rename 失败 → 旧文件不变。"""
    path = tmp_path / "schedule.json"
    old_text = _seed(path, [_entry()])

    original = sched.os.replace

    def boom(src, dst, *args, **kwargs):
        if Path(dst) == path:
            raise OSError(5, "replace failed")
        return original(src, dst, *args, **kwargs)

    monkeypatch.setattr(sched.os, "replace", boom)
    store = ScheduleStore(path)
    with pytest.raises(SchedulePersistError):
        store.add("new", after=60)
    assert path.read_text(encoding="utf-8") == old_text
    assert _tmp_files(path) == []


def test_fault_after_replace_before_dir_fsync(tmp_path, monkeypatch):
    """打断点4（replace 后、目录 fsync 前）：状态已前进但耐久性未确认 → 显式报错。"""
    path = tmp_path / "schedule.json"
    _seed(path, [_entry()])

    original = sched._fsync_directory

    def boom(directory):
        if Path(directory) == path.parent:
            raise OSError(5, "dir fsync failed")
        return original(directory)

    monkeypatch.setattr(sched, "_fsync_directory", boom)
    store = ScheduleStore(path)
    with pytest.raises(SchedulePersistError):
        store.add("new", after=60)
    data = json.loads(path.read_text(encoding="utf-8"))  # replace 已生效
    assert len(data) == 2
    assert _tmp_files(path) == []


def test_post_replace_fsync_exhaustion_is_uncertain_and_does_not_rewrite(tmp_path, monkeypatch):
    """replace 已发生后只重试 durability fence，不得重复 rename/语义提交."""
    path = tmp_path / "schedule.json"
    _seed(path, [_entry()])
    write_calls: list[Path] = []
    original_write = sched._write_temp_exclusive
    original_fsync = sched._fsync_directory

    def counted_write(temp: Path, text: str):
        if _is_target_temp(temp, path):
            write_calls.append(temp)
        return original_write(temp, text)

    def fail_dir_fsync(directory: Path):
        if Path(directory) == path.parent:
            raise OSError(5, "dir fsync failed")
        return original_fsync(directory)

    monkeypatch.setattr(sched, "_write_temp_exclusive", counted_write)
    monkeypatch.setattr(sched, "_fsync_directory", fail_dir_fsync)
    store = ScheduleStore(path)
    with pytest.raises(ScheduleCommitUncertainError) as caught:
        store.add("new", after=60)
    assert len(write_calls) == 1
    assert caught.value.outcome == "commit_outcome_uncertain"
    assert caught.value.visible_state == "matches"
    assert caught.value.sid.startswith("sched-")
    assert caught.value.retry_safe is False
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 2


def test_corrupt_old_state_restart_recovery(tmp_path, caplog):
    """打断点5（损坏旧 state 后重启）：recover 报告 corrupt，空基底继续，下次提交修复文件。"""
    path = tmp_path / "schedule.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{corrupted json", encoding="utf-8")
    with caplog.at_level("ERROR"):
        store = ScheduleStore(path)
    report = store.recover()
    assert report["exists"] and report["corrupt"] and not report["readable"]
    assert any("自检" in r.getMessage() for r in caplog.records)
    sid = store.add("after-corrupt", after=60)  # 读侧 fail-open：可继续
    data = json.loads(path.read_text(encoding="utf-8"))
    assert [d["sid"] for d in data] == [sid]


def test_retry_exhaustion_counts_attempts(tmp_path, monkeypatch):
    """打断点6（重试耗尽）：恰好 _PERSIST_ATTEMPTS 次后放弃并抛错，不吞。"""
    path = tmp_path / "schedule.json"
    old_text = _seed(path, [_entry()])
    calls = []
    original = sched._write_temp_exclusive

    def boom(temp, text):
        if _is_target_temp(temp, path):
            calls.append(temp)
            raise OSError(28, "persistent failure")
        return original(temp, text)

    monkeypatch.setattr(sched, "_write_temp_exclusive", boom)
    store = ScheduleStore(path)
    with pytest.raises(SchedulePersistError):
        store.add("new", after=60)
    assert len(calls) == sched._PERSIST_ATTEMPTS
    assert path.read_text(encoding="utf-8") == old_text
    assert _tmp_files(path) == []


def test_definite_add_failure_rolls_back_memory_and_is_retry_safe(tmp_path, monkeypatch):
    """replace 前耗尽=确定未提交；失败 add 不得留内存幽灵条目."""
    path = tmp_path / "schedule.json"
    original = sched._write_temp_exclusive

    def boom(temp: Path, text: str):
        if _is_target_temp(temp, path):
            raise OSError(28, "persistent failure")
        return original(temp, text)

    monkeypatch.setattr(sched, "_write_temp_exclusive", boom)
    store = ScheduleStore(path)
    with pytest.raises(SchedulePersistError) as caught:
        store.add("new", after=60)
    assert not isinstance(caught.value, ScheduleCommitUncertainError)
    assert caught.value.outcome == "definitely_not_committed"
    assert caught.value.retry_safe is True
    assert store.list() == []
    assert not path.exists()


def test_transient_failure_recovers_within_retry_budget(tmp_path, monkeypatch):
    """瞬态失败两次内自愈：不抛错、最终落盘成功。"""
    path = tmp_path / "schedule.json"
    _seed(path, [_entry()])
    original = sched._write_temp_exclusive
    state = {"n": 0}

    def flaky(temp, text):
        if _is_target_temp(temp, path):
            state["n"] += 1
            if state["n"] <= 2:
                raise OSError(11, "transient")
        original(temp, text)

    monkeypatch.setattr(sched, "_write_temp_exclusive", flaky)
    store = ScheduleStore(path)
    sid = store.add("new", after=60)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert {d["sid"] for d in data} == {"old-1", sid}
    assert _tmp_files(path) == []


def test_schedule_tool_surfaces_uncertain_add_without_duplicate_retry(tmp_path, monkeypatch):
    """模型面拿到机械 uncertain + sid + retry_safe=false，而不是普通可重试失败."""
    path = tmp_path / "schedule.json"
    original_fsync = sched._fsync_directory

    def fail_dir_fsync(directory: Path):
        if Path(directory) == path.parent:
            raise OSError(5, "dir fsync failed")
        return original_fsync(directory)

    monkeypatch.setattr(sched, "_fsync_directory", fail_dir_fsync)
    tool = ScheduleTool(store=ScheduleStore(path))
    result = tool.execute(message="only-once", after=60)
    assert result.status.value == "error"
    assert result.error_type == "ScheduleCommitUncertainError"
    assert "commit_outcome_uncertain" in result.content
    assert "retry_safe=false" in result.content
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["sid"] in result.content


def test_schedule_cancel_tool_surfaces_uncertain_as_same_sid_retry_safe(tmp_path, monkeypatch):
    """取消是同 sid 幂等操作；uncertain 必须暴露 reconcile 事实而非普通异常."""
    path = tmp_path / "schedule.json"
    store = ScheduleStore(path)
    sid = store.add("cancel-me", after=60)
    original_fsync = sched._fsync_directory

    def fail_dir_fsync(directory: Path):
        if Path(directory) == path.parent:
            raise OSError(5, "dir fsync failed")
        return original_fsync(directory)

    monkeypatch.setattr(sched, "_fsync_directory", fail_dir_fsync)
    result = ScheduleCancelTool(store=store).execute(sid=sid)
    assert result.status.value == "error"
    assert result.error_type == "ScheduleCommitUncertainError"
    assert "commit_outcome_uncertain" in result.content
    assert f"sid={sid}" in result.content
    assert "retry_safe=true" in result.content
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_wake_add_definite_failure_revokes_authority_and_grant(tmp_path, monkeypatch):
    """主状态确定未提交时补偿先行 authority issue；不得留下可恢复 pending grant."""
    path = tmp_path / "schedule.json"
    original = sched._write_temp_exclusive

    def boom(temp: Path, text: str):
        if _is_target_temp(temp, path):
            raise OSError(28, "persistent failure")
        return original(temp, text)

    monkeypatch.setattr(sched, "_write_temp_exclusive", boom)
    store = ScheduleStore(path)
    grant = delegate_ingress(issue_ingress("web"), entry="schedule_wake")
    with pytest.raises(SchedulePersistError):
        store.add("wake", after=60, wake=True, session_id="s", wake_grant=grant)
    records = store._authority._read()
    assert len(records) == 1
    sid, record = next(iter(records.items()))
    assert record["state"] == "revoked"
    assert store.wake_grant(sid) is None
    assert store.list() == []


def test_wake_add_uncertain_keeps_pending_authority_for_visible_state(tmp_path, monkeypatch):
    """replace 后 uncertain 不能补偿撤权：可见 main state 与 pending authority 必须同在."""
    path = tmp_path / "schedule.json"
    original_fsync = sched._fsync_directory

    def fail_dir_fsync(directory: Path):
        if Path(directory) == path.parent:
            raise OSError(5, "dir fsync failed")
        return original_fsync(directory)

    monkeypatch.setattr(sched, "_fsync_directory", fail_dir_fsync)
    store = ScheduleStore(path)
    grant = delegate_ingress(issue_ingress("web"), entry="schedule_wake")
    with pytest.raises(ScheduleCommitUncertainError) as caught:
        store.add("wake", after=60, wake=True, session_id="s", wake_grant=grant)
    sid = caught.value.sid
    assert json.loads(path.read_text(encoding="utf-8"))[0]["sid"] == sid
    assert store._authority._read()[sid]["state"] == "pending"
    assert store.wake_grant(sid) is grant


def test_claim_due_uncertain_visible_match_returns_claim_without_replay(tmp_path, monkeypatch):
    """内部 claim 在 exact visible match 时接受 uncertain，不做第二次 lease mutation."""
    path = tmp_path / "schedule.json"
    store = ScheduleStore(path)
    sid = store.add("due", after=0)
    original_fsync = sched._fsync_directory

    def fail_dir_fsync(directory: Path):
        if Path(directory) == path.parent:
            raise OSError(5, "dir fsync failed")
        return original_fsync(directory)

    monkeypatch.setattr(sched, "_fsync_directory", fail_dir_fsync)
    claimed = store.claim_due("owner-a", lease_s=30)
    assert [entry.sid for entry in claimed] == [sid]
    row = json.loads(path.read_text(encoding="utf-8"))[0]
    assert row["lease_owner"] == "owner-a"


def test_mark_triggered_uncertain_visible_match_accepts_ack(tmp_path, monkeypatch):
    """通知已发生后的 ack 若 exact visible match，视当前态已应用而不再语义重放."""
    path = tmp_path / "schedule.json"
    store = ScheduleStore(path)
    sid = store.add("once", after=0)
    store.claim_due("owner-a", lease_s=30)
    original_fsync = sched._fsync_directory

    def fail_dir_fsync(directory: Path):
        if Path(directory) == path.parent:
            raise OSError(5, "dir fsync failed")
        return original_fsync(directory)

    monkeypatch.setattr(sched, "_fsync_directory", fail_dir_fsync)
    store.mark_triggered(sid, owner="owner-a")
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_note_wake_started_uncertain_visible_match_keeps_at_most_once_tombstone(
    tmp_path, monkeypatch
):
    """wake admission: main-state durability uncertain 时 authority started tombstone 仍先落盘."""
    path = tmp_path / "schedule.json"
    store = ScheduleStore(path)
    grant = delegate_ingress(issue_ingress("web"), entry="schedule_wake")
    sid = store.add("wake", after=0, wake=True, session_id="s", wake_grant=grant)
    store.claim_due("owner-a", lease_s=30)
    original_fsync = sched._fsync_directory

    def fail_dir_fsync(directory: Path):
        if Path(directory) == path.parent:
            raise OSError(5, "dir fsync failed")
        return original_fsync(directory)

    monkeypatch.setattr(sched, "_fsync_directory", fail_dir_fsync)
    store.note_wake_started(sid, owner="owner-a")
    row = json.loads(path.read_text(encoding="utf-8"))[0]
    assert row["wake_started_at"] > 0
    assert store._authority._read()[sid]["state"] == "started"


def test_recover_reports_invalid_entries_and_orphan_tmp(tmp_path):
    """recover()：无效条目计数 + 孤儿 tmp 计数 + SchedulePersistError 是 OSError。"""
    assert issubclass(SchedulePersistError, OSError)
    path = tmp_path / "schedule.json"
    _seed(path, [_entry("ok-1"), {"sid": "bad", "trigger_at": "not-a-number"}, "junk-not-dict"])
    (tmp_path / "schedule.json.deadbeef.tmp").write_text("orphan", encoding="utf-8")
    store = ScheduleStore(path)
    report = store.recover()
    assert report["readable"] and not report["corrupt"]
    assert report["entries"] == 3
    assert report["invalid_entries"] == 2
    assert report["orphan_tmp"] == 1


def test_invalid_non_dict_first_entry_is_fail_open_not_attribute_error(tmp_path):
    """recover 已识别非 dict 时，_load 不能因顺序不同改成 AttributeError 崩初始化."""
    path = tmp_path / "schedule.json"
    _seed(path, ["junk-not-dict", _entry("ok-after-junk")])
    store = ScheduleStore(path)
    report = store.recover()
    assert report["readable"] and report["invalid_entries"] == 1
    # 维持既有整次 load fail-open 语义：首条非法时不猜测后续部分状态。
    assert store._entries == {}


def test_refresh_invalid_non_dict_keeps_last_known_memory(tmp_path):
    """refresh 遇非 dict 条目时沿用内存 SoT，不因 AttributeError 清空/崩溃."""
    path = tmp_path / "schedule.json"
    store = ScheduleStore(path)
    sid = store.add("known-good", after=60)
    _seed(path, ["junk-not-dict", _entry("other")])
    store.refresh()
    assert set(store._entries) == {sid}


def test_posix_lock_failure_is_fail_closed(tmp_path, monkeypatch):
    """T2 单写者红线：POSIX lock OSError 不能降级成无锁 read-modify-write."""
    path = tmp_path / "schedule.json"
    store = ScheduleStore(path)
    real_open = Path.open

    def fail_lock_open(self, *args, **kwargs):
        if self == path.with_suffix(path.suffix + ".lock"):
            raise OSError(13, "permission denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_lock_open)
    with pytest.raises(SchedulePersistError, match="拒绝无锁写入"):
        store.add("must-not-write-unlocked", after=60)
    assert not path.exists()


def test_authority_projection_failure_skips_commit_without_raising(tmp_path, monkeypatch):
    """边界钉子：授权投影失败 → 跳过本次主状态提交（不写半套状态）且不抛错.

    wake 投递路径依赖该降级语义返回 WAKE_DEFERRED（见
    test_schedule_restart_recovery.py::test_failed_authority_persistence_prevents_model_work）。
    前置：rearm 签发真实授权记录，projection 变更才会触发 preserve_fields→_write。
    """
    path = tmp_path / "schedule.json"
    _seed(path, [])
    store = ScheduleStore(path)
    sid = store.add("wake-reminder", after=0, wake=True, session_id="fixture")
    assert rearm_wake_grants(store, "fixture", issue_ingress("web")) == 1  # 签发授权
    committed_text = path.read_text(encoding="utf-8")

    def fail_write(_records):
        raise OSError("authority disk unavailable")

    monkeypatch.setattr(store._authority, "_write", fail_write)
    store.note_wake_waiting(sid, "awaiting_run_admission")  # 不抛错
    assert path.read_text(encoding="utf-8") == committed_text  # 不写半套状态
    # 注：内存注记未提交故不落 SoT——list() 刷新自磁盘，等待原因不可见是正确语义。
