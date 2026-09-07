"""Durable mechanical facts for long-lived external executions.

This journal records ownership/lifecycle facts only.  It never decides whether an
execution is useful, whether its effects satisfy a task, or whether an orphan should
be reclaimed/restarted.  EventStore remains the append-only source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm_loop.event_log.model import (
    EVENT_EXTERNAL_EXECUTION_CANCEL_REQUESTED,
    EVENT_EXTERNAL_EXECUTION_LAUNCHED,
    EVENT_EXTERNAL_EXECUTION_TERMINAL,
)


@dataclass(frozen=True)
class ExternalExecutionState:
    job_id: str
    session_id: str
    workspace_root: str
    executor: str
    command_sha256: str
    pid: int
    pgid: int
    state: str
    exit_code: int | None = None
    killed: bool = False
    cancel_requested: bool = False
    cancel_reason: str = ""
    launch_seq: int = 0
    terminal_seq: int = 0
    cancel_seq: int = 0
    durable: bool = True


class ExternalExecutionJournal:
    """Append/read session-scoped external-execution lifecycle facts."""

    def __init__(self, event_store: Any | None) -> None:
        self.event_store = event_store

    @property
    def enabled(self) -> bool:
        store = self.event_store
        return store is not None and bool(getattr(store, "enabled", False))

    def _append(self, session_id: str, event_type: str, payload: dict[str, object]) -> Any | None:
        store = self.event_store
        if not self.enabled or store is None:
            return None
        return store.append(session_id, event_type, payload)

    def launched(
        self,
        *,
        session_id: str,
        job_id: str,
        workspace_root: str,
        executor: str,
        command_sha256: str,
        pid: int = 0,
        pgid: int = 0,
    ) -> ExternalExecutionState | None:
        """Persist launch ownership before a background-start receipt may be returned."""
        if not self.enabled:
            return ExternalExecutionState(
                job_id=job_id,
                session_id=session_id,
                workspace_root=workspace_root,
                executor=executor,
                command_sha256=command_sha256,
                pid=int(pid or 0),
                pgid=int(pgid or 0),
                state="running",
                durable=False,
            )
        existing = self.state(session_id, job_id)
        if existing is not None:
            if (
                existing.workspace_root == workspace_root
                and existing.executor == executor
                and existing.command_sha256 == command_sha256
            ):
                return existing
            return None
        event = self._append(
            session_id,
            EVENT_EXTERNAL_EXECUTION_LAUNCHED,
            {
                "job_id": job_id,
                "workspace_root": workspace_root,
                "executor": executor,
                "command_sha256": command_sha256,
                "pid": int(pid or 0),
                "pgid": int(pgid or 0),
                "auto_reclaim": False,
            },
        )
        if event is None:
            return None
        return ExternalExecutionState(
            job_id=job_id,
            session_id=session_id,
            workspace_root=workspace_root,
            executor=executor,
            command_sha256=command_sha256,
            pid=int(pid or 0),
            pgid=int(pgid or 0),
            state="running",
            launch_seq=int(getattr(event, "seq", 0) or 0),
        )

    def cancel_requested(
        self, *, session_id: str, job_id: str, reason: str
    ) -> ExternalExecutionState | None:
        state = self.state(session_id, job_id)
        if state is None:
            return None
        if not self.enabled:
            return state
        if state.cancel_requested:
            return state
        event = self._append(
            session_id,
            EVENT_EXTERNAL_EXECUTION_CANCEL_REQUESTED,
            {
                "job_id": job_id,
                "reason": str(reason or "session_cancel"),
                "auto_reclaim": False,
            },
        )
        if event is None:
            return None
        return ExternalExecutionState(
            **{
                **state.__dict__,
                "cancel_requested": True,
                "cancel_reason": str(reason or "session_cancel"),
                "cancel_seq": int(getattr(event, "seq", 0) or 0),
            }
        )

    def terminal(
        self,
        *,
        session_id: str,
        job_id: str,
        exit_code: int | None,
        killed: bool,
    ) -> ExternalExecutionState | None:
        state = self.state(session_id, job_id)
        if state is None:
            return None
        if not self.enabled:
            return state
        if state.terminal_seq:
            return state
        normalized_exit = int(exit_code) if isinstance(exit_code, int) else None
        terminal_state = "killed" if killed else ("completed" if normalized_exit == 0 else "failed")
        event = self._append(
            session_id,
            EVENT_EXTERNAL_EXECUTION_TERMINAL,
            {
                "job_id": job_id,
                "state": terminal_state,
                "exit_code": normalized_exit,
                "killed": bool(killed),
                "auto_reclaim": False,
            },
        )
        if event is None:
            return None
        return ExternalExecutionState(
            **{
                **state.__dict__,
                "state": terminal_state,
                "exit_code": normalized_exit,
                "killed": bool(killed),
                "terminal_seq": int(getattr(event, "seq", 0) or 0),
            }
        )

    def state(self, session_id: str, job_id: str) -> ExternalExecutionState | None:
        """Rebuild one job from the owner's append-only event stream."""
        store = self.event_store
        if not self.enabled or store is None or not session_id or not store.exists(session_id):
            return None
        launch: Any | None = None
        terminal: Any | None = None
        cancel: Any | None = None
        for event in store.read(session_id) or []:
            payload = dict(getattr(event, "payload", None) or {})
            if str(payload.get("job_id") or "") != job_id:
                continue
            etype = str(getattr(event, "type", ""))
            if etype == EVENT_EXTERNAL_EXECUTION_LAUNCHED and launch is None:
                launch = event
            elif etype == EVENT_EXTERNAL_EXECUTION_CANCEL_REQUESTED:
                cancel = event
            elif etype == EVENT_EXTERNAL_EXECUTION_TERMINAL:
                terminal = event
        if launch is None:
            return None
        lp = dict(getattr(launch, "payload", None) or {})
        cp = dict(getattr(cancel, "payload", None) or {}) if cancel is not None else {}
        tp = dict(getattr(terminal, "payload", None) or {}) if terminal is not None else {}
        terminal_state = str(tp.get("state") or "")
        state = terminal_state or "running"
        raw_exit = tp.get("exit_code")
        exit_code = int(raw_exit) if isinstance(raw_exit, int) else None
        return ExternalExecutionState(
            job_id=job_id,
            session_id=session_id,
            workspace_root=str(lp.get("workspace_root") or ""),
            executor=str(lp.get("executor") or ""),
            command_sha256=str(lp.get("command_sha256") or ""),
            pid=int(lp.get("pid") or 0),
            pgid=int(lp.get("pgid") or 0),
            state=state,
            exit_code=exit_code,
            killed=bool(tp.get("killed")),
            cancel_requested=cancel is not None,
            cancel_reason=str(cp.get("reason") or ""),
            launch_seq=int(getattr(launch, "seq", 0) or 0),
            terminal_seq=int(getattr(terminal, "seq", 0) or 0) if terminal is not None else 0,
            cancel_seq=int(getattr(cancel, "seq", 0) or 0) if cancel is not None else 0,
        )


__all__ = ["ExternalExecutionJournal", "ExternalExecutionState"]
