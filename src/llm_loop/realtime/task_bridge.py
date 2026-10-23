"""T-CONTRACT-1 / T-CONTRACT-2：唯一执行链、双层调用关联与工具幂等。

对应需求：`RTM-TOL-01/02/03/04/05/06/08/16`、`RTM-REC-02/06`、`RTM-IDN-01`、`RTM-CMP-01/02`。

不变量（`DESIGN v1.3 §2.1.3-C/§2.2.2-C`、D18–D20）：

- **唯一执行链**：桥接只做「确认归属 → 关联代次 → 原子认领 → 提交任务 / 由引擎派发」，
  **不直连工具管线**；工具执行**只发生在引擎内**（浏览器/桥接无并列执行权）。
- **双层调用关联**：外层（`tool_call_id` + `turn_id`）↔ 内层（`engine_execution_id` + `round`）
  **显式绑定**，防止两条来源被误当同一调用。
- **稳定去重键**：`call_key` 由 Provider/桥接调用标识派生，**禁用参数哈希**
  （合法相同参数的**新轮次**不得被永久黑名单误拦，`RTM-TOL-06`）。
- **原子认领**：派发前以唯一稳定键**条件写入**认领记录，写成功才派发；
  同键重复到达返回**已知状态、不重派**（`RTM-TOL-04/05`）。
- **重启恢复**：先读认领记录，`claimed` → 已知状态且**不重派**；`not_claimed` 才进入正常派发。
- **崩溃窗口**显式 `outcome_unknown`，**先核远端事实、禁止盲重试**（`RTM-TOL-07/08`、`RTM-REC-02`）。

本模块只做机械事实与边界（归属、代次、唯一键、状态），不做语义判断。
首版单进程使用本进程锁；事实底座可与现有 `ToolExecutionJournal` 衔接（协议注入）。
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def _identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _NAME_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a non-empty, bounded identifier")


class ToolCallState(StrEnum):
    """工具调用状态（复用既有执行事实表达，`RTM-TOL-02`）。"""

    REQUESTED = "requested"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    OUTCOME_UNKNOWN = "outcome_unknown"


_TERMINAL_STATES = frozenset(
    {ToolCallState.SUCCEEDED, ToolCallState.FAILED, ToolCallState.CANCELLED, ToolCallState.OUTCOME_UNKNOWN}
)


def make_call_key(*, media_session_id: str, turn_id: str, tool_call_id: str) -> str:
    """生成**稳定去重键**。

    键由 Provider/桥接**调用标识 + 轮次**派生——**不**包含工具参数内容，因此
    **不是参数哈希**：不同轮次中相同参数的合法新调用不会被永久误拦（`RTM-TOL-06`）。
    """
    for name, value in (
        ("media_session_id", media_session_id),
        ("turn_id", turn_id),
        ("tool_call_id", tool_call_id),
    ):
        _identifier(name, value)
    return f"call:{media_session_id}:{turn_id}:{tool_call_id}"


@dataclass(frozen=True)
class ToolCallMapping:
    """桥接调用映射（外层 ↔ 内层）。"""

    call_key: str
    media_session_id: str
    session_id: str
    turn_id: str
    tool_call_id: str
    tool_name: str
    run_generation: str
    origin: str = "bridge_committed"
    engine_execution_id: str = ""
    round_no: int | None = None

    def __post_init__(self) -> None:
        for name in ("media_session_id", "session_id", "turn_id", "tool_call_id", "tool_name", "run_generation"):
            _identifier(name, getattr(self, name))
        if not isinstance(self.call_key, str) or not self.call_key:
            raise ValueError("call_key must be a non-empty string")
        if self.round_no is not None and (
            isinstance(self.round_no, bool) or not isinstance(self.round_no, int) or self.round_no < 0
        ):
            raise ValueError("round_no must be a non-negative integer or None")

    def with_engine_binding(self, *, engine_execution_id: str, round_no: int) -> ToolCallMapping:
        """显式绑定内层（引擎执行标识 + 轮次），保持外层不变。"""
        if not engine_execution_id:
            raise ValueError("engine_execution_id is required")
        if isinstance(round_no, bool) or not isinstance(round_no, int) or round_no < 0:
            raise ValueError("round_no must be a non-negative integer")
        return ToolCallMapping(
            call_key=self.call_key,
            media_session_id=self.media_session_id,
            session_id=self.session_id,
            turn_id=self.turn_id,
            tool_call_id=self.tool_call_id,
            tool_name=self.tool_name,
            run_generation=self.run_generation,
            origin=self.origin,
            engine_execution_id=engine_execution_id,
            round_no=round_no,
        )


@dataclass(frozen=True)
class ClaimRecord:
    mapping: ToolCallMapping
    state: ToolCallState


@dataclass(frozen=True)
class ClaimOutcome:
    claimed: bool
    record: ClaimRecord


class ToolCallClaimStore(Protocol):
    """认领记录存储契约（可与 `ToolExecutionJournal` 衔接）。"""

    def claim_if_absent(self, mapping: ToolCallMapping) -> ClaimOutcome: ...

    def lookup(self, call_key: str) -> ClaimRecord | None: ...

    def mark(
        self, call_key: str, state: ToolCallState, *, engine_execution_id: str = "", round_no: int | None = None
    ) -> ClaimRecord: ...


class InMemoryClaimStore:
    """首版单进程认领记录（本进程锁保证**原子认领**）。

    跨进程/崩溃窗口另由持久层承担；若持久层不能跨外部副作用原子提交，崩溃窗口必须
    表达为 `outcome_unknown`（不承诺恰好一次）。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, ClaimRecord] = {}

    def claim_if_absent(self, mapping: ToolCallMapping) -> ClaimOutcome:
        if not isinstance(mapping, ToolCallMapping):
            raise TypeError("mapping must be ToolCallMapping")
        with self._lock:
            existing = self._records.get(mapping.call_key)
            if existing is not None:
                # 已认领：返回**已知状态**，不重复派发。
                return ClaimOutcome(claimed=False, record=existing)
            record = ClaimRecord(mapping=mapping, state=ToolCallState.CLAIMED)
            self._records[mapping.call_key] = record
            return ClaimOutcome(claimed=True, record=record)

    def lookup(self, call_key: str) -> ClaimRecord | None:
        with self._lock:
            return self._records.get(call_key)

    def mark(
        self, call_key: str, state: ToolCallState, *, engine_execution_id: str = "", round_no: int | None = None
    ) -> ClaimRecord:
        if not isinstance(state, ToolCallState):
            raise TypeError("state must be ToolCallState")
        with self._lock:
            record = self._records.get(call_key)
            if record is None:
                raise KeyError(f"unknown call_key: {call_key}")
            mapping = record.mapping
            if engine_execution_id or round_no is not None:
                mapping = mapping.with_engine_binding(
                    engine_execution_id=engine_execution_id or mapping.engine_execution_id,
                    round_no=mapping.round_no if round_no is None else round_no,
                )
            updated = ClaimRecord(mapping=mapping, state=state)
            self._records[call_key] = updated
            return updated


class TaskSubmitter(Protocol):
    """任务提交面（复用现有队列/Runner）；桥接**只提交任务**。"""

    def submit(self, *, session_id: str, run_generation: str, turn_id: str, text: str) -> str: ...


class EngineToolDispatcher(Protocol):
    """引擎内工具派发面；**唯一执行入口**，返回真实回执。"""

    def dispatch_once(self, mapping: ToolCallMapping) -> EngineDispatchResult: ...


@dataclass(frozen=True)
class EngineDispatchResult:
    """引擎派发的真实回执。"""

    execution_id: str
    round_no: int
    state: ToolCallState

    def __post_init__(self) -> None:
        if not self.execution_id:
            raise ValueError("execution_id is required")
        if not isinstance(self.state, ToolCallState):
            raise TypeError("state must be ToolCallState")


@dataclass(frozen=True)
class ToolDispatchRequest:
    """桥接编排发起的工具调用请求（基于 `committed` 输入，`RTM-TOL-16`）。"""

    media_session_id: str
    session_id: str
    turn_id: str
    tool_call_id: str
    tool_name: str
    run_generation: str

    @property
    def call_key(self) -> str:
        return make_call_key(
            media_session_id=self.media_session_id,
            turn_id=self.turn_id,
            tool_call_id=self.tool_call_id,
        )

    def to_mapping(self) -> ToolCallMapping:
        return ToolCallMapping(
            call_key=self.call_key,
            media_session_id=self.media_session_id,
            session_id=self.session_id,
            turn_id=self.turn_id,
            tool_call_id=self.tool_call_id,
            tool_name=self.tool_name,
            run_generation=self.run_generation,
        )


@dataclass(frozen=True)
class ToolDispatchResult:
    dispatched: bool
    state: ToolCallState
    record: ClaimRecord | None = None
    reason: str = ""


@dataclass(frozen=True)
class SubmissionReceipt:
    accepted: bool
    task_ref: str = ""


@dataclass(frozen=True)
class ToolCallResume:
    """重启恢复结果：`claimed` → 已知状态且**不重派**。"""

    exists: bool
    state: ToolCallState | None
    record: ClaimRecord | None
    redispatch: bool = False


class TaskBridge:
    """唯一执行链编排（桥接只提交任务 / 由引擎派发工具）。"""

    def __init__(
        self,
        *,
        claim_store: ToolCallClaimStore,
        engine: EngineToolDispatcher,
        submitter: TaskSubmitter,
        ownership_check: object | None = None,
        authorize: object | None = None,
        budget_admit: object | None = None,
        notifier: object | None = None,
    ) -> None:
        self._claims = claim_store
        self._engine = engine
        self._submitter = submitter
        self._ownership_check = ownership_check
        self._authorize = authorize
        self._budget_admit = budget_admit
        self._notifier = notifier

    def submit_committed_input(
        self, *, session_id: str, run_generation: str, turn_id: str, text: str
    ) -> SubmissionReceipt:
        """只提交任务（不在此处派发任何工具；工具由引擎在任务内执行）。"""
        task_ref = self._submitter.submit(
            session_id=session_id, run_generation=run_generation, turn_id=turn_id, text=text
        )
        return SubmissionReceipt(accepted=True, task_ref=str(task_ref or ""))

    def dispatch_tool(self, request: ToolDispatchRequest) -> ToolDispatchResult:
        """唯一工具执行入口；执行顺序：归属 → 代次 → 原子认领 → 授权/预算 → 引擎派发一次 → 记录。"""
        if self._ownership_check is not None and not self._ownership_check(  # type: ignore[operator]
            request.session_id, request.turn_id
        ):
            # 归属未通过：**不认领、不写 store**（避免游离记录误导恢复）
            return ToolDispatchResult(dispatched=False, state=ToolCallState.FAILED, record=None, reason="not_owned")

        mapping = request.to_mapping()
        outcome = self._claims.claim_if_absent(mapping)
        if not outcome.claimed:
            # 同键重复到达：返回已知状态，**不重派**。
            return ToolDispatchResult(
                dispatched=False, state=outcome.record.state, record=outcome.record, reason="already_claimed"
            )

        if self._authorize is not None and not self._authorize(mapping):  # type: ignore[operator]
            record = self._claims.mark(mapping.call_key, ToolCallState.FAILED)
            return ToolDispatchResult(dispatched=False, state=record.state, record=record, reason="not_authorized")
        if self._budget_admit is not None and not self._budget_admit(mapping):  # type: ignore[operator]
            record = self._claims.mark(mapping.call_key, ToolCallState.FAILED)
            return ToolDispatchResult(dispatched=False, state=record.state, record=record, reason="budget_stop")

        running = self._claims.mark(mapping.call_key, ToolCallState.RUNNING)
        try:
            result = self._engine.dispatch_once(running.mapping)
        except Exception:  # noqa: BLE001 - 崩溃/异常窗口表达为未确认，禁止盲重试
            record = self._claims.mark(mapping.call_key, ToolCallState.OUTCOME_UNKNOWN)
            return ToolDispatchResult(
                dispatched=True, state=record.state, record=record, reason="outcome_unknown"
            )

        record = self._claims.mark(
            mapping.call_key,
            result.state,
            engine_execution_id=result.execution_id,
            round_no=result.round_no,
        )
        if self._notifier is not None:
            self._notifier(record)  # type: ignore[operator]
        return ToolDispatchResult(dispatched=True, state=record.state, record=record)

    def resume_call(self, call_key: str) -> ToolCallResume:
        """重启恢复：先读认领记录；`claimed` → 已知状态且**不重派**。"""
        record = self._claims.lookup(call_key)
        if record is None:
            return ToolCallResume(exists=False, state=None, record=None, redispatch=False)
        return ToolCallResume(exists=True, state=record.state, record=record, redispatch=False)

    @staticmethod
    def is_terminal(state: ToolCallState) -> bool:
        return state in _TERMINAL_STATES
