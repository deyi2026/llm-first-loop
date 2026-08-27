"""任务级 Goal 工具注册（EVO-20260824-3cd4d74b）.

承载: create_goal / checkpoint_goal / get_goal / update_goal
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_goal import GOAL_TOOL_DEFS


def tool_defs() -> list[dict]:
    return GOAL_TOOL_DEFS


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "create_goal":
        from llm_loop.introspection.tools_goal import run_create_goal

        return run_create_goal(host.ctx, host, args)
    if name == "checkpoint_goal":
        from llm_loop.introspection.tools_goal import run_checkpoint_goal

        return run_checkpoint_goal(host.ctx, host, args)
    if name == "get_goal":
        from llm_loop.introspection.tools_goal import run_get_goal

        return run_get_goal(host.ctx, host, args)
    if name == "update_goal":
        from llm_loop.introspection.tools_goal import run_update_goal

        return run_update_goal(host.ctx, host, args)
    return None
