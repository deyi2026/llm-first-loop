"""M2：已提交输入提交桥接与三能力控制（`T-M2-1` / `T-M2-2`）。

对应需求：`RTM-INP-01/02/06/07/09`、`RTM-AUD-07`、`RTM-STP-01/02/03/04/05/06/07`、
`RTM-TOL-10`、`RTM-SES-07`、`RTM-SCN-02`。

不变量：

- **只提交 `committed` 输入**（其 `final` 来自高精度终稿），临时字幕/`delta` 永不进队列；
- 已提交输入**恰一次**进队列（按 `session_id + turn_id` 去重，重复返回已知状态）；
- **分级回执**：`received` / `applied` / `denied`（复用既有回执挂点语义）；
- 三能力：`query_task`（先拉真实状态）、`submit_correction`（精确代次、冲突 409）、
  `request_cancel`（精确代次 + 如实终态）；
- **三类停止分离**：本地停播 / 回复取消 / 任务取消，**不合并**、不谎称撤销已完成部分；
- 桥接面**收敛为 4 能力**（提交任务/查询状态/提交纠正/请求取消），不灌全仓 schema。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from llm_loop.realtime.turn_aggregator import TurnIntent


class ReceiptStage(StrEnum):
    """分级回执：已接收 / 已生效 / 被拒。"""

    RECEIVED = "received"
    APPLIED = "applied"
    DENIED = "denied"


@dataclass(frozen=True)
class Receipt:
    stage: ReceiptStage
    reason: str = ""
    run_generation: str = ""
    task_ref: str = ""
    duplicate: bool = False


@dataclass(frozen=True)
class CommittedInput:
    """已提交轮次（来自 `TurnAggregator.commit`）；`final` 来自高精度终稿。"""

    turn_id: str
    text: str
    intent: TurnIntent
    run_generation: str = ""
    precision_notice: str = ""

    @property
    def degraded(self) -> bool:
        """降级标识：保守终稿（精度受限）如实标注（`RTM-INP-07`）。"""
        return bool(self.precision_notice)


@dataclass(frozen=True)
class SubmitOutcome:
    accepted: bool
    receipt: Receipt
    dispatched_to: str = ""


class QueueBackend(Protocol):
    """复用既有队列/Runner 的提交面（`human_turn_queue.py` / `runner.py`）。"""

    def has_active_run(self, session_id: str) -> bool: ...

    def enqueue(self, *, session_id: str, run_generation: str, turn_id: str, text: str) -> str: ...

    def interject(self, *, session_id: str, run_generation: str, turn_id: str, text: str) -> str: ...

    def start_task(self, *, session_id: str, turn_id: str, text: str) -> str: ...


class CommittedInputBridge:
    """已提交输入 → 既有队列/引擎；**恰一次**、分级回执、降级如实。"""

    def __init__(self, backend: QueueBackend, *, max_tracked: int = 1024) -> None:
        if isinstance(max_tracked, bool) or not isinstance(max_tracked, int) or max_tracked < 1:
            raise ValueError("max_tracked must be a positive integer")
        self._backend = backend
        self._max_tracked = max_tracked
        # 有界（LRU）：去重记录不得无界增长（RTM-LIF-05）
        self._submitted: OrderedDict[tuple[str, str], SubmitOutcome] = OrderedDict()

    def submit(self, session_id: str, committed: CommittedInput) -> SubmitOutcome:
        """提交已提交轮次；重复提交返回**已知状态**（不重复进队列）。"""
        if not isinstance(committed, CommittedInput):
            raise TypeError("committed must be CommittedInput")
        key = (session_id, committed.turn_id)
        existing = self._submitted.get(key)
        if existing is not None:
            return SubmitOutcome(
                accepted=existing.accepted,
                receipt=Receipt(
                    stage=existing.receipt.stage,
                    reason="already_submitted",
                    run_generation=existing.receipt.run_generation,
                    task_ref=existing.receipt.task_ref,
                    duplicate=True,
                ),
                dispatched_to=existing.dispatched_to,
            )
        outcome = self._dispatch(session_id, committed)
        self._submitted[key] = outcome
        while len(self._submitted) > self._max_tracked:
            self._submitted.popitem(last=False)  # 淘汰最旧，防无界增长
        return outcome

    def _dispatch(self, session_id: str, committed: CommittedInput) -> SubmitOutcome:
        if committed.intent is TurnIntent.CORRECTION:
            if not committed.run_generation:
                return SubmitOutcome(
                    accepted=False,
                    receipt=Receipt(ReceiptStage.DENIED, reason="correction_requires_run_generation"),
                )
            if not self._backend.has_active_run(session_id):
                return SubmitOutcome(
                    accepted=False,
                    receipt=Receipt(ReceiptStage.DENIED, reason="no_active_run_to_correct"),
                )
            task_ref = self._backend.interject(
                session_id=session_id,
                run_generation=committed.run_generation,
                turn_id=committed.turn_id,
                text=committed.text,
            )
            return SubmitOutcome(
                accepted=True,
                receipt=Receipt(ReceiptStage.APPLIED, run_generation=committed.run_generation, task_ref=task_ref),
                dispatched_to="interject",
            )

        if committed.intent is TurnIntent.DIALOGUE:
            return SubmitOutcome(
                accepted=True,
                receipt=Receipt(ReceiptStage.RECEIVED, run_generation=committed.run_generation),
                dispatched_to="dialogue",
            )

        # TASK_SUBMIT / QUERY → 提交任务（活动 Run 存在时插话，否则新任务）
        if self._backend.has_active_run(session_id):
            task_ref = self._backend.interject(
                session_id=session_id,
                run_generation=committed.run_generation,
                turn_id=committed.turn_id,
                text=committed.text,
            )
            return SubmitOutcome(
                accepted=True,
                receipt=Receipt(ReceiptStage.APPLIED, run_generation=committed.run_generation, task_ref=task_ref),
                dispatched_to="interject",
            )
        task_ref = self._backend.start_task(session_id=session_id, turn_id=committed.turn_id, text=committed.text)
        return SubmitOutcome(
            accepted=True,
            receipt=Receipt(ReceiptStage.APPLIED, task_ref=task_ref),
            dispatched_to="start_task",
        )


class StopKind(StrEnum):
    LOCAL_PLAYBACK = "local_playback"
    REPLY_CANCEL = "reply_cancel"
    TASK_CANCEL = "task_cancel"


@dataclass(frozen=True)
class StopSettlement:
    """三类停止**分离**结算：各自状态独立，不合并语义。"""

    local_playback: str
    reply_cancel: str
    task_cancel: str

    def requested_only(self) -> bool:
        """全部仅为「已请求」、尚无完成确认时为 True（不得谎称已完成）。"""
        return all(
            value in ("requested", "not_applicable")
            for value in (self.local_playback, self.reply_cancel, self.task_cancel)
        )


class CancelDisposition(StrEnum):
    REQUESTED = "requested"
    COMPLETED = "completed"
    CONFLICT = "conflict"  # 代次不符 → 409
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class CancelResult:
    disposition: CancelDisposition
    run_generation: str = ""
    terminal_state: str = ""
    detail: str = ""


class TaskControlBackend(Protocol):
    """精确代次操作面（复用 `chat_cancel` / `queue_interject` 语义）。"""

    def task_state(self, session_id: str) -> dict: ...

    def cancel(self, *, session_id: str, expected_run_generation: str) -> tuple[str, str]: ...


class TaskController:
    """查询 / 纠正 / 取消三能力；桥接面**收敛**，不灌全仓 schema（`RTM-TOL-10`）。"""

    def __init__(self, backend: TaskControlBackend, *, interjector: QueueBackend | None = None) -> None:
        self._backend = backend
        self._interjector = interjector

    def query_task(self, session_id: str, *, run_generation: str | None = None) -> dict:
        """先拉**真实状态**，不自动重发、不替模型臆断。"""
        state = self._backend.task_state(session_id)
        if run_generation is not None:
            state = {**state, "queried_run_generation": run_generation}
        return state

    def submit_correction(
        self, session_id: str, *, run_generation: str, turn_id: str, text: str
    ) -> Receipt:
        """精确代次插话，**下一安全边界采用**；无活动 Run 或代次不符 → 拒绝/409 语义。"""
        if self._interjector is None:
            return Receipt(ReceiptStage.DENIED, reason="interject_unavailable")
        actual = self._backend.task_state(session_id).get("run_generation", "")
        if actual and run_generation and actual != run_generation:
            return Receipt(ReceiptStage.DENIED, reason="run_generation_conflict", run_generation=run_generation)
        if not self._interjector.has_active_run(session_id):
            return Receipt(ReceiptStage.DENIED, reason="no_active_run")
        task_ref = self._interjector.interject(
            session_id=session_id, run_generation=run_generation, turn_id=turn_id, text=text
        )
        return Receipt(ReceiptStage.APPLIED, run_generation=run_generation, task_ref=task_ref)

    def request_cancel(self, session_id: str, *, run_generation: str) -> CancelResult:
        """精确取消：代次不符 → `CONFLICT`（409）；终态**如实报告**。"""
        if not run_generation:
            return CancelResult(CancelDisposition.NOT_FOUND, detail="missing_run_generation")
        try:
            status, terminal = self._backend.cancel(session_id=session_id, expected_run_generation=run_generation)
        except KeyError:
            return CancelResult(CancelDisposition.NOT_FOUND, run_generation=run_generation)
        if status == "conflict":
            return CancelResult(CancelDisposition.CONFLICT, run_generation=run_generation, terminal_state=terminal)
        return CancelResult(CancelDisposition.COMPLETED, run_generation=run_generation, terminal_state=terminal)


def settle_three_stops(
    *, local_playback: str, reply_cancel: str, task_cancel: str
) -> StopSettlement:
    """三类停止**分离**结算（`RTM-STP-01/02/06`）；歧义不扩大（`RTM-STP-05`）。"""
    return StopSettlement(
        local_playback=local_playback,
        reply_cancel=reply_cancel,
        task_cancel=task_cancel,
    )
