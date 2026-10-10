"""LFL 能力目录（工具面导出）.

静态结构化描述 LFL 可被外部复用的能力域，作为 MCP 工具 ``list_capabilities``
的载荷。内容与代码事实对齐：只列已存在的层，不虚构未交付能力。
"""

from __future__ import annotations

from typing import Any


def capability_catalog() -> dict[str, Any]:
    """返回 LFL 对外能力目录（纯函数，无 IO）。"""
    return {
        "server": {
            "name": "lfl-export",
            "kind": "read_only_mcp_export",
            "write_paths": "none（write_guard 恒拒绝）",
        },
        "exported_layers": [
            {
                "id": "experience",
                "description": "LFL 经验库：结构化经验/教训文档（front matter + 正文），lexical 检索，仅 active",
                "tools": ["search_experience", "read_experience"],
                "storage": "experiences/EXPERIENCE-*.md",
            },
            {
                "id": "method",
                "description": "Method Learning 库：候选/资格化方法及其生命周期状态",
                "tools": ["search_method", "read_method"],
                "storage": "data/methods/<method_id>/METHOD.md（seed 目录兜底）",
            },
            {
                "id": "evidence",
                "description": "ERC 证据 ledger：owner-scoped 捕获观测的只读检索与有界精确水合",
                "tools": ["search_evidence", "read_evidence"],
                "opt_in": True,
                "enable": "LFL_EXPORT_EVIDENCE_OWNER=workspace_id/session_id",
                "default": "disabled（owner 隔离，外部消费者默认不持有 scope）",
            },
            {
                "id": "capabilities",
                "description": "本能力目录（工具面自描述）",
                "tools": ["list_capabilities"],
            },
        ],
        "runtime_domains": [
            {"id": "knowledge", "description": "经验/方法/规则的记忆分层与生命周期"},
            {
                "id": "evidence_recovery",
                "description": "证据捕获/水合/新鲜度（ERC）：content-addressed blob + ledger",
            },
            {
                "id": "mcp_client_stack",
                "description": "作为 MCP 客户端连接外部工具服务器的完整协议栈",
                "transports": ["stdio", "streamable_http", "sse"],
                "protocol_generations": [
                    "legacy（initialize 握手）",
                    "2026-07-28 modern（server/discover，逐请求 _meta）",
                ],
            },
            {"id": "goal_task_graph", "description": "durable Goal/Task 图：里程碑、依赖、验收证据"},
            {"id": "introspection", "description": "记录检索/文档检索/架构状态/审计等内省工具面"},
        ],
        "notes": [
            "导出面全部只读；不装配对话 engine，不执行模型调用。",
            "evidence 面为 opt-in：仅在显式指定导出 owner 且 ledger 存在时启用。",
        ],
    }
