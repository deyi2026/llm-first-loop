"""Task Frontier 工具注册（DESIGN-20260828）.

承载: task_create / task_update / task_frontier
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_task import TASK_TOOL_DEFS


def tool_defs() -> list[dict]:
    return TASK_TOOL_DEFS


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "task_create":
        from llm_loop.introspection.tools_task import run_task_create

        return run_task_create(host.ctx, host, args)
    if name == "task_update":
        from llm_loop.introspection.tools_task import run_task_update

        return run_task_update(host.ctx, host, args)
    if name == "task_frontier":
        from llm_loop.introspection.tools_task import run_task_frontier

        return run_task_frontier(host.ctx, host, args)
    return None
