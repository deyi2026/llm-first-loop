"""M2：桥接编排发起的只读工具闭环（`T-M2-3`）。

对应需求：`RTM-TOL-09/10/11/12/16`、`RTM-EVD-02`。

不变量（`DESIGN v1.3 §2.1.3-C`、D25）：

- 工具调用由**桥接基于 `committed` 输入编排发起**，仍经 `TaskBridge.dispatch_tool`
  **唯一服务端入口**；浏览器/桥接**无并列执行权**；
- 桥接面**收敛为少量能力**（提交任务/查询状态/提交纠正/请求取消），
  **不把全仓工具 schema 灌入实时模型**（`RTM-TOL-10`）；
- **只有收到真实 LFL 回执才播报**（禁用假工具回包）；读取值 ≠ 写入值即失败；
- 旧结果仍写原任务记录（`RTM-TOL-11/12`）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from llm_loop.realtime.task_bridge import (
    TaskBridge,
    ToolCallState,
    ToolDispatchRequest,
    ToolDispatchResult,
)

FIRST_RELEASE_ALLOWED_TOOLS: frozenset[str] = frozenset({"read_file"})


@dataclass(frozen=True)
class ToolCallPlan:
    """桥接编排计划（基于 `committed` 输入）。首版仅只读 `read_file`。"""

    media_session_id: str
    session_id: str
    turn_id: str
    tool_call_id: str
    tool_name: str
    run_generation: str
    arguments: dict[str, object] = field(default_factory=dict)

    def to_request(self) -> ToolDispatchRequest:
        return ToolDispatchRequest(
            media_session_id=self.media_session_id,
            session_id=self.session_id,
            turn_id=self.turn_id,
            tool_call_id=self.tool_call_id,
            tool_name=self.tool_name,
            run_generation=self.run_generation,
        )


class ModelVetoable(Protocol):
    """编排可被模型 veto：工具不可用时如实不执行，不静默伪造。"""

    def allow(self, plan: ToolCallPlan) -> bool: ...


class ToolOrchestrator:
    """把 `committed` 输入编排为**唯一入口**的工具调用。"""

    def __init__(
        self,
        bridge: TaskBridge,
        *,
        allowed_tools: frozenset[str] = FIRST_RELEASE_ALLOWED_TOOLS,
        veto: ModelVetoable | None = None,
        record_legacy_result: Callable[[ToolDispatchResult], None] | None = None,
    ) -> None:
        self._bridge = bridge
        self._allowed = allowed_tools
        self._veto = veto
        self._record_legacy = record_legacy_result

    def initiate(self, plan: ToolCallPlan) -> ToolDispatchResult:
        """经唯一入口派发；越出收敛能力集 / 模型 veto → 不派发（不写 store）。"""
        if plan.tool_name not in self._allowed:
            return ToolDispatchResult(
                dispatched=False, state=ToolCallState.FAILED, record=None, reason="tool_not_in_bridge_surface"
            )
        if self._veto is not None and not self._veto.allow(plan):
            return ToolDispatchResult(
                dispatched=False, state=ToolCallState.CANCELLED, record=None, reason="vetoed"
            )
        result = self._bridge.dispatch_tool(plan.to_request())
        if self._record_legacy is not None:
            self._record_legacy(result)  # 旧结果仍写原任务记录
        return result

    def announce(
        self, result: ToolDispatchResult, *, announce: Callable[[str], None]
    ) -> bool:
        """**仅真实 LFL 回执**才播报；未派发/未确认 → 不播报，返回 False。"""
        if not result.dispatched:
            return False
        if result.state not in (ToolCallState.SUCCEEDED, ToolCallState.FAILED):
            return False  # outcome_unknown 等未确认状态不得谎称结果
        announce(result.state.value)
        return True
