"""模型管理类工具注册（T2，design §2.1.2-5.2）.

承载: model_catalog / switch_model
model_pool 未注入时仍注册 schema，执行时如实回执"工具不可用"。
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_model import (
    MODEL_CATALOG_TOOL_DEF,
    SWITCH_MODEL_TOOL_DEF,
)


def _resolve_binding(ctx: Any):
    """P0-5: 经 contextvar 解析本会话 override 绑定（并发 run 隔离）.

    Returns: (getter, setter) 或 None（无解析器/会话不活跃 → 调用方回退 ctx 环境字段）。
    """
    resolver = getattr(ctx, "session_binding_resolver", None)
    if resolver is None:
        return None
    try:
        from llm_loop.core.run_context import current_session_id

        sid = current_session_id.get()
        if not sid:
            return None
        return resolver(sid)
    except Exception:  # noqa: BLE001 — 解析失败回退环境字段（零回归）
        return None


def tool_defs() -> list[dict]:
    return [MODEL_CATALOG_TOOL_DEF, SWITCH_MODEL_TOOL_DEF]


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "model_catalog":
        from llm_loop.introspection.tools_model import run_model_catalog

        binding = _resolve_binding(host.ctx)
        current_override = binding[0]() if binding is not None else host.ctx.session_model_override
        result = run_model_catalog(
            host.ctx,
            host.ctx.model_pool,
            current_override,
        )
        host.audit("model_catalog", args, result.status.value)
        return result

    if name == "switch_model":
        from llm_loop.introspection.tools_model import run_switch_model

        binding = _resolve_binding(host.ctx)
        setter = binding[1] if binding is not None else host.ctx.session_set_override
        return run_switch_model(
            host.ctx,
            host.ctx.model_pool,
            setter,
            host.audit,
            args,
        )

    return None
