"""Deliver one-shot wakes at the actual run admission boundary."""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from typing import Any

from llm_loop.core.scheduler import (
    WAKE_DEFERRED,
    ScheduleEntry,
    SchedulerThread,
    ScheduleStore,
    wake_goal_binding_state,
)

logger = logging.getLogger(__name__)


def _optional_facts(projection: Callable[..., str] | None, argument: Any) -> str:
    try:
        return projection(argument) if projection is not None else ""
    except Exception:  # noqa: BLE001 - optional facts do not own admission
        return ""


class ScheduleWakeDelivery:
    def __init__(
        self, store: ScheduleStore, runner: Any, *, data_dir: str,
        record_action: Callable[..., Any],
        goal_binding_resolver: Callable[..., Any] | None = None,
        restart_barrier: Callable[[], Any] | None = None,
        jobs_facts: Callable[[str], str] | None = None,
        subject_facts: Callable[[ScheduleEntry], str] | None = None,
    ) -> None:
        self.store = store
        self.runner = runner
        self.data_dir = data_dir
        self.record_action = record_action
        self.goal_binding_resolver = goal_binding_resolver
        self.restart_barrier = restart_barrier
        self.jobs_facts = jobs_facts
        self.subject_facts = subject_facts

    def _degrade(self, entry: ScheduleEntry, reason: str) -> bool:
        # EVO-20261007-8057c39a 案2: 降级通知携带再锚定 payload——sid/原因之外
        # 补齐原始调度规格（触发时刻/重复参数/max_count），下一会话可据此
        # re-issue schedule，原计划不再随降级丢失。
        reanchor = {
            "sid": entry.sid,
            "session_id": entry.session_id,
            "reason": reason,
            "message": entry.message,
            "trigger_at": getattr(entry, "trigger_at", None),
            "repeat_interval": getattr(entry, "repeat_interval", None),
            "max_count": getattr(entry, "max_count", None),
        }
        SchedulerThread._notify_via_interop(
            entry,
            data_dir=self.data_dir,
            wake_degraded_reason=reason,
            wake_degraded_payload=reanchor,
        )
        self.record_action(
            "schedule.wake", "degraded_to_notify",
            f"sid={entry.sid};reason={reason};notify_chars={len(entry.message) + 7}"
            ";prompt_chars=0;reanchor=1",
        )
        return True

    def _defer(self, entry: ScheduleEntry, reason: str) -> object:
        result = self.store.defer_wake_retry(entry.sid, owner=entry.lease_owner, reason=reason)
        if not result.present:
            return WAKE_DEFERRED
        if result.exhausted:
            return self._degrade(entry, reason + "_retry_cap")
        self.record_action(
            "schedule.wake", "deferred_retry",
            f"sid={entry.sid};reason={reason};retry_count={result.retry_count}"
            f";next_delay_s={result.next_delay_s:.0f}",
        )
        return WAKE_DEFERRED

    def __call__(self, entry: ScheduleEntry) -> object:
        if not entry.wake:
            SchedulerThread._notify_via_interop(entry, data_dir=self.data_dir)
            return True
        binding = wake_goal_binding_state(entry, self.goal_binding_resolver)
        if binding == "stale":
            self.store.cancel(entry.sid)
            self.record_action("schedule.wake", "goal_stale_noop", f"sid={entry.sid};prompt_chars=0")
            return WAKE_DEFERRED
        if binding == "unknown":
            return self._defer(entry, "goal_binding_unknown")
        grant = self.store.wake_grant(entry.sid)
        authority_state = self.store.authority_state(entry.sid)
        if grant is None and entry.wake_started_at <= 0:
            grant = self.store.recover_wake_grant(entry.sid)
        if grant is None or not entry.session_id:
            if entry.wake_started_at > 0 or authority_state in {"started", "revoked"} or (
                entry.wake_owner_pid == os.getpid() and authority_state != "pending"
            ):
                return self._degrade(entry, "grant_consumed_stale")
            # EVO-20261007-8057c39a 案1: grant 丢失且 ledger 恢复失败是确定性终态
            # (2026-10-07 双 sid 实证: 6 次退避 ~30 分钟无一自愈)。立即降级为
            # 通知并携带再锚定 payload,不再走瞬态退避路径。
            return self._degrade(entry, "grant_lost_owner_dead")
        if self.restart_barrier is not None:
            try:
                barrier = self.restart_barrier()
            except Exception:  # noqa: BLE001 - unreadable admission boundary cannot authorize a run
                return self._defer(entry, "restart_barrier_unavailable")
            if barrier is not None:
                return self._defer(entry, "service_restart_barrier")
        if not self.runner.enabled:
            return self._degrade(entry, "runner_disabled")
        prompt = f"[定时续跑·先前真人授权的程序委派·非新真人输入] {entry.message}"
        for facts in (
            _optional_facts(self.jobs_facts, entry.session_id),
            _optional_facts(self.subject_facts, entry),
        ):
            if facts:
                prompt += "\n" + facts
        admitted = threading.Event()

        def on_acquired(_session: Any) -> None:
            # Re-check lifecycle after a queued worker actually acquires the run.
            if wake_goal_binding_state(entry, self.goal_binding_resolver) not in {"active", "unbound"}:
                raise ValueError("wake Goal changed before admission")
            self.store.note_wake_started(entry.sid, owner=entry.lease_owner)
            admitted.set()
            self.store.mark_triggered(entry.sid, owner=entry.lease_owner)
            self.record_action(
                "schedule.wake", "started",
                f"sid={entry.sid};session={entry.session_id};delegated=1",
            )

        def terminal(status: str, _detail: str | None) -> None:
            if admitted.is_set():
                return
            reason = "session_busy" if status == "not_started" else "runner_admission_failed"
            outcome = self._defer(entry, reason)
            if outcome is True:
                self.store.mark_triggered(entry.sid)

        # Set queued while retaining the claim; a local handle is not a started run.
        self.store.note_wake_waiting(entry.sid, "awaiting_run_admission")
        try:
            handle, _queue = self.runner.start(
                entry.session_id, prompt, ingress=grant,
                before_start=on_acquired, terminal_callback=terminal,
            )
        except Exception:  # noqa: BLE001 - start rejection retains the unconsumed wake
            logger.warning("wake admission rejected sid=%s", entry.sid, exc_info=True)
            return self._defer(entry, "runner_admission_failed")
        if handle is None:
            busy = self.runner.is_running(entry.session_id) or self.runner.is_sync_active(entry.session_id)
            return self._defer(entry, "session_busy" if busy else "runner_unavailable")
        # Callback acknowledges only after real admission. Cross-process busy/error
        # callbacks requeue without setting started or spending the one-shot grant.
        return WAKE_DEFERRED
