"""基础工具 2: 执行命令（design.md 模块 D / FR-TOOL-01）.

灾难性安全校验在 ToolRegistry.execute 包裹内完成（FR-SAFE-01），
工具自身只做真实执行与如实结果构造。
"""

from __future__ import annotations

import subprocess

from llm_loop.core.message import ToolResult, ToolResultStatus

# 方案 4: 工具输出截断（context 优化——长输出只发头尾，完整内容可经 search_archive 检索）
_MAX_OUTPUT_CHARS = 3000
_KEEP_HEAD_CHARS = 1500
_KEEP_TAIL_CHARS = 1500


def _truncate_output(content: str, command: str = "") -> str:
    """截断长输出：保留首 1500 + 末 1500 字符，中间附截断说明与搜索关键词."""
    if len(content) <= _MAX_OUTPUT_CHARS:
        return content
    head = content[:_KEEP_HEAD_CHARS]
    tail = content[-_KEEP_TAIL_CHARS:]
    # 从命令提取关键词（取可打印词，最多 3 个；排除常见 shell 噪音词）
    _NOISE = {"and", "or", "not", "the", "for", "with", "echo"}
    kw = " ".join(
        [w for w in command.split() if w.isalnum() and len(w) >= 2 and w not in _NOISE][:3]
    )
    return (
        f"{head}\n"
        f"[输出已截断] 事实: 完整输出 {len(content)} 字符，仅展示首 {_KEEP_HEAD_CHARS} + 末 {_KEEP_TAIL_CHARS} 字符。"
        f"\n原因: 上下文优化（方案 4 工具输出截断）。"
        f"\n建议: 如需完整内容可用 search_archive 检索{'，搜索关键词: ' + kw if kw else '（按命令相关词检索）'}。\n"
        f"{tail}"
    )


class ExecuteCommandTool:
    name = "execute_command"
    description = (
        "在本地 shell 执行命令并返回标准输出/错误。何时用: 运行脚本、查询系统状态、安装依赖、文件操作等。"
        "何时不用: 纯读取文件应优先 read_file；仅获取网页用 web_fetch。"
        "失败对策: 非零退出码会如实返回并标注；破坏性命令（rm -rf 根目录等）会被安全边界硬阻断，请改用安全方案。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令"},
        },
        "required": ["command"],
    }

    def __init__(self, timeout_s: float | None = None) -> None:
        """工具内兜底超时（M18 AA8: 读配置值，默认 30s 兜底向后兼容；注册表另有线程级超时）."""
        self._timeout_s = 30.0 if timeout_s is None else float(timeout_s)

    def execute(self, **kwargs) -> ToolResult:
        command = str(kwargs.get("command", "")).strip()
        if not command:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'command'（要执行的命令）",
                tool_call_id="",
                tool_name=self.name,
            )
        try:
            proc = subprocess.run(
                command,
                shell=True,  # noqa: S602 — 工具本质是执行命令，安全校验由 CatastrophicGuard 前置
                capture_output=True,
                text=True,
                timeout=self._timeout_s,  # 工具内兜底超时 = 配置值（注册表另有线程级超时）
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                status=ToolResultStatus.TIMEOUT,
                content=f"[执行超时] 命令超过 {self._timeout_s:.0f}s 未完成",
                tool_call_id="",
                tool_name=self.name,
            )
        except OSError as exc:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[执行失败] {type(exc).__name__}: {exc}",
                tool_call_id="",
                tool_name=self.name,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )

        parts: list[str] = []
        if proc.stdout:
            parts.append(proc.stdout.rstrip())
        if proc.stderr:
            parts.append(f"[stderr] {proc.stderr.rstrip()}")
        content = "\n".join(parts) if parts else "（命令执行成功，无输出）"

        status = ToolResultStatus.SUCCESS if proc.returncode == 0 else ToolResultStatus.FAILURE
        if proc.returncode != 0:
            content = f"[命令退出码 {proc.returncode}] {content}"

        content = _truncate_output(content, command)

        return ToolResult(
            status=status,
            content=content,
            tool_call_id="",
            tool_name=self.name,
        )
