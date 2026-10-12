"""飞书出站类工具注册（T2，design §2.1.2-5.2）.

承载: send_feishu_message / create_feishu_doc / send_feishu_attachment
默认禁用+白名单+速率+审计（涉安全边界）。
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_feishu_outbound import (
    CREATE_FEISHU_DOC_TOOL_DEF,
    SEND_FEISHU_ATTACHMENT_TOOL_DEF,
    SEND_FEISHU_MESSAGE_TOOL_DEF,
)


def tool_defs() -> list[dict]:
    return [SEND_FEISHU_MESSAGE_TOOL_DEF, CREATE_FEISHU_DOC_TOOL_DEF, SEND_FEISHU_ATTACHMENT_TOOL_DEF]


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "send_feishu_message":
        from llm_loop.introspection.tools_feishu_outbound import run_send_feishu_message

        return run_send_feishu_message(host.ctx, host.audit, args)
    if name == "create_feishu_doc":
        from llm_loop.introspection.tools_feishu_outbound import run_create_feishu_doc

        return run_create_feishu_doc(host.ctx, host.audit, args)
    if name == "send_feishu_attachment":
        from llm_loop.introspection.tools_feishu_outbound import run_send_feishu_attachment

        return run_send_feishu_attachment(host.ctx, host.audit, args)
    return None
