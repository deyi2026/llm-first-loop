"""L3 协助收件箱工具注册（DESIGN-20261105 §4.7 / L3）.

承载: help_request / help_inbox / help_resolve
（主会话统一接入由 corrections.py 负责，本模块不触碰。）
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_help import HELP_TOOL_DEFS


def tool_defs() -> list[dict]:
    return HELP_TOOL_DEFS


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "help_request":
        from llm_loop.introspection.tools_help import run_help_request

        return run_help_request(host.ctx, host, args)
    if name == "help_inbox":
        from llm_loop.introspection.tools_help import run_help_inbox

        return run_help_inbox(host.ctx, host, args)
    if name == "help_resolve":
        from llm_loop.introspection.tools_help import run_help_resolve

        return run_help_resolve(host.ctx, host, args)
    return None
