"""DSH 借鉴 021（2026-08-17）: JobRegistry 并发上限 + 终态通知测试."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from llm_loop.tools.builtin.job_registry import JobLimitExceeded, JobRegistry


class _FakeProc:
    """模拟 subprocess: wait() 立即返回，exit_code 可配."""

    def __init__(self, exit_code: int = 0) -> None:
        self.returncode = exit_code
        self.stdout = None
        self.stderr = None

    def wait(self) -> int:
        return self.returncode


def _fresh_registry(monkeypatch, max_concurrent: int = 5) -> JobRegistry:
    """单例隔离: 重建实例 + 设并发上限."""
    monkeypatch.setenv("JOB_MAX_CONCURRENT", str(max_concurrent))
    JobRegistry._instance = None
    reg = JobRegistry.instance()
    reg._jobs.clear()  # 防历史 job 残留
    reg._seq = 0
    return reg


# ── 建议 B: owner 并发上限 ──
def test_create_rejects_over_limit(monkeypatch):
    reg = _fresh_registry(monkeypatch, max_concurrent=2)
    assert reg.create(_FakeProc(), "cmd1") == "job-1"
    assert reg.create(_FakeProc(), "cmd2") == "job-2"
    with pytest.raises(JobLimitExceeded):
        reg.create(_FakeProc(), "cmd3")
    assert reg.active_count() == 2


def test_limit_freed_after_completion(monkeypatch):
    reg = _fresh_registry(monkeypatch, max_concurrent=1)
    job_id = reg.create(_FakeProc(exit_code=0), "cmd1")
    # 手动置为完成（模拟 watcher 标记）→ 配额释放
    entry = reg.get(job_id)
    with entry._lock:
        entry.done = True
        entry.exit_code = 0
    assert reg.active_count() == 0
    assert reg.create(_FakeProc(), "cmd2") == "job-2"


def test_limit_freed_after_kill(monkeypatch):
    reg = _fresh_registry(monkeypatch, max_concurrent=1)
    job_id = reg.create(_FakeProc(), "cmd1")
    entry = reg.get(job_id)
    with entry._lock:
        entry.killed = True
    assert reg.active_count() == 0
    assert reg.create(_FakeProc(), "cmd2") == "job-2"


# ── 建议 A: 终态通知写入 interop inbox ──
def test_watcher_notifies_completed(tmp_path, monkeypatch):
    """正常完成(exit=0) → inbox 出现 [任务完成] completed 通知."""
    reg = _fresh_registry(monkeypatch)
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    job_id = reg.create(_FakeProc(exit_code=0), "echo ok")
    reg.start_readers(job_id)
    _wait_for(lambda: _inbox_files(tmp_path) != [], timeout=3)
    files = _inbox_files(tmp_path)
    assert len(files) == 1
    msg = json.loads(files[0].read_text(encoding="utf-8"))
    assert msg["from"] == "job-registry"
    assert msg["topic"] == "notify"
    assert msg["status"] == "pending"
    assert msg["ref"] == job_id
    assert "[任务完成]" in msg["body"]
    assert "completed" in msg["body"] and "exit=0" in msg["body"]
    assert job_id in msg["body"]


def test_watcher_notifies_failed(tmp_path, monkeypatch):
    """失败(exit=1) → [任务完成] failed 通知."""
    reg = _fresh_registry(monkeypatch)
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    job_id = reg.create(_FakeProc(exit_code=1), "boom")
    reg.start_readers(job_id)
    _wait_for(lambda: _inbox_files(tmp_path) != [], timeout=3)
    msg = json.loads(_inbox_files(tmp_path)[0].read_text(encoding="utf-8"))
    assert "failed" in msg["body"] and "exit=1" in msg["body"]


def test_watcher_notifies_killed(tmp_path, monkeypatch):
    """killed 终态 → [任务完成] killed 通知（kill 由 job_kill 置位，watcher 兜底通知）."""
    reg = _fresh_registry(monkeypatch)
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    job_id = reg.create(_FakeProc(exit_code=-15), "sleep 100")
    entry = reg.get(job_id)
    with entry._lock:
        entry.killed = True  # 模拟 job_kill 已置 killed
    reg.start_readers(job_id)
    _wait_for(lambda: _inbox_files(tmp_path) != [], timeout=3)
    msg = json.loads(_inbox_files(tmp_path)[0].read_text(encoding="utf-8"))
    assert "killed" in msg["body"]


def test_notify_fail_open_no_inbox_dir(tmp_path, monkeypatch, caplog):
    """LFL_DATA_DIR 不可写 → 通知失败仅日志（fail-open），job 状态不受影响."""
    reg = _fresh_registry(monkeypatch)
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path / "no" / "such" / "dir"))
    job_id = reg.create(_FakeProc(exit_code=0), "cmd")
    reg.start_readers(job_id)
    _wait_for(lambda: reg.get(job_id).done, timeout=3)
    assert reg.get(job_id).done is True  # 状态标记不受通知失败影响
    assert not (tmp_path / "no" / "such" / "dir").exists()  # 未创建目录


# ── 辅助 ──
def _inbox_files(tmp_path: Path) -> list[Path]:
    base = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    if not base.is_dir():
        return []
    return sorted(base.glob("*.json"))


def _wait_for(cond, timeout: float = 3.0, interval: float = 0.05) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return
        time.sleep(interval)
    raise AssertionError(f"条件在 {timeout}s 内未满足")
