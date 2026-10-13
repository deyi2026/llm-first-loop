"""Read-only bounded wait, optionally bound to an owned background job.

Job completion and run cancellation wake the current authorized run. This tool
does not create a continuation, infer task success, or restart an execution.
"""

from __future__ import annotations

import threading
import time

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import (
    WaitBudget,
    child_cancel_event,
    child_wait_budget_used,
    current_run_generation,
    current_session_id,
    current_wait_budget,
    current_wait_cancel_check,
)
from llm_loop.tools.builtin.job_registry import JobRegistry

MAX_SINGLE_WAIT_S = 120.0
MAX_TOTAL_WAIT_S = 600.0
_CANCEL_POLL_INTERVAL_S = 0.5


class WaitTool:
    name = "wait"
    registry_timeout_s = None
    description = (
        "只读有界等待，seconds 为 1..120。传 job_id 时等当前会话后台任务的进程终态，"
        "完成即提前返回；未完成则到超时返回当前状态。省略 job_id 时只等墙钟，"
        "不监视后台任务。回执给出 wake_reason、实际等待时长与累计；"
        "主会话 Stop 和父对子代理取消会提前唤醒。等待期间不调用模型；"
        "子代理累计租约预算仍为 600s，主会话仅记录本 run 累计、不设该租约上限。"
        "进程终态不代表任务验收通过，输出与退出码用 job_output 核验。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "seconds": {
                "type": "number",
                "description": "最大等待秒数，1..120；job 完成或取消可提前返回",
            },
            "job_id": {
                "type": "string",
                "description": "可选，当前会话后台启动回执中的 exact job_id；省略只等墙钟",
            },
        },
        "required": ["seconds"],
    }

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._active: dict[tuple[str, str], set[threading.Event]] = {}

    def terminate_session(self, session_id: str, *, run_generation: str = "") -> None:
        """Wake only matching active waits; never kills the observed background job."""
        with self._guard:
            for (sid, generation), events in self._active.items():
                if sid == session_id and (not run_generation or generation == run_generation):
                    for event in events:
                        event.set()

    @staticmethod
    def _terminal(snapshot: dict[str, object]) -> bool:
        state = snapshot.get("state")
        return state in {"completed", "failed"} or (
            state == "killed"
            and (snapshot.get("finished_at") is not None or snapshot.get("exit_code") is not None)
        )

    @staticmethod
    def _cancelled(stop: threading.Event) -> bool:
        child_event = child_cancel_event.get()
        checker = current_wait_cancel_check.get()
        return (
            stop.is_set()
            or bool(child_event is not None and getattr(child_event, "is_set", lambda: False)())
            or bool(checker is not None and checker())
        )

    def _pause(
        self, stop: threading.Event, completion: threading.Event | None, seconds: float,
    ) -> None:
        # Job exit gets an immediate local notification; cancellation remains bounded
        # even when a different Event is the one currently being waited on.
        (completion if completion is not None else stop).wait(seconds)

    def _result(self, status: ToolResultStatus, content: str, *, job_id: str = "") -> ToolResult:
        return ToolResult(
            status=status, content=content, tool_call_id="", tool_name=self.name,
            capability_requirements=("job_output",) if job_id else (),
        )

    @staticmethod
    def _accounting(carrier: WaitBudget | None, child: bool, total: float) -> str:
        if carrier is None:
            return "累计未绑定（无 run 上下文）"
        if child:
            return f"本会话累计 {total:.0f}s / {MAX_TOTAL_WAIT_S:.0f}s"
        return f"本 run 累计 {total:.0f}s；主会话无 child 租约上限"

    def execute(self, **kwargs) -> ToolResult:
        raw = kwargs.get("seconds")
        if raw is None:
            return self._result(ToolResultStatus.FAILURE, "[参数错误] seconds 需为数字（1..120）")
        try:
            seconds = float(raw)
        except (TypeError, ValueError, OverflowError):
            return self._result(ToolResultStatus.FAILURE, "[参数错误] seconds 需为数字（1..120）")
        if seconds != seconds or seconds in (float("inf"), float("-inf")):
            return self._result(ToolResultStatus.FAILURE, "[参数错误] seconds 需为有限数字（1..120）")
        if seconds < 1.0 or seconds > MAX_SINGLE_WAIT_S:
            return self._result(
                ToolResultStatus.FAILURE,
                f"[参数错误] seconds 超出单次上限：{seconds} 不在 [1, {MAX_SINGLE_WAIT_S:.0f}] 内",
            )
        raw_job = kwargs.get("job_id", "")
        if not isinstance(raw_job, str):
            return self._result(ToolResultStatus.FAILURE, "[参数错误] job_id 需为字符串")
        job_id = raw_job.strip()
        requester = current_session_id.get()
        generation = current_run_generation.get()
        child_carrier = child_wait_budget_used.get()
        child = isinstance(child_carrier, WaitBudget)
        carrier = child_carrier if child else current_wait_budget.get()
        snapshot: dict[str, object] | None = None
        completion = None
        if job_id:
            if not requester:
                return self._result(ToolResultStatus.FAILURE, "[任务不存在或无权访问] job_id=" + job_id)
            jobs = JobRegistry.instance()
            snapshot = jobs.snapshot(job_id, session_id=requester)
            if snapshot is None or snapshot.get("session_id") != requester:
                return self._result(ToolResultStatus.FAILURE, "[任务不存在或无权访问] job_id=" + job_id)
            completion = jobs.completion_event(job_id, session_id=requester)

        stop = threading.Event()
        key = (requester, generation)
        with self._guard:
            self._active.setdefault(key, set()).add(stop)
        start = time.monotonic()
        reserved = False
        total = carrier.used if isinstance(carrier, WaitBudget) else 0.0
        reason = "timeout" if job_id else "elapsed"
        status = ToolResultStatus.SUCCESS
        try:
            # A previously completed job needs no lease reservation or wall-clock wait.
            if self._cancelled(stop):
                reason, status = "cancelled", ToolResultStatus.BLOCKED
            elif snapshot is not None and self._terminal(snapshot):
                reason = "job_terminal"
            elif job_id and completion is None:
                reason, status = "job_unobservable", ToolResultStatus.FAILURE
            else:
                if isinstance(carrier, WaitBudget):
                    allowed, used, remaining = carrier.reserve(
                        seconds, MAX_TOTAL_WAIT_S if child else None,
                    )
                    if not allowed:
                        return self._result(
                            ToolResultStatus.BLOCKED,
                            f"[状态: blocked] 本会话累计等待预算不足：已用 {used:.0f}s / "
                            f"{MAX_TOTAL_WAIT_S:.0f}s，剩余 {max(0.0, remaining or 0.0):.0f}s "
                            f"< 请求 {seconds:.0f}s（含在途预留）。",
                            job_id=job_id,
                        )
                    reserved = True
                deadline = start + seconds
                while True:
                    if self._cancelled(stop):
                        reason, status = "cancelled", ToolResultStatus.BLOCKED
                        break
                    if job_id and completion is not None and completion.is_set():
                        snapshot = jobs.snapshot(job_id, session_id=requester)
                        if snapshot is None or snapshot.get("session_id") != requester:
                            reason, status = "job_unobservable", ToolResultStatus.FAILURE
                        else:
                            reason = "job_terminal" if self._terminal(snapshot) else "job_unobservable"
                            if reason == "job_unobservable":
                                status = ToolResultStatus.FAILURE
                        break
                    left = deadline - time.monotonic()
                    if left <= 0:
                        if job_id:
                            snapshot = jobs.snapshot(job_id, session_id=requester)
                            if snapshot is None or snapshot.get("session_id") != requester:
                                reason, status = "job_unobservable", ToolResultStatus.FAILURE
                            elif self._terminal(snapshot):
                                reason = "job_terminal"
                        break
                    self._pause(stop, completion, min(_CANCEL_POLL_INTERVAL_S, left))
        finally:
            waited = min(seconds, max(0.0, time.monotonic() - start))
            if reserved and isinstance(carrier, WaitBudget):
                total = carrier.settle(seconds, waited)
            with self._guard:
                events = self._active.get(key)
                if events is not None:
                    events.discard(stop)
                    if not events:
                        self._active.pop(key, None)

        facts = ""
        if job_id and snapshot is not None:
            facts = (
                f"; job_id={job_id}; state={snapshot.get('state')}; exit={snapshot.get('exit_code')}"
                f"; local_handle={str(bool(snapshot.get('local_handle'))).lower()}"
                f"; state_durable={str(bool(snapshot.get('state_durable'))).lower()}"
            )
        return self._result(
            status,
            f"[状态: {reason}] wait 返回：wake_reason={reason}{facts}；"
            f"请求 {seconds:.0f}s，实际 {waited:.1f}s"
            f"（{self._accounting(carrier if isinstance(carrier, WaitBudget) else None, child, total)}）。"
            "等待期间未产生模型调用。",
            job_id=job_id,
        )
