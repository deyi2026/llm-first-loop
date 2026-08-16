"""基础工具 1: 读取文件（design.md 模块 D / FR-TOOL-01）."""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.tools.safety import link_shaped_paths


class ReadFileTool:
    name = "read_file"
    description = (
        "读取本地文件内容。何时用: 需要查看文件/代码/配置/任何文本文件内容时。"
        "何时不用: 需要列出目录或查找文件时（应选目录/查找类工具）；URL 不是文件路径。"
        "失败对策: 文件不存在/无权限会如实返回失败原因，请核对路径后重试或换工具。"
        "状态契约: 大文件/长输出超 12000 字符将走分层折叠（关键事实提取 + 原文另存压缩档案，"
        "TOOL_SUMMARY_THRESHOLD 环境变量可调）——超大文件建议直接用 offset/limit 分段读取以避免折叠后二次检索。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要读取的文件路径"},
            "offset": {"type": "integer", "description": "起始行号（0-based，默认 0）"},
            "limit": {"type": "integer", "description": "最多读取行数（默认全部）"},
        },
        "required": ["path"],
    }

    def execute(self, **kwargs) -> ToolResult:
        path = str(kwargs.get("path", "")).strip()
        offset = int(kwargs.get("offset", 0) or 0)
        limit = kwargs.get("limit")

        if not path:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'path'（要读取的文件路径）",
                tool_call_id="",  # 由注册表填充
                tool_name=self.name,
            )
        p = Path(path).expanduser()
        # 工作区跟随: 相对路径基于当前工作区根（无工作区 → 进程 cwd，零回归）
        if not p.is_absolute():
            from llm_loop.core.run_context import workspace_base

            p = Path(workspace_base()) / p
        # T5b: symlink 透明标注（读放行，信息不隐藏；写路径在 edit_file 拒绝）
        _links = link_shaped_paths(p)
        _link_note = f"\n[symlink] 路径含符号链接: {' → '.join(_links)}" if _links else ""
        try:
            if not p.exists():
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=f"[文件不存在] {p} 不存在。请检查路径是否正确（可先用 list 类工具确认）。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            if not p.is_file():
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=f"[不是文件] {p} 是目录而非文件，请用目录工具。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(lines)
            start = max(0, min(offset, total))
            selected = lines[start:]
            if limit is not None:
                selected = selected[: int(limit)]
            if not selected:
                return ToolResult(
                    status=ToolResultStatus.SUCCESS,
                    content=f"[空文件] {p} 为空或无内容。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            numbered = "\n".join(f"{start + i + 1} | {ln}" for i, ln in enumerate(selected))
            note = f"\n[共 {total} 行，已显示 {len(selected)} 行]" if len(selected) < total else ""
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=numbered + note + _link_note,
                tool_call_id="",
                tool_name=self.name,
            )
        except PermissionError:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[无权限] 无法读取 {p}（权限不足）。",
                tool_call_id="",
                tool_name=self.name,
            )
        except OSError as exc:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[读取失败] {type(exc).__name__}: {exc}",
                tool_call_id="",
                tool_name=self.name,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
