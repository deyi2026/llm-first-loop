"""代码结构概览工具（EVO-20260817 拷问识别的最高 ROI 能力工具）.

给 AI 一个"代码结构地图"：输入文件/目录 → 输出类/函数/import 索引（AST 解析，
零依赖），避免逐文件 read_file 定位慢（大项目定位提速 5-10 倍）。
与 search_files 互补：search_files 找"哪个文件有这个词"，inspect_code 给"这个文件/目录的结构"。

设计约束（能力工具，非 UX）:
- AST 解析（内建 ast，零依赖），非正则（注释/字符串误报少）
- 输出结构化：文件 → 类（方法）/函数（签名）/import，带行号
- 上限保护：文件数/输出长度受限（防大目录爆炸）
- fail-open: 解析失败单文件跳过并标注，不阻塞整体
"""

from __future__ import annotations

import ast
from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus

_MAX_FILES = 40          # 单次扫描最大文件数（目录模式）
_MAX_DEPTH = 3           # 目录递归最大深度
_MAX_LINES_PER_FILE = 60  # 单文件输出最大行数
_MAX_OUTPUT_CHARS = 12000  # 输出总字符上限（对齐 TOOL_MAX_OUTPUT_CHARS 合理档）


class InspectCodeTool:
    name = "inspect_code"
    description = (
        "代码结构概览——解析 Python 文件/目录的 AST，输出类（含方法）/函数（含签名）/import 索引。"
        "何时用: 需要快速了解一个文件/模块/项目的结构（有哪些类、函数、依赖），定位代码入口；"
        "大项目找东西时比逐文件 read_file 快 5-10 倍。"
        "何时不用: 需要看具体实现内容（用 read_file）；需要按关键词找文件（用 search_files）；"
        "非 Python 文件（返回不支持标注）。"
        "失败对策: 路径不存在/非 Python 如实返回失败；单文件解析失败跳过并标注。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件或目录路径（相对项目根或绝对路径）"},
            "depth": {"type": "integer", "description": "目录递归深度（默认 2，最大 3）"},
            "keyword": {"type": "string", "description": "可选：只显示名称含关键词的类/函数（过滤）"},
            "with_docstrings": {"type": "boolean", "description": "是否显示 docstring 首行（默认 true）"},
        },
        "required": ["path"],
    }

    def execute(self, **kwargs) -> ToolResult:
        path = str(kwargs.get("path", "") or "").strip()
        if not path:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'path'",
                tool_call_id="", tool_name=self.name,
            )
        try:
            depth = max(1, min(int(kwargs.get("depth", 2) or 2), _MAX_DEPTH))
        except (TypeError, ValueError):
            depth = 2
        keyword = str(kwargs.get("keyword", "") or "").strip()
        with_doc = bool(kwargs.get("with_docstrings", True))

        p = Path(path).expanduser()
        if not p.exists():
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[路径不存在] {path}",
                tool_call_id="", tool_name=self.name,
            )
        if p.is_file() and p.suffix != ".py":
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[不支持] 非 Python 文件: {path}（inspect_code 仅解析 .py）",
                tool_call_id="", tool_name=self.name,
            )
        if p.is_file():
            files = [p]
        else:
            files = self._collect_files(p, depth)

        if not files:
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=f"[空] {path} 下未找到 Python 文件（.py）",
                tool_call_id="", tool_name=self.name,
            )

        out: list[str] = []
        out.append(f"# 代码结构: {path}（{len(files)} 个 .py 文件）")
        skipped = 0
        total_chars = 0
        for f in files:
            if total_chars >= _MAX_OUTPUT_CHARS:
                out.append(f"…输出已达上限（{_MAX_OUTPUT_CHARS} 字符），剩余文件省略")
                break
            try:
                block = self._inspect_file(f, keyword, with_doc)
            except Exception as exc:  # noqa: BLE001 — 单文件失败跳过
                skipped += 1
                block = f"## {self._rel(f)}\n⚠️ 解析失败: {type(exc).__name__}: {exc}"
            if not block:
                continue
            out.append(block)
            total_chars += len(block)

        if skipped:
            out.append(f"（{skipped} 个文件解析失败已跳过）")
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="\n".join(out),
            tool_call_id="", tool_name=self.name,
        )

    # ── 内部 ──
    @staticmethod
    def _collect_files(root: Path, depth: int) -> list[Path]:
        files: list[Path] = []
        try:
            if depth <= 0:
                return []
            for child in sorted(root.iterdir()):
                if child.name.startswith((".", "__pycache__", "node_modules", ".venv", "venv")):
                    continue
                if child.is_file() and child.suffix == ".py":
                    files.append(child)
                    if len(files) >= _MAX_FILES:
                        break
                elif child.is_dir() and not child.name.startswith("__"):
                    files.extend(InspectCodeTool._collect_files(child, depth - 1))
                    if len(files) >= _MAX_FILES:
                        break
        except OSError:
            pass
        return files[: _MAX_FILES]

    @staticmethod
    def _rel(f: Path) -> str:
        try:
            return str(f.relative_to(Path.cwd()))
        except ValueError:
            return str(f)

    def _inspect_file(self, f: Path, keyword: str, with_doc: bool) -> str:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            return f"## {self._rel(f)}\n⚠️ 语法错误: {exc.msg}（行 {exc.lineno}）"
        lines: list[str] = [f"## {self._rel(f)}"]
        count = 0

        def _sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
            args = []
            for a in node.args.posonlyargs + node.args.args:
                args.append(a.arg)
            if node.args.vararg:
                args.append("*" + node.args.vararg.arg)
            if node.args.kwonlyargs:
                args.append("*")
                args.extend(a.arg for a in node.args.kwonlyargs)
            if node.args.kwarg:
                args.append("**" + node.args.kwarg.arg)
            return f"{node.name}({', '.join(args)})"

        def _doc(node: ast.AST) -> str:
            if not with_doc:
                return ""
            ds = ast.get_docstring(node)
            if not ds:
                return ""
            first = ds.strip().splitlines()[0][:60]
            return f"  # {first}"

        def _match(name: str) -> bool:
            return (not keyword) or keyword.lower() in name.lower()

        # 顶层 import
        for node in tree.body:
            if isinstance(node, ast.Import):
                for a in node.names:
                    if _match(a.asname or a.name.split(".")[0]):
                        lines.append(f"  import {a.name}" + (f" as {a.asname}" if a.asname else ""))
                        count += 1
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for a in node.names:
                    if _match(a.name):
                        lines.append(f"  from {mod} import {a.name}" + (f" as {a.asname}" if a.asname else ""))
                        count += 1
            if count >= _MAX_LINES_PER_FILE:
                break

        # 顶层类/函数
        for node in tree.body:
            if count >= _MAX_LINES_PER_FILE:
                lines.append("  …（输出达单文件上限）")
                break
            if isinstance(node, (ast.ClassDef,)) and _match(node.name):
                lines.append(f"  class {node.name}:{_doc(node)}")
                count += 1
                for item in node.body:
                    if count >= _MAX_LINES_PER_FILE:
                        break
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and _match(item.name):
                        prefix = "    async def " if isinstance(item, ast.AsyncFunctionDef) else "    def "
                        lines.append(f"{prefix}{_sig(item)}:{_doc(item)}")
                        count += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _match(node.name):
                prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
                lines.append(f"  {prefix}{_sig(node)}:{_doc(node)}")
                count += 1

        return "\n".join(lines) if len(lines) > 1 else f"## {self._rel(f)}\n  （无匹配条目）"
