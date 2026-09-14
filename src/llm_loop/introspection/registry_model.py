"""模型管理类工具注册（T2，design §2.1.2-5.2）.

承载: model_catalog / switch_model
model_pool 未注入时仍注册 schema，执行时如实回执"工具不可用"。
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_model import (
    MODEL_CATALOG_TOOL_DEF,
    SWITCH_MODEL_TOOL_DEF,
)


def _resolve_binding(ctx: Any):
    """P0-5: 经 contextvar 解析本会话 override 绑定（并发 run 隔离）.

    Returns: (getter, setter) 或 None。模型可调用 registry 把 None 视为
    ``session ownership unknown`` 并 fail closed；不得回退 shared ctx 最近值。
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
    except Exception:  # noqa: BLE001 — 解析失败 = ownership unknown，调用方 fail closed
        return None


def tool_defs() -> list[dict]:
    return [MODEL_CATALOG_TOOL_DEF, SWITCH_MODEL_TOOL_DEF]


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "model_catalog":
        from llm_loop.introspection.tools_model import run_model_catalog

        binding = _resolve_binding(host.ctx)
        binding_known = binding is not None
        current_override = None
        if binding is not None:
            try:
                current_override = binding[0]()
            except Exception:  # noqa: BLE001 — catalog stays read-only, current owner becomes unknown
                binding_known = False
        result = run_model_catalog(
            host.ctx,
            host.ctx.model_pool,
            current_override,
            session_binding_known=binding_known,
        )
        host.audit("model_catalog", args, result.status.value)
        return result

    if name == "switch_model":
        from llm_loop.introspection.tools_model import run_switch_model

        binding = _resolve_binding(host.ctx)
        if binding is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    "[会话归属不可用] 当前执行没有可证明的 session binding；"
                    "未读取或调用 shared session override，模型切换未执行。"
                ),
                tool_call_id="",
                tool_name="switch_model",
            )
        getter = binding[0]
        setter = binding[1]
        routing_transition = (
            binding[2] if isinstance(binding, tuple) and len(binding) >= 3 else None
        )
        return run_switch_model(
            host.ctx,
            host.ctx.model_pool,
            setter,
            host.audit,
            args,
            session_get_override=getter,
            routing_transition=routing_transition,
        )

    return None
