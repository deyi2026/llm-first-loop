"""后台任务注册表（EVO-20260814: 对齐 Harness ctx.jobs 思路）.

execute_command(run_in_background=true) 启动的进程在此登记；
job_output / job_kill 工具查询输出与终止任务。

- 线程安全（Lock 保护 entry.output / 状态字段）
- 输出异步收集：stdout/stderr 各一个读线程 append 到 entry.output
- job 生命周期: 启动 → 运行 → 完成(killed/done) → 可反复查询
- 常驻进程内存（会话级），进程退出自然清理
- owner 并发上限（2026-08-17 DSH 借鉴 021-B）: 活跃 job（未完成/未 killed）数
  达 max_concurrent 时 create 抛 JobLimitExceeded，调用方如实拒绝——防多会话
  并行后台任务耗尽资源。上限经环境变量 JOB_MAX_CONCURRENT 配置（默认 5）。
- 终态通知（2026-08-17 DSH 借鉴 021-A）: watcher 检测到 job 终态（completed/
  failed/killed）时写一条 interop 通知到 data/interop/lfl_to_dsh/pending/
  （topic=notify, from=job-registry）——LFL 下轮 run 自动注入会话，
  agent 无需手动 job_output 轮询（对齐 scheduler 通知机制）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# DSH 借鉴 021-B: 默认并发上限（JOB_MAX_CONCURRENT 可调）
_DEFAULT_MAX_CONCURRENT = 5


class JobLimitExceeded(RuntimeError):
    """活跃后台任务数达上限，拒绝创建新任务."""


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
        try:
            self.max_concurrent = max(
                1, int(os.environ.get("JOB_MAX_CONCURRENT", _DEFAULT_MAX_CONCURRENT))
            )
        except ValueError:  # 非法值 fail-open 回退默认
            self.max_concurrent = _DEFAULT_MAX_CONCURRENT

    @classmethod
    def instance(cls) -> JobRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def active_count(self) -> int:
        """活跃 job 数（未完成且未 killed）."""
        with self._lock:
            return sum(1 for j in self._jobs.values() if not j.done and not j.killed)

    def create(self, proc: Any, command: str) -> str:
        """登记新任务，返回 job_id；活跃数达上限抛 JobLimitExceeded.

        调用方（execute_command/dsh_task）须捕获并如实拒绝（含释放已 Popen 进程）。
        """
        with self._lock:
            # 锁内直接计数（active_count 也持锁，避免重入死锁）
            active = sum(1 for j in self._jobs.values() if not j.done and not j.killed)
            if active >= self.max_concurrent:
                raise JobLimitExceeded(
                    f"活跃后台任务数已达上限 {self.max_concurrent}"
                    f"（可用 job_kill 释放，或调大 JOB_MAX_CONCURRENT 环境变量）"
                )
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
        """watcher 线程：等待进程结束，统一标记完成状态 + 发终态通知.

        DSH 借鉴 021-A: 终态（completed/failed/killed）写 interop 通知到
        lfl_to_dsh/pending/，LFL 下轮 run 自动注入（agent 免手动 job_output 轮询）。
        """
        entry = self.get(job_id)
        if entry is None or entry.proc is None:
            return
        proc = entry.proc
        proc.wait()
        with entry._lock:
            if not entry.killed:
                entry.done = True
                entry.exit_code = proc.returncode
        self._notify_completion(job_id)

    def _notify_completion(self, job_id: str) -> None:
        """终态通知：写 interop inbox（lfl_to_dsh/pending/，topic=notify，from=job-registry）.

        对齐 scheduler._notify_via_interop 格式；LFL 下轮 run 扫描注入会话
        （[外部协调·from DSH] 回显，web/飞书可见）。fail-open: 写失败仅日志，
        不阻断主流程（job 仍可经 job_output 查询，只是少一条主动通知）。
        """
        try:
            entry = self.get(job_id)
            if entry is None:
                return
            with entry._lock:
                done, killed, exit_code = entry.done, entry.killed, entry.exit_code
            if killed:
                status, detail = "killed", "（已终止）"
            elif done and exit_code == 0:
                status, detail = "completed", "（exit=0）"
            elif done:
                status, detail = "failed", f"（exit={exit_code}）"
            else:
                return  # 非终态不通知
            base = Path(os.environ.get("LFL_DATA_DIR", "data")) / "interop" / "lfl_to_dsh" / "pending"
            base.mkdir(parents=True, exist_ok=True)
            now = datetime.now(UTC)
            ts = now.strftime("%Y%m%d-%H%M%S")
            fname = f"{now.strftime('%Y%m%d')}-job-{ts}-{job_id}.json"
            payload = {
                "id": f"{now.strftime('%Y%m%d')}-job-{job_id}",
                "from": "job-registry",
                "to": "lfl",
                "ts": now.isoformat(),
                "topic": "notify",
                "ref": job_id,
                "body": f"[任务完成] job_id={job_id} 状态={status}{detail}",
                "status": "pending",
            }
            (base / fname).write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            logger.info("job 终态通知已写入 inbox: job_id=%s status=%s", job_id, status)
        except Exception:  # noqa: BLE001 — fail-open: 通知失败不影响主流程
            logger.warning("job 终态通知写入失败（fail-open）: job_id=%s", job_id, exc_info=True)
