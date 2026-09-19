"""子代理拓扑 + fleet 租约合并只读视图（topology_lease_view 的工具面暴露）。"""

from __future__ import annotations

import json

from llm_loop.core.message import ToolResult, ToolResultStatus


class SubagentTopologyTool:
    """只读合并视图：拓扑（journal/session 面）+ 租约（fleet 盘上面）。

    coordinator 未接入时租约块如实 unavailable，拓扑面仍可用；
    本工具不产生任何写，不做接管/续约/语义判断。
    """

    name = "subagent_topology"
    registry_timeout_s = 10.0
    description = (
        "只读查询子代理拓扑与 fleet 租约的合并磁盘真相视图。二选一输入："
        "child_id=某子代理（返回 parent 归属、topology_snapshot、lease recover 视图），"
        "parent_id=某会话（返回其 active children、每 child 租约与 pending obligations）。"
        "跨会话接管/寻找前情 children/判断租约是否超期可回收时使用；"
        "租约块 unavailable 表示本 runner 未接入 fleet（LFL_FLEET_WORKSPACE_ROOT 未配置）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "child_id": {
                "type": "string",
                "description": "要查的子代理 child_id（workspace run_key）",
            },
            "parent_id": {
                "type": "string",
                "description": "要查的父会话 session id（列其 active children 与租约）",
            },
        },
        "required": [],
    }

    def __init__(self, runner) -> None:
        self._runner = runner

    def _lease_lines(self, lease: dict) -> list[str]:
        lines: list[str] = []
        if lease.get("status") != "ok":
            lines.append(f"lease: unavailable ({lease.get('detail')})")
            return lines
        facts = lease.get("facts") or {}
        lease_facts = facts.get("lease") or {}
        summary = facts.get("facts_summary") or {}
        if lease_facts:
            lines.append(
                "lease: state={state} generation={generation} expires_at={expires_at} expired={expired}".format(
                    state=lease_facts.get("state"),
                    generation=lease_facts.get("generation"),
                    expires_at=lease_facts.get("expires_at"),
                    expired=str(bool(lease_facts.get("expired"))).lower(),
                )
            )
        else:
            lines.append("lease: none")
        lines.append(
            "facts: run_started={s} run_settled={t} last_parent_session_id={p}".format(
                s=summary.get("run_started"),
                t=summary.get("run_settled"),
                p=summary.get("last_parent_session_id"),
            )
        )
        return lines

    def execute(self, **kwargs) -> ToolResult:
        child_id = str(kwargs.get("child_id", "") or "").strip()
        parent_id = str(kwargs.get("parent_id", "") or "").strip()
        ok, detail, view = self._runner.topology_lease_view(
            parent_id=parent_id, child_id=child_id
        )
        if not ok:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[状态: failure] subagent_topology: {detail}",
                tool_call_id="",
                tool_name=self.name,
            )
        lines: list[str]
        if child_id:
            topology = view.get("topology")
            lines = [
                f"[状态: success] child_id={child_id}",
                f"parent_session_id={view.get('parent_id') or 'none'}",
                f"topology={json.dumps(topology, ensure_ascii=False) if topology is not None else 'none'}",
            ]
            lines.extend(self._lease_lines(view.get("lease") or {}))
        else:
            lines = [
                f"[状态: success] parent_id={view.get('parent_id')}",
                "active_children={children}".format(
                    children=",".join(view.get("active_children") or []) or "none"
                ),
            ]
            for item in view.get("children") or []:
                lines.append(f"child={item.get('child_id')}")
                lines.extend(self._lease_lines(item.get("lease") or {}))
            obligations = view.get("pending_obligations") or []
            lines.append(f"pending_obligations={len(obligations)}")
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="\n".join(lines),
            tool_call_id="",
            tool_name=self.name,
        )
