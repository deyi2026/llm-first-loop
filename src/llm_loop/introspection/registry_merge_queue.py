"""合并队列与 S1 机检工具注册（DESIGN-20261105 §4.4）.

承载: lane_queue_submit / lane_queue_status / lane_merge_advice /
      lane_queue_confirm / lane_gate_check
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_merge_queue import MERGE_QUEUE_TOOL_DEFS

_HANDLERS: dict[str, str] = {
    "lane_queue_submit": "run_lane_queue_submit",
    "lane_queue_status": "run_lane_queue_status",
    "lane_merge_advice": "run_lane_merge_advice",
    "lane_queue_confirm": "run_lane_queue_confirm",
    "lane_gate_check": "run_lane_gate_check",
}


def tool_defs() -> list[dict]:
    return MERGE_QUEUE_TOOL_DEFS


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    handler = _HANDLERS.get(name)
    if handler is None:
        return None
    from llm_loop.introspection import tools_merge_queue

    return getattr(tools_merge_queue, handler)(host.ctx, host, args)
