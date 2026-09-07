"""Explicit hydration for durable attachment references."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus


class ReadAttachmentTool:
    """Read exact model-readable text behind an ``attachment://`` reference."""

    name = "read_attachment"
    description = (
        "读取用户已上传附件的完整可读文本，参数 ref 必须是 attachment:// 引用。"
        "首次对话中的 excerpt 只是快速视图；显式调用本工具时不再使用 excerpt 截断。"
        "单次最多返回 100000 个真实字符；只有源文本物理超过该页大小时才返回 next_offset，"
        "后续用该绝对 offset 连续读取，不重复前一页。该工具只读取耐久源，不做摘要/语义筛选。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "ref": {
                "type": "string",
                "description": "attachment:// 开头的服务端附件引用",
            },
            "offset": {
                "type": "integer",
                "description": "绝对字符偏移，默认 0；分页时使用上一页 next_offset",
            },
            "max_chars": {
                "type": "integer",
                "description": "本次最多读取字符数，默认/硬上限 100000",
            },
        },
        "required": ["ref"],
    }

    def __init__(self, store: Any) -> None:
        # Store is injected by factory. Keeping this tool free of a Web-package import
        # avoids factory <-> web.__init__ cycles while preserving one source of truth.
        self.store = store

    def execute(self, **kwargs) -> ToolResult:
        ref = str(kwargs.get("ref", "") or "").strip()
        offset = max(0, int(kwargs.get("offset", 0) or 0))
        max_chars = max(1, min(int(kwargs.get("max_chars", 100_000) or 100_000), 100_000))
        if not ref.startswith("attachment://"):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] ref 必须是 attachment:// 引用。",
                tool_call_id="",
                tool_name=self.name,
                error_type="InvalidAttachmentRef",
            )
        from llm_loop.core.run_context import workspace_base

        scope = str(Path(workspace_base()).expanduser().resolve())
        try:
            page = self.store.hydrate_text(
                ref,
                workspace_scope=scope,
                offset=offset,
                max_chars=max_chars,
            )
        except ValueError as exc:  # AttachmentError is a ValueError with client-safe text.
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[attachment 无法读取] {exc}",
                tool_call_id="",
                tool_name=self.name,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
        except Exception as exc:  # unexpected storage/I/O detail may contain host paths
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[attachment 读取异常] {type(exc).__name__}",
                tool_call_id="",
                tool_name=self.name,
                error_type=type(exc).__name__,
                error_detail=type(exc).__name__,
            )
        header = (
            f"[read_attachment] ref={page['ref']} filename={page['filename']} "
            f"source_text_chars={page['source_text_chars']} offset={page['offset']} "
            f"sha256={page['source_text_sha256']} "
            f"source_complete={'true' if page['source_text_complete'] else 'false'} "
            f"page_complete={'true' if page['complete'] else 'false'}"
        )
        footer = ""
        if page["next_offset"] is not None:
            footer = f"\n[next_offset={page['next_offset']}]"
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=header + "\n" + str(page["content"]) + footer,
            tool_call_id="",
            tool_name=self.name,
            evidence_source_version_token=f"attachment-sha256:{page['source_text_sha256']}",
        )
