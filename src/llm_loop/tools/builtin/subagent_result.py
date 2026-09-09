"""读取/等待 nonblocking subagent handle 的运行状态与最终结果。"""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus


class SubAgentResultTool:
    """父代理唯一的 child handle 查询/await 操作。"""

    name = "subagent_result"
    # wait_seconds 被限制到 <=30s，给 registry 外层留出清理余量。
    registry_timeout_s = 35.0
    description = (
        "查询或短暂等待自己直接 child 的状态/中途报告/最终结果。"
        "spawn_subagent 返回 child_id 后使用；wait_seconds=0 为立即查询，>0 最多等待 30 秒。"
        "child_state=running 时父代理仍可 agent_message 中途 steer；"
        "只有 child_outcome=completed 才代表子任务成功完成。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "child_id": {
                "type": "string",
                "description": "spawn_subagent 返回的直接 child_id",
            },
            "wait_seconds": {
                "type": "number",
                "minimum": 0,
                "maximum": 30,
                "description": "可选等待秒数，0=立即查询，最大 30；等待超时仍返回当前 running 状态",
            },
        },
        "required": ["child_id"],
    }

    def __init__(self, runner) -> None:
        self._runner = runner

    def execute(self, **kwargs) -> ToolResult:
        child_id = str(kwargs.get("child_id", "") or "").strip()
        raw_wait = kwargs.get("wait_seconds", 0)
        try:
            wait_seconds = float(raw_wait or 0)
        except (TypeError, ValueError):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] wait_seconds 必须是 0..30 的数字",
                tool_call_id="",
                tool_name=self.name,
            )
        if wait_seconds < 0:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] wait_seconds 不能为负数",
                tool_call_id="",
                tool_name=self.name,
            )

        ok, detail, snapshot = self._runner.result_current(child_id, wait_seconds)
        if not ok:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[状态: failure] subagent_result: {detail}",
                tool_call_id="",
                tool_name=self.name,
            )

        state = str(snapshot.get("state", "running"))
        depth = int(snapshot.get("depth", 0) or 0)
        reports = list(snapshot.get("reports") or [])
        cancel_requested = bool(snapshot.get("cancel_requested"))
        if state in {"running", "orphaned"}:
            parts = [
                f"[状态: success] child_state={state} child_id={child_id} depth={depth} "
                f"cancel_requested={str(cancel_requested).lower()}",
            ]
            if reports:
                parts.append(f"[中途报告 {len(reports)} 条]")
                for report in reports[-5:]:
                    parts.append(f"  - {str(report)[:300]}")
            if state == "running":
                parts.append(
                    "child 尚未结算；可继续父级工作、agent_message steer，或稍后再次查询。"
                )
            else:
                parts.append(
                    "child 当前无本进程 active worker；以上仅为durable状态/报告读取，"
                    "不代表子任务完成，也不会自动恢复执行。"
                )
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="\n".join(parts),
                tool_call_id="",
                tool_name=self.name,
            )

        result = snapshot.get("result")
        if result is None:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[状态: error] child_state={state} 但终态结果缺失",
                tool_call_id="",
                tool_name=self.name,
            )

        outcome = str(getattr(result, "outcome", state) or state)
        status = ToolResultStatus.SUCCESS if outcome == "completed" else ToolResultStatus.FAILURE
        parts = [
            f"[状态: {status.value}] child_state={state} child_outcome={outcome} "
            f"child_id={child_id} depth={getattr(result, 'depth', depth)} "
            f"rounds={getattr(result, 'rounds', 0)} tools={len(getattr(result, 'tool_calls', []) or [])} "
            f"tokens_in={getattr(result, 'tokens_in', 0)} tokens_out={getattr(result, 'tokens_out', 0)}",
        ]
        result_reports = list(getattr(result, "reports", []) or [])
        if result_reports:
            parts.append(f"[中途报告 {len(result_reports)} 条]")
            for report in result_reports[-5:]:
                parts.append(f"  - {str(report)[:300]}")
        trace = list(getattr(result, "tool_calls", []) or [])
        if trace:
            parts.append(
                "[工具轨迹] "
                + ", ".join(
                    f"{item.get('name', '?')}:{item.get('status', '?')}" for item in trace[:10]
                )
            )
        parts.append("[子代理回答]")
        parts.append(str(getattr(result, "final_answer", "") or ""))
        nested_success = tuple(
            f"{item.get('name', '?')}:success"
            for item in trace
            if str(item.get("status", "")).lower() == "success"
        )
        parent_id = str(snapshot.get("parent_id") or "")
        generation = str(snapshot.get("generation") or "")
        result_id = str(snapshot.get("result_id") or "")
        binding = (
            {
                "child_id": child_id,
                "parent_id": parent_id,
                "generation": generation,
                "result_id": result_id,
            }
            if all((child_id, parent_id, generation, result_id))
            else None
        )
        return ToolResult(
            status=status,
            content="\n".join(parts),
            tool_call_id="",
            tool_name=self.name,
            verification_receipts=nested_success,
            subagent_settlement=binding,
        )
