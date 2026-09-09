"""Background external-execution registry with durable mechanical lifecycle facts.

``execute_command(run_in_background=true)`` and ``dsh_task(background=true)`` keep a
process-local handle for low-latency output/termination, while EventStore records the
stable owner/workspace/lifecycle facts needed after a runtime restart.  A fresh runtime
may observe an orphaned execution but never reattach, kill, restart, or otherwise reclaim
it automatically.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.core.external_execution import ExternalExecutionJournal

logger = logging.getLogger(__name__)

_DEFAULT_MAX_CONCURRENT = 5


class JobLimitExceeded(RuntimeError):  # noqa: N818 - public compatibility name
    """Active background execution limit reached."""


class JobDurabilityError(RuntimeError):  # noqa: N818 - explicit launch contract failure
    """A durable launch fact was required but could not be committed."""


@dataclass
class JobEntry:
    """One process-local background execution handle."""

    id: str
    command: str
    proc: Any = None
    output: list[str] = field(default_factory=list)
    done: bool = False
    exit_code: int | None = None
    killed: bool = False
    session_id: str = ""
    workspace_root: str = ""
    executor: str = ""
    durable: bool = False
    cancel_durable: bool = False
    terminal_durable: bool = False
    journal: ExternalExecutionJournal | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class JobRegistry:
    """Process-local handles backed by an optional durable ExternalExecutionJournal."""

    _instance: JobRegistry | None = None

    def __init__(self, *, event_store: Any | None = None) -> None:
        self._jobs: dict[str, JobEntry] = {}
        self._lock = threading.Lock()
        self._seq = 0
        self._creating = 0
        self._journal = ExternalExecutionJournal(event_store)
        try:
            self.max_concurrent = max(
                1, int(os.environ.get("JOB_MAX_CONCURRENT", _DEFAULT_MAX_CONCURRENT))
            )
        except ValueError:
            self.max_concurrent = _DEFAULT_MAX_CONCURRENT

    @classmethod
    def instance(cls) -> JobRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def configure(self, *, event_store: Any | None) -> None:
        """Bind the durable EventStore used by the current runtime.

        This does not mutate existing process handles.  Production has one shared store;
        tests/hot construction may explicitly rebind the singleton.
        """
        self._journal = ExternalExecutionJournal(event_store)

    @property
    def durable_enabled(self) -> bool:
        return self._journal.enabled

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if not j.done and not j.killed)

    @staticmethod
    def _process_group(proc: Any) -> int:
        pid = int(getattr(proc, "pid", 0) or 0)
        if pid <= 0:
            return 0
        try:
            return int(os.getpgid(pid))
        except (ProcessLookupError, PermissionError, OSError):
            return 0

    def _new_job_id(self, *, durable: bool) -> str:
        if durable:
            return f"job-{uuid.uuid4().hex[:20]}"
        self._seq += 1
        return f"job-{self._seq}"

    def create(
        self,
        proc: Any,
        command: str,
        session_id: str = "",
        *,
        workspace_root: str = "",
        executor: str = "execute_command",
    ) -> str:
        """Register a live process only after any required durable launch fact commits."""
        with self._lock:
            active = sum(1 for j in self._jobs.values() if not j.done and not j.killed)
            if active + self._creating >= self.max_concurrent:
                raise JobLimitExceeded(
                    f"活跃后台任务数已达上限 {self.max_concurrent}"
                    "（可等待已有任务结束；若用户明确要求取消现有任务，再走取消授权路径；"
                    "或由运维调整 JOB_MAX_CONCURRENT）"
                )
            self._creating += 1
            requires_durable = self._journal.enabled and bool(session_id)
            job_id = self._new_job_id(durable=requires_durable)

        canonical_workspace = ""
        if workspace_root:
            try:
                canonical_workspace = str(Path(workspace_root).expanduser().resolve())
            except OSError:
                canonical_workspace = str(Path(workspace_root).expanduser())
        command_sha256 = hashlib.sha256(command.encode("utf-8", "replace")).hexdigest()
        pid = int(getattr(proc, "pid", 0) or 0)
        pgid = self._process_group(proc)
        launch = None
        try:
            if requires_durable:
                launch = self._journal.launched(
                    session_id=session_id,
                    job_id=job_id,
                    workspace_root=canonical_workspace,
                    executor=str(executor or "external"),
                    command_sha256=command_sha256,
                    pid=pid,
                    pgid=pgid,
                )
                if launch is None:
                    raise JobDurabilityError("external execution launch fact unavailable")

            entry = JobEntry(
                id=job_id,
                command=command,
                proc=proc,
                session_id=session_id,
                workspace_root=canonical_workspace,
                executor=str(executor or "external"),
                durable=bool(launch and launch.durable),
                journal=self._journal,
            )
            with self._lock:
                # UUID-backed durable ids make collision practically impossible. Legacy
                # ids are allocated under the same lock for process-local compatibility.
                if job_id in self._jobs:
                    raise JobDurabilityError(f"duplicate external execution id: {job_id}")
                self._jobs[job_id] = entry
            return job_id
        finally:
            with self._lock:
                self._creating = max(0, self._creating - 1)

    def get(self, job_id: str) -> JobEntry | None:
        with self._lock:
            return self._jobs.get(job_id)

    def active_for_session(self, session_id: str) -> tuple[JobEntry, ...]:
        if not session_id:
            return ()
        with self._lock:
            return tuple(
                j
                for j in self._jobs.values()
                if j.session_id == session_id and not j.done and not j.killed
            )

    def snapshots_for_session(self, session_id: str) -> tuple[dict[str, object], ...]:
        """Return owner-scoped local jobs plus durable nonterminal orphan facts.

        Completed jobs remain visible while this runtime still has their local handle.
        After restart, only durable launched-without-terminal executions are surfaced;
        no liveness, reattach, or reclaim authority is inferred from PID/PGID facts.
        """
        if not session_id:
            return ()
        with self._lock:
            local_ids = [
                entry.id for entry in self._jobs.values() if entry.session_id == session_id
            ]
        snapshots: list[dict[str, object]] = []
        seen: set[str] = set()
        for job_id in local_ids:
            item = self.snapshot(job_id, session_id=session_id)
            if item is not None:
                snapshots.append(item)
                seen.add(job_id)
        for state in self._journal.nonterminal(session_id):
            if state.job_id in seen:
                continue
            item = self.snapshot(state.job_id, session_id=session_id)
            if item is not None:
                snapshots.append(item)
        return tuple(snapshots)

    def snapshot(self, job_id: str, *, session_id: str = "") -> dict[str, object] | None:
        """Return local facts or owner-scoped durable facts without fabricating liveness."""
        entry = self.get(job_id)
        if entry is not None:
            if session_id and entry.session_id and entry.session_id != session_id:
                return None
            with entry._lock:
                if entry.killed:
                    state = "killed"
                elif entry.done:
                    state = "completed" if entry.exit_code == 0 else "failed"
                else:
                    state = "running"
                output = list(entry.output)
                exit_code = entry.exit_code
                killed = entry.killed
                cancel_durable = entry.cancel_durable
                terminal_durable = entry.terminal_durable
            durable_state = (
                entry.journal.state(entry.session_id, job_id)
                if entry.durable and entry.session_id and entry.journal is not None
                else None
            )
            return {
                "job_id": job_id,
                "session_id": entry.session_id,
                "workspace_root": entry.workspace_root,
                "executor": entry.executor,
                "state": state,
                "exit_code": exit_code,
                "killed": killed,
                "cancel_requested": bool(
                    cancel_durable or (durable_state and durable_state.cancel_requested)
                ),
                "local_handle": True,
                "durable": entry.durable,
                "state_durable": (entry.durable if state == "running" else terminal_durable),
                "auto_reclaim": False,
                "output": output,
                "command": entry.command,
            }

        if not session_id:
            return None
        durable = self._journal.state(session_id, job_id)
        if durable is None:
            return None
        # A launched record without a terminal fact is epistemically orphaned after
        # restart.  PID/PGID observations are not sufficient authority to signal it.
        state = "orphaned" if durable.state == "running" else durable.state
        return {
            "job_id": job_id,
            "session_id": durable.session_id,
            "workspace_root": durable.workspace_root,
            "executor": durable.executor,
            "state": state,
            "exit_code": durable.exit_code,
            "killed": durable.killed,
            "cancel_requested": durable.cancel_requested,
            "local_handle": False,
            "durable": True,
            "state_durable": True,
            "auto_reclaim": False,
            "output": [],
            "command": "",
        }

    def start_readers(self, job_id: str) -> None:
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
        entry = self.get(job_id)
        if entry is None:
            return
        for line in iter(stream.readline, ""):
            with entry._lock:
                entry.output.append(f"[{tag}] {line.rstrip()}")

    def _watch_completion(self, job_id: str) -> None:
        entry = self.get(job_id)
        if entry is None or entry.proc is None:
            return
        proc = entry.proc
        code = proc.wait()
        exit_code = int(code) if isinstance(code, int) else getattr(proc, "returncode", None)
        with entry._lock:
            killed = entry.killed
        # Publish the durable terminal fact before exposing local terminal state.  If
        # the event transport fails, local completion remains usable but a fresh
        # runtime will honestly retain orphaned/unknown state.
        terminal_durable = False
        if entry.durable and entry.session_id and entry.journal is not None:
            terminal_record = entry.journal.terminal(
                session_id=entry.session_id,
                job_id=job_id,
                exit_code=exit_code,
                killed=killed,
            )
            terminal_durable = terminal_record is not None and bool(terminal_record.terminal_seq)
        with entry._lock:
            entry.done = True
            entry.exit_code = exit_code
            entry.terminal_durable = terminal_durable
        self._notify_completion(job_id)

    @staticmethod
    def _signal_proc(proc: Any) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError, AttributeError):
            proc.terminate()

    def _terminate_entry(self, entry: JobEntry, *, reason: str) -> bool:
        with entry._lock:
            if entry.done or entry.killed or entry.proc is None:
                return False
        durable_cancel = False
        if entry.durable and entry.session_id and entry.journal is not None:
            record = entry.journal.cancel_requested(
                session_id=entry.session_id,
                job_id=entry.id,
                reason=reason,
            )
            durable_cancel = record is not None and record.cancel_requested
        # Local safety/resource cancellation proceeds even when the fact transport fails;
        # a fresh runtime will then honestly have no durable cancel_requested fact.
        self._signal_proc(entry.proc)
        with entry._lock:
            entry.killed = True
            entry.cancel_durable = durable_cancel
        return True

    def kill(
        self, job_id: str, *, requester_session_id: str = "", reason: str = "user_job_kill"
    ) -> tuple[bool, str]:
        entry = self.get(job_id)
        if entry is None:
            if requester_session_id:
                durable = self._journal.state(requester_session_id, job_id)
                if durable is not None:
                    if durable.state != "running":
                        return False, "任务已结束"
                    return False, "任务仅有durable orphan事实；本进程无句柄，auto_reclaim=false"
            return False, "任务不存在"
        if requester_session_id and entry.session_id and entry.session_id != requester_session_id:
            return False, "任务不属于当前会话"
        with entry._lock:
            if entry.done or entry.killed:
                return False, "任务已结束"
        if not self._terminate_entry(entry, reason=reason):
            return False, "任务已结束或本进程无句柄"
        return True, "SIGTERM 已发送"

    def cancel_session(self, session_id: str) -> int:
        """Cancel only this process's active jobs owned by ``session_id``."""
        entries = self.active_for_session(session_id)
        count = 0
        for entry in entries:
            if self._terminate_entry(entry, reason="session_cancel"):
                count += 1
        return count

    def _notify_completion(self, job_id: str) -> None:
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
                return
            base = (
                Path(os.environ.get("LFL_DATA_DIR", "data")) / "interop" / "lfl_to_dsh" / "pending"
            )
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
            (base / fname).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            logger.info("job 终态通知已写入 inbox: job_id=%s status=%s", job_id, status)
        except Exception:  # noqa: BLE001 - notification is best-effort observability
            logger.warning("job 终态通知写入失败（fail-open）: job_id=%s", job_id, exc_info=True)


__all__ = [
    "JobDurabilityError",
    "JobEntry",
    "JobLimitExceeded",
    "JobRegistry",
]
