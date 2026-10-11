"""基础工具: wait 只读墙钟等待原语（E5, EVO-20261012-65475c5a）.

问题背景（全部有工具回执实测）：
- child 无任何墙钟等待原语：execute_command(sleep) 被 run-lease fence 全量拒绝；
- child 存活 = 每轮至少一次工具调用，自然轮转 ≈10–15s/轮、每轮 ≈16K in，
  Mode-L 空闲成本 ≈64–96K in/min（v2 §2.2），心跳房间被迫降为特例。

本工具提供确定性只读等待：
- 等待期间不产生任何模型调用，token 成本为零；
- 父会话取消（cancel_event）在 ≤0.5s 内唤醒并如实返回；
- 单次上限 120s、每 child 会话累计上限 600s（租约窗口内防借等待变相长驻）。
"""

from __future__ import annotations

import time

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import child_cancel_event, child_wait_budget_used

MAX_SINGLE_WAIT_S = 120.0
MAX_TOTAL_WAIT_S = 600.0
_CANCEL_POLL_INTERVAL_S = 0.5


class WaitTool:
    name = "wait"
    # 等待时限由参数上限 + 累计预算自管（分片轮询 cancel），退出 registry 外层超时。
    registry_timeout_s = None
    description = (
        "只读等待：确定性阻塞 seconds 秒（1..120）后再返回。"
        "何时用: 子代理任务处于等待期（心跳/轮询/等父指令/等外部事件窗口）时，"
        "用一次 wait 替代多轮空转工具调用——等待期间零模型调用、token 成本为零，"
        "父会话取消会在 0.5s 内提前唤醒。"
        "何时不用: 有实际工作可推进时（等待不产出任何结果）；父代理侧无需使用"
        "（父可继续决策，无强制轮转成本）。"
        "预算: 单次 ≤120s；每 child 会话累计 ≤600s，超限拒绝并告知剩余额度。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "seconds": {
                "type": "number",
                "description": "等待秒数，1..120（上限内确定性阻塞；等待中零模型调用）",
            },
        },
        "required": ["seconds"],
    }

    def execute(self, **kwargs) -> ToolResult:
        raw = kwargs.get("seconds")
        try:
            seconds = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] seconds 需为数字（1..120）",
                tool_call_id="",
                tool_name=self.name,
            )
        if seconds != seconds or seconds in (float("inf"), float("-inf")):  # NaN/inf
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] seconds 需为有限数字（1..120）",
                tool_call_id="",
                tool_name=self.name,
            )
        if seconds < 1.0 or seconds > MAX_SINGLE_WAIT_S:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    f"[参数错误] seconds 超出单次上限：{seconds} 不在 "
                    f"[1, {MAX_SINGLE_WAIT_S:.0f}] 内"
                ),
                tool_call_id="",
                tool_name=self.name,
            )

        used = float(child_wait_budget_used.get())
        remaining = MAX_TOTAL_WAIT_S - used
        if seconds > remaining:
            return ToolResult(
                status=ToolResultStatus.BLOCKED,
                content=(
                    f"[状态: blocked] 本会话累计等待预算不足：已用 {used:.0f}s / "
                    f"{MAX_TOTAL_WAIT_S:.0f}s，剩余 {max(0.0, remaining):.0f}s < 请求 "
                    f"{seconds:.0f}s。等待不能替代任务推进：请直接执行下一步动作，"
                    "或按任务书说明结束/汇报。"
                ),
                tool_call_id="",
                tool_name=self.name,
            )

        deadline = time.monotonic() + seconds
        cancelled = False
        while True:
            ev = child_cancel_event.get()
            if ev is not None and getattr(ev, "is_set", lambda: False)():
                cancelled = True
                break
            now = time.monotonic()
            if now >= deadline:
                break
            time.sleep(min(_CANCEL_POLL_INTERVAL_S, max(0.0, deadline - now)))

        waited = seconds - max(0.0, deadline - time.monotonic())
        child_wait_budget_used.set(used + waited)
        if cancelled:
            return ToolResult(
                status=ToolResultStatus.BLOCKED,
                content=(
                    f"[状态: cancelled] 父会话已请求停止，wait 提前唤醒"
                    f"（请求 {seconds:.0f}s，实际 {waited:.1f}s）。请立即收尾并如实汇报。"
                ),
                tool_call_id="",
                tool_name=self.name,
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                f"[状态: success] wait 完成：请求 {seconds:.0f}s，实际 {waited:.1f}s"
                f"（本会话累计 {used + waited:.0f}s / {MAX_TOTAL_WAIT_S:.0f}s）。"
                "等待期间未产生模型调用；醒来后请继续推进任务。"
            ),
            tool_call_id="",
            tool_name=self.name,
        )
