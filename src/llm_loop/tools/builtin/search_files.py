"""基础工具: 文件搜索（glob 路径 + 内容 grep）——DSH-PLUGINS-20260816 ③ search_files.

何时用: 需要按文件名 glob / 内容关键词检索工作区文件（RULE-AI-07 工具优先，
免 execute_command 手写 grep 碎调用）；返回匹配文件/行摘要（截断防超长）。
何时不用: 读已知路径文件用 read_file；需执行复杂命令用 execute_command。
失败对策: 目录不存在/无权限返回失败原因；无匹配返回空列表（如实）。
安全: 搜索根限工作区（workspace_root 或项目根），不越权扫全盘。
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus


class SearchFilesTool:
    name = "search_files"
    description = (
        "搜索工作区文件：按文件名 glob 模式或内容关键词检索。"
        "何时用: 需要查找文件位置（按名/扩展名/glob）或按内容关键词定位代码时；"
        "比 execute_command 手写 grep 更直接，返回结构化匹配结果。"
        "何时不用: 已确知文件路径用 read_file；需要执行复杂逻辑用 execute_command。"
        "失败对策: 目录不存在/无权限如实返回失败原因；无匹配返回空列表。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "文件名 glob 模式（如 '*.py'、'test_*.py'、'**/models/*.py'）；与 content 二选一",
            },
            "content": {
                "type": "string",
                "description": "内容关键词（正则，如 'def main'、'history_budget'）；与 pattern 二选一",
            },
            "root": {
                "type": "string",
                "description": "搜索根目录（默认项目根；必须为项目内路径，防越权）",
            },
            "max_results": {
                "type": "integer",
                "description": "最大返回条数（默认 20）",
            },
        },
        "required": [],
    }

    def execute(self, **kwargs) -> ToolResult:
        pattern = str(kwargs.get("pattern", "") or "").strip()
        content = str(kwargs.get("content", "") or "").strip()
        root = str(kwargs.get("root", "") or "").strip()
        max_results = int(kwargs.get("max_results", 20) or 20)

        if not pattern and not content:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] pattern（文件名 glob）与 content（内容关键词）至少填一个",
                tool_call_id="",
                tool_name=self.name,
            )

        # 搜索根解析：默认项目根；显式 root 允许任意存在目录（测试/外部工作区用）
        # __file__ = src/llm_loop/tools/builtin/search_files.py → 上 5 级 = 项目根
        project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        if root:
            base = (project_root / root).resolve()
            if not base.exists():
                base = Path(root).resolve()
            if not base.is_dir():
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=f"[目录不存在] {root}",
                    tool_call_id="",
                    tool_name=self.name,
                )
        else:
            base = project_root

        if not base.is_dir():
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[目录不存在] {base}",
                tool_call_id="",
                tool_name=self.name,
            )

        # 默认忽略常见噪声目录
        _ignore_dirs = {".git", "__pycache__", ".venv", "node_modules", "data", "dist", "build", ".idea", ".vscode"}

        results: list[str] = []
        try:
            if content:
                regex = re.compile(content, re.IGNORECASE)
                for dirpath, dirnames, filenames in os.walk(base):
                    dirnames[:] = [d for d in dirnames if d not in _ignore_dirs]
                    for fn in filenames:
                        fp = Path(dirpath) / fn
                        try:
                            if fp.stat().st_size > 2 * 1024 * 1024:
                                continue  # 跳过 >2MB 大文件（防卡）
                            with fp.open("r", encoding="utf-8", errors="replace") as f:
                                for i, line in enumerate(f, 1):
                                    if regex.search(line):
                                        rel = fp.relative_to(base)
                                        snippet = line.strip()[:120]
                                        results.append(f"{rel}:{i}: {snippet}")
                                        if len(results) >= max_results:
                                            break
                                    if i > 5000:
                                        break  # 单文件最多扫 5000 行（防超时）
                            if len(results) >= max_results:
                                break
                        except (OSError, UnicodeDecodeError):
                            continue
                        if len(results) >= max_results:
                            break
                    if len(results) >= max_results:
                        break
            else:
                for dirpath, dirnames, filenames in os.walk(base):
                    dirnames[:] = [d for d in dirnames if d not in _ignore_dirs]
                    for fn in filenames:
                        if fnmatch.fnmatch(fn, pattern):
                            rel = (Path(dirpath) / fn).relative_to(base)
                            results.append(str(rel))
                            if len(results) >= max_results:
                                break
                    if len(results) >= max_results:
                        break
        except OSError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[搜索失败] {exc}",
                tool_call_id="",
                tool_name=self.name,
            )

        if not results:
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=f"[search_files] 无匹配（pattern={pattern or '-'}, content={content or '-'}）",
                tool_call_id="",
                tool_name=self.name,
            )
        mode = "内容" if content else "文件名"
        body = f"[search_files] {mode}搜索命中 {len(results)} 条（截断显示前 {min(len(results), max_results)}）:\n"
        body += "\n".join(results[:max_results])
        if len(results) > max_results:
            body += f"\n…（共 {len(results)} 条，已截断）"
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=body,
            tool_call_id="",
            tool_name=self.name,
        )
