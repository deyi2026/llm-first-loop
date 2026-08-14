"""模型管理类工具注册（T2，design §2.1.2-5.2）.

承载: model_catalog / switch_model
model_pool 未注入时仍注册 schema，执行时如实回执"工具不可用"。
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_model import (
    MODEL_CATALOG_TOOL_DEF,
    SWITCH_MODEL_TOOL_DEF,
)


def tool_defs() -> list[dict]:
    return [MODEL_CATALOG_TOOL_DEF, SWITCH_MODEL_TOOL_DEF]


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "model_catalog":
        from llm_loop.introspection.tools_model import run_model_catalog

        result = run_model_catalog(
            host.ctx,
            host.ctx.model_pool,
            host.ctx.session_model_override,
        )
        host.audit("model_catalog", args, result.status.value)
        return result

    if name == "switch_model":
        from llm_loop.introspection.tools_model import run_switch_model

        return run_switch_model(
            host.ctx,
            host.ctx.model_pool,
            host.ctx.session_set_override,
            host.audit,
            args,
        )

    return None
