"""后台任务注册表（EVO-20260814: 对齐 Harness ctx.jobs 思路）.

execute_command(run_in_background=true) 启动的进程在此登记；
job_output / job_kill 工具查询输出与终止任务。

- 线程安全（Lock 保护 entry.output / 状态字段）
- 输出异步收集：stdout/stderr 各一个读线程 append 到 entry.output
- job 生命周期: 启动 → 运行 → 完成(killed/done) → 可反复查询
- 常驻进程内存（会话级），进程退出自然清理
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class JobEntry:
    """单个后台任务条目."""

    id: str
    command: str
    proc: Any = None
    output: list[str] = field(default_factory=list)
    done: bool = False
    exit_code: int | None = None
    killed: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class JobRegistry:
    """进程内后台任务登记表（单例）."""

    _instance: JobRegistry | None = None

    def __init__(self) -> None:
        self._jobs: dict[str, JobEntry] = {}
        self._lock = threading.Lock()
        self._seq = 0

    @classmethod
    def instance(cls) -> JobRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def create(self, proc: Any, command: str) -> str:
        """登记新任务，返回 job_id."""
        with self._lock:
            self._seq += 1
            job_id = f"job-{self._seq}"
            self._jobs[job_id] = JobEntry(id=job_id, command=command, proc=proc)
            return job_id

    def get(self, job_id: str) -> JobEntry | None:
        with self._lock:
            return self._jobs.get(job_id)

    def start_readers(self, job_id: str) -> None:
        """启动 stdout/stderr 读线程 + 完成 watcher（进程刚启动后调用）."""
        entry = self.get(job_id)
        if entry is None or entry.proc is None:
            return
        for stream, tag in ((entry.proc.stdout, "stdout"), (entry.proc.stderr, "stderr")):
            if stream is not None:
                threading.Thread(
                    target=self._read_stream,
                    args=(job_id, stream, tag),
                    daemon=True,
                    name=f"job-{job_id}-{tag}",
                ).start()
        threading.Thread(
            target=self._watch_completion,
            args=(job_id,),
            daemon=True,
            name=f"job-{job_id}-watch",
        ).start()

    def _read_stream(self, job_id: str, stream: Any, tag: str) -> None:
        """读线程：逐行收集输出直到 EOF（EOF 后自然退出，不标记状态）."""
        entry = self.get(job_id)
        if entry is None:
            return
        for line in iter(stream.readline, ""):
            with entry._lock:
                entry.output.append(f"[{tag}] {line.rstrip()}")

    def _watch_completion(self, job_id: str) -> None:
        """watcher 线程：等待进程结束，统一标记完成状态."""
        entry = self.get(job_id)
        if entry is None or entry.proc is None:
            return
        proc = entry.proc
        proc.wait()
        with entry._lock:
            if not entry.killed:
                entry.done = True
                entry.exit_code = proc.returncode
