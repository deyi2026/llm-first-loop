"""知识打分自动闭环调度器：状态落盘、锁、超时退避的单测。"""

from __future__ import annotations

import subprocess
from datetime import timedelta

from llm_loop.knowledge_score import runner
from llm_loop.timekeeping import system_local_now


def test_run_once_no_pending_writes_state(tmp_path):
    result = runner.run_once(tmp_path, health_check=False)
    assert result["skipped"] == "no_pending"
    assert result["consecutive_failures"] == 0
    assert result["last_pending_before"] == 0
    assert runner.read_runner_state(tmp_path)["skipped"] == "no_pending"


def test_run_once_success_updates_state(tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "knowledge_score.py").write_text("", encoding="utf-8")
    pending_values = iter([(3, None), (0, None)])
    monkeypatch.setattr(runner, "count_pending", lambda root: next(pending_values))
    seen: dict[str, object] = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="[run] scored=3 failed=0 stopped=done\n",
            stderr="",
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result = runner.run_once(tmp_path, health_check=False, limit=7, card_timeout_s=12.5)

    assert result["last_scored"] == 3
    assert result["last_failed"] == 0
    assert result["last_pending_after"] == 0
    assert result["consecutive_failures"] == 0
    assert result["next_retry_at"] is None
    assert result["last_success_at"]
    command = seen["command"]
    assert "--all-pending" in command
    assert command[command.index("--limit") + 1] == "7"
    assert command[command.index("--timeout-seconds") + 1] == "12.5"


def test_run_once_timeout_enters_backoff(tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "knowledge_score.py").write_text("", encoding="utf-8")
    pending_values = iter([(2, None), (2, None)])
    monkeypatch.setattr(runner, "count_pending", lambda root: next(pending_values))

    def slow_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(runner.subprocess, "run", slow_run)
    result = runner.run_once(
        tmp_path,
        health_check=False,
        process_timeout_s=1,
        retry_base_s=60,
    )

    assert result["consecutive_failures"] == 1
    assert result["next_retry_at"]
    assert result["stopped"] == "timeout"
    assert "run_timeout" in result["last_error"]


def test_retry_wait_seconds_is_future_positive():
    now = system_local_now()
    future = (now + timedelta(seconds=120)).isoformat()
    assert runner.retry_wait_seconds(future, now=now) > 100
    assert runner.retry_wait_seconds((now - timedelta(seconds=60)).isoformat(), now=now) == 0


def test_run_once_honors_active_backoff_without_spawning(tmp_path, monkeypatch):
    """next_retry_at 未到时不启动子进程，否则 30 分钟 cooldown 内会空跑。"""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "knowledge_score.py").write_text("", encoding="utf-8")
    now = system_local_now()
    runner._write_runner_state(
        tmp_path,
        {
            "schema": runner.SCHEMA,
            "consecutive_failures": 2,
            "next_retry_at": (now + timedelta(seconds=600)).isoformat(),
            "last_error": "scorer_unhealthy",
        },
    )
    monkeypatch.setattr(runner, "count_pending", lambda root: (5, None))

    def must_not_run(*args, **kwargs):
        raise AssertionError("active backoff should not spawn CLI")

    monkeypatch.setattr(runner.subprocess, "run", must_not_run)
    result = runner.run_once(tmp_path, health_check=False)
    assert result["skipped"] == "backoff"
    assert result["consecutive_failures"] == 2
    assert result["last_pending_after"] == 5


def test_run_once_deferred_keeps_backoff(tmp_path, monkeypatch):
    """CLI 正常退出但 0 张可打分（全在 error cooldown）时不得清零失败计数。"""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "knowledge_score.py").write_text("", encoding="utf-8")
    runner._write_runner_state(
        tmp_path,
        {"schema": runner.SCHEMA, "consecutive_failures": 2, "next_retry_at": None},
    )
    pending_values = iter([(3, None), (3, None)])
    monkeypatch.setattr(runner, "count_pending", lambda root: next(pending_values))
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout="[run] scored=0 failed=0 stopped=done\n",
            stderr="",
        ),
    )
    result = runner.run_once(tmp_path, health_check=False, error_cooldown_s=1800)
    assert result["skipped"] == "deferred"
    assert result["consecutive_failures"] == 2
    assert result["next_retry_at"]


def test_read_runner_state_tolerates_corrupt_file(tmp_path):
    path = runner.state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    assert runner.read_runner_state(tmp_path) is None


def test_loop_can_be_disabled(tmp_path):
    loop = runner.KnowledgeScoreLoop(tmp_path, enabled=False)
    assert loop.enabled is False
    loop.start()
    loop.join(timeout=1)
    assert not loop.is_alive()
    loop.stop()
