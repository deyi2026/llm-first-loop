"""读取子代理 fleet 租约的磁盘事实（recover() 视图的工具面暴露）。"""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus


class SubAgentLeaseTool:
    """只读的 fleet lease 事实面：workspace/lease/settlement + expires_at/expired。"""

    name = "subagent_lease"
    registry_timeout_s = 10.0
    description = (
        "读取一个子代理 workspace 的 fleet 租约磁盘事实（当前租约与结算）："
        "workspace_id、lease_id/generation/worker_id/owner_id/state、expires_at/expired，"
        "以及 settlement 是否存在与 outcome。输入 spawn_subagent 返回的 child_id（即 workspace run_key）。"
        "只读工具：不做任何接管/续约/语义判断；expired=true 只说明租约超期这一机械事实。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "child_id": {
                "type": "string",
                "description": "子代理的 child_id（workspace run_key）",
            },
        },
        "required": ["child_id"],
    }

    def __init__(self, runner) -> None:
        self._runner = runner

    def execute(self, **kwargs) -> ToolResult:
        child_id = str(kwargs.get("child_id", "") or "").strip()
        ok, detail, view = self._runner.lease_facts(child_id)
        if not ok:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[状态: failure] subagent_lease: {detail}",
                tool_call_id="",
                tool_name=self.name,
            )
        assert view is not None
        lease = view.get("lease") or {}
        settlement = view.get("settlement")
        lines = [
            f"[状态: success] workspace_id={view.get('workspace_id')}",
        ]
        if lease:
            expired = bool(lease.get("expired"))
            lines.append(
                "lease: lease_id={lease_id} generation={generation} worker_id={worker_id} "
                "owner_id={owner_id} state={state} expires_at={expires_at} expired={expired}".format(
                    lease_id=lease.get("lease_id"),
                    generation=lease.get("generation"),
                    worker_id=lease.get("worker_id"),
                    owner_id=lease.get("owner_id"),
                    state=lease.get("state"),
                    expires_at=lease.get("expires_at"),
                    expired=str(expired).lower(),
                )
            )
        else:
            lines.append("lease: none")
        if settlement is None:
            lines.append("settlement: none")
        else:
            result = settlement.get("result") or {}
            lines.append(
                "settlement=settled outcome={outcome} worker_id={worker_id}".format(
                    outcome=result.get("outcome"),
                    worker_id=settlement.get("worker_id"),
                )
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="\n".join(lines),
            tool_call_id="",
            tool_name=self.name,
        )
