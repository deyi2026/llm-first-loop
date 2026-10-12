"""EVO-20261013 队列可观测性：oldest_queued / requeue_stats / 准入心跳.

用户确认的两项学习页需求之一（阻塞显化）：排队数之外显化
① 最老任务等待时长 ② worker 阻塞原因 ③ requeue 原因统计。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from llm_loop.methods.learning_journal import LearningJournal
from llm_loop.methods.learning_plane import LearningPlane
from llm_loop.resources.foreground import ForegroundActivityProbe
from llm_loop.resources.governor import ResourceGovernor


def _journal(tmp_path: Path) -> LearningJournal:
    return LearningJournal(tmp_path / "journal.jsonl")


def _write_events(tmp_path: Path, events: list[dict]) -> LearningJournal:
    journal = _journal(tmp_path)
    with (tmp_path / "journal.jsonl").open("w", encoding="utf-8") as fh:
        for evt in events:
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")
    return journal


def test_oldest_queued_empty_journal_returns_none(tmp_path: Path) -> None:
    assert _journal(tmp_path).oldest_queued() is None


def test_oldest_queued_picks_oldest_queued_job(tmp_path: Path) -> None:
    base = time.time() - 4000.0
    journal = _write_events(
        tmp_path,
        [
            {"event": "queued", "job_id": "learn:a", "kind": "reflection", "ts": base},
            {"event": "queued", "job_id": "learn:b", "kind": "memory_extract", "ts": base + 100.0},
            {"event": "requeued", "job_id": "learn:a", "reason": "resource_authority_changed", "ts": base + 200.0},
        ],
    )

    oldest = journal.oldest_queued()
    assert oldest is not None
    assert oldest["job_id"] == "learn:a"
    assert oldest["kind"] == "reflection"
    # created_at 取首次 queued；等待时长 ≈ now - created_at
    assert oldest["wait_seconds"] >= 3800.0


def test_oldest_queued_ignores_terminal_jobs(tmp_path: Path) -> None:
    now = time.time()
    journal = _write_events(
        tmp_path,
        [
            {"event": "queued", "job_id": "learn:done", "kind": "reflection", "ts": now - 500.0},
            {"event": "saved", "job_id": "learn:done", "ts": now - 400.0},
        ],
    )
    assert journal.oldest_queued() is None


def test_requeue_stats_counts_by_reason_all_history_and_window(tmp_path: Path) -> None:
    now = time.time()
    events: list[dict] = []
    for i in range(3):
        events.append({"event": "queued", "job_id": f"learn:{i}", "kind": "reflection", "ts": now - 100.0})
        events.append({"event": "requeued", "job_id": f"learn:{i}", "reason": "resource_authority_changed", "ts": now - 90.0})
    events.append({"event": "requeued", "job_id": "learn:0", "reason": "preempted_by_foreground", "ts": now - 10.0})
    journal = _write_events(tmp_path, events)

    stats = journal.requeue_stats()
    assert stats["total"]["resource_authority_changed"] == 3
    assert stats["total"]["preempted_by_foreground"] == 1
    # 全部事件都落在 24h 窗口内
    assert stats["recent"]["resource_authority_changed"] == 3
    assert stats["recent_window_s"] == 86400.0
    assert stats["last_event_ts"] > now - 60.0


def test_requeue_stats_uses_mtime_cache_between_calls(tmp_path: Path) -> None:
    now = time.time()
    journal = _write_events(
        tmp_path,
        [
            {"event": "queued", "job_id": "learn:x", "kind": "reflection", "ts": now},
            {"event": "requeued", "job_id": "learn:x", "reason": "service_restart_barrier", "ts": now},
        ],
    )

    first = journal.requeue_stats()
    # 未追加新事件：缓存命中应返回相同结构
    second = journal.requeue_stats()
    assert first == second
    # 追加后缓存失效、统计更新
    journal.mark_requeued("learn:x", "service_restart_barrier")
    third = journal.requeue_stats()
    assert third["total"]["service_restart_barrier"] == 2


def _mk_plane(
    tmp_path: Path,
    journal: LearningJournal,
    *,
    heartbeat_path=None,
) -> LearningPlane:
    engine = SimpleNamespace(
        registry=object(),
        runner=SimpleNamespace(has_running=lambda: False),
        _sync_guard=threading.Lock(),
        _sync_active=set(),
    )
    probe = ForegroundActivityProbe(engine, tmp_path / "sessions")
    governor = ResourceGovernor(foreground_probe=probe.active)

    def _resource_target(model_ref: str) -> tuple[str, str]:
        if "/" in model_ref:
            return tuple(model_ref.split("/", 1))  # type: ignore[return-value]
        return "test-provider", model_ref or "test-model"

    return LearningPlane(
        journal=journal,
        episode_store=SimpleNamespace(get=lambda *_args: None),
        method_store=SimpleNamespace(),
        engine=engine,
        model_resolver=lambda _model: "fake",
        resource_governor=governor,
        resource_target_resolver=_resource_target,
        memory_extractor=SimpleNamespace(),
        poll_interval_s=1.0,
        quiet_period_s=0.0,
        admission_heartbeat_path=heartbeat_path,
    )


def test_admission_block_reason_reports_foreground(tmp_path: Path) -> None:
    now = time.time()
    journal = _write_events(
        tmp_path,
        [{"event": "queued", "job_id": "learn:f", "kind": "reflection", "ts": now - 300.0}],
    )
    engine = SimpleNamespace(
        registry=object(),
        runner=SimpleNamespace(has_running=lambda: False),
        _sync_guard=threading.Lock(),
        _sync_active=set(),
    )
    journal_dir = tmp_path / "sessions"
    probe = ForegroundActivityProbe(engine, journal_dir)
    governor = ResourceGovernor(foreground_probe=probe.active)

    def _resource_target(model_ref: str) -> tuple[str, str]:
        return "test-provider", model_ref or "test-model"

    plane = LearningPlane(
        journal=journal,
        episode_store=SimpleNamespace(get=lambda *_args: None),
        method_store=SimpleNamespace(),
        engine=engine,
        model_resolver=lambda _model: "fake",
        resource_governor=governor,
        resource_target_resolver=_resource_target,
        memory_extractor=SimpleNamespace(),
        poll_interval_s=1.0,
        quiet_period_s=0.0,
    )
    job = journal.runnable_jobs()[0]
    assert plane._admission_block_reason(job) is None  # 四门全开
    engine.runner.has_running = lambda: True  # 前台会话在场 → 全队列让位
    assert plane._admission_block_reason(job) == "foreground_busy"


def test_heartbeat_writes_on_state_change_and_throttles(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    hb_path = tmp_path / "runtime" / "learning_admission.json"
    plane = _mk_plane(tmp_path, journal, heartbeat_path=hb_path)

    plane._write_admission_heartbeat("blocked", "foreground_busy", 36)
    payload = json.loads(hb_path.read_text(encoding="utf-8"))
    assert payload["state"] == "blocked"
    assert payload["reason"] == "foreground_busy"
    assert payload["queued"] == 36
    assert payload["pid"] > 0
    first_ts = payload["ts"]

    # 同状态短时间重复：节流跳过（文件不重写）
    plane._write_admission_heartbeat("blocked", "foreground_busy", 36)
    assert json.loads(hb_path.read_text(encoding="utf-8"))["ts"] == first_ts

    # 状态变化：立即写并重置 since
    plane._write_admission_heartbeat("draining", None, 36)
    payload2 = json.loads(hb_path.read_text(encoding="utf-8"))
    assert payload2["state"] == "draining"
    assert payload2["reason"] == ""
    assert payload2["since"] >= first_ts


def test_heartbeat_fail_open_without_path(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    plane = _mk_plane(tmp_path, journal)
    # admission_heartbeat_path 默认 None：不落盘也不抛错
    plane._write_admission_heartbeat("idle", None, 0)
    assert not (tmp_path / "runtime").exists()
