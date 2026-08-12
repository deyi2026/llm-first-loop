"""基础工具: 四段式文件修改（edit_file）.

M51（能力盘点短板改进）: 替代 execute_command + sed/heredoc 盲替换的脆弱路径。
四段式语义（一次调用内完成，每段失败如实回执不伪装）:
  1. read    读取原文件（不存在/无权限如实报错）
  2. match   old_string 唯一性校验（0 处/多处均失败并给修正引导，防锚点失配）
  3. diff    生成统一 diff 预览（回执可见，dry_run=true 时仅预览不写入）
  4. apply+verify  临时文件 + os.replace 原子写入，写后复读校验（失败如实报）

对应安全链: registry._is_destructive_tool 已含 edit_file（过 CatastrophicGuard），
factory 变更通告 hook 已含 edit_file（多会话协调落盘）。
"""

from __future__ import annotations

import contextlib
import difflib
import os
import tempfile
from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus

_DIFF_MAX_LINES = 80  # 回执中 diff 预览最大行数（超出截断并如实标注）


class EditFileTool:
    name = "edit_file"
    description = (
        "四段式文件修改（read→match→diff→apply+verify，替代 sed/heredoc 盲替换）。"
        "何时用: 精确修改已有文件的部分内容（改函数/加字段/修配置），"
        "尤其多行字符串或需确认改动正确性时。dry_run=true 只预览 diff 不写入（建议首次修改先预览）。"
        "何时不用: 读文件用 read_file；新建文件/全量重写用 execute_command 重定向更合适；"
        "不确定原文时先 read_file 拿到精确文本再调用（old_string 必须与文件内容完全一致，含缩进/换行）。"
        "失败对策: old_string 未匹配（0 处）→ read_file 核对原文（注意空白差异）后重试；"
        "多处匹配 → 扩大 old_string 上下文保证唯一，或确认后 replace_all=true；"
        "写入/校验失败会如实返回原因，文件保持原状（原子写入不产生半成品）。"
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目标文件路径"},
            "old_string": {
                "type": "string",
                "description": "要被替换的原文（必须与文件内容完全一致；默认需唯一匹配）",
            },
            "new_string": {"type": "string", "description": "替换后的新内容（可与 old_string 相同做 no-op 校验）"},
            "replace_all": {
                "type": "boolean",
                "description": "为 true 时替换全部匹配处（默认 false 要求唯一匹配，防误改）",
            },
            "dry_run": {
                "type": "boolean",
                "description": "为 true 时仅返回 diff 预览不写入（默认 false 实际应用）",
            },
        },
        "required": ["path", "old_string", "new_string"],
    }

    def run(self, arguments: dict) -> ToolResult:
        path_str = str(arguments.get("path", "") or "").strip()
        old = arguments.get("old_string")
        new = arguments.get("new_string")
        replace_all = bool(arguments.get("replace_all", False))
        dry_run = bool(arguments.get("dry_run", False))

        if not path_str:
            return self._fail("缺少必填参数 path")
        if old is None or new is None:
            return self._fail("缺少必填参数 old_string/new_string")
        old, new = str(old), str(new)
        if old == "":
            return self._fail("old_string 为空无法定位（插入内容请锚定相邻原文）")

        # ── 段1: read ──
        path = Path(path_str)
        try:
            original = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self._fail(f"文件不存在: {path_str}（可用 execute_command ls 确认路径）", "FileNotFoundError")
        except (OSError, UnicodeDecodeError) as exc:
            return self._fail(f"读取失败: {type(exc).__name__}: {exc}", type(exc).__name__)

        # ── 段2: match（唯一性校验，防锚点失配）──
        count = original.count(old)
        if count == 0:
            return self._fail(
                f"old_string 未匹配（0 处）。原因通常是空白/缩进/换行与原文有细微差异。"
                f"建议: read_file 读取 {path_str} 目标区域获取精确文本后重试（不要用记忆里的内容）。",
                "NoMatch",
            )
        if count > 1 and not replace_all:
            return self._fail(
                f"old_string 匹配 {count} 处（非唯一，默认拒绝防误改）。"
                f"建议: 扩大 old_string 上下文（含前后行）保证唯一；或确认全部替换后 replace_all=true。",
                "MultipleMatches",
            )

        updated = original.replace(old, new)

        # ── 段3: diff 预览 ──
        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(),
                updated.splitlines(),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
                lineterm="",
                n=2,
            )
        )
        truncated = len(diff_lines) > _DIFF_MAX_LINES
        diff_text = "\n".join(diff_lines[:_DIFF_MAX_LINES])
        if truncated:
            diff_text += f"\n... [diff 过长已截断: 共 {len(diff_lines)} 行，显示前 {_DIFF_MAX_LINES} 行]"
        added = sum(1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++"))
        removed = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))

        if dry_run:
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=(
                    f"[预览模式 dry_run: 未写入] {path_str}\n"
                    f"匹配 {count} 处，变更 +{added}/-{removed} 行。确认无误后去掉 dry_run 应用。\n"
                    f"```diff\n{diff_text}\n```"
                ),
                tool_call_id="",
                tool_name=self.name,
            )

        # ── 段4: apply（原子写入）+ verify（写后复读校验）──
        try:
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(updated)
                os.replace(tmp, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        except OSError as exc:
            return self._fail(
                f"写入失败: {type(exc).__name__}: {exc}（文件保持原状，原子写入未产生半成品）",
                type(exc).__name__,
            )

        try:
            reread = path.read_text(encoding="utf-8")
        except OSError as exc:
            return self._fail(f"写入后校验读取失败: {type(exc).__name__}: {exc}（写入可能已生效，请人工核对）", type(exc).__name__)
        if reread != updated:
            return self._fail(
                "写后校验失败: 复读内容与预期不一致（可能被并发修改）。文件当前状态需人工核对。",
                "VerifyMismatch",
            )

        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                f"[修改完成并已校验] {path_str}\n"
                f"替换 {count} 处，变更 +{added}/-{removed} 行（原子写入，写后复读一致）。\n"
                f"```diff\n{diff_text}\n```"
            ),
            tool_call_id="",
            tool_name=self.name,
        )

    def _fail(self, msg: str, error_type: str = "ValueError") -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.ERROR,
            content=f"[修改失败] {msg}",
            tool_call_id="",
            tool_name=self.name,
            error_type=error_type,
            error_detail=msg,
        )
