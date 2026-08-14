"""自我评估类工具注册（T2，design §2.1.2-5.2）.

承载: self_evaluate
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_eval import SELF_EVALUATE_TOOL_DEF


def tool_defs() -> list[dict]:
    return [SELF_EVALUATE_TOOL_DEF]


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "self_evaluate":
        from llm_loop.introspection.tools_eval import run_self_evaluate

        return run_self_evaluate(host.ctx, host.audit, args)
    return None
