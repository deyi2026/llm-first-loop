"""BranchLane 工具注册（DESIGN-20261105 §4.2 / §11 裁决）.

承载: lane_open / lane_update / lane_close / lane_merge_request
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_lane import LANE_TOOL_DEFS


def tool_defs() -> list[dict]:
    return LANE_TOOL_DEFS


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "lane_open":
        from llm_loop.introspection.tools_lane import run_lane_open

        return run_lane_open(host.ctx, host, args)
    if name == "lane_update":
        from llm_loop.introspection.tools_lane import run_lane_update

        return run_lane_update(host.ctx, host, args)
    if name == "lane_close":
        from llm_loop.introspection.tools_lane import run_lane_close

        return run_lane_close(host.ctx, host, args)
    if name == "lane_reap":
        from llm_loop.introspection.tools_lane import run_lane_reap

        return run_lane_reap(host.ctx, host, args)
    if name == "lane_merge_request":
        from llm_loop.introspection.tools_lane import run_lane_merge_request

        return run_lane_merge_request(host.ctx, host, args)
    return None
