"""基础工具: 四段式文件修改（edit_file）.

M51（能力盘点短板改进）: 替代 execute_command + sed/heredoc 盲替换的脆弱路径。
四段式语义（一次调用内完成，每段失败如实回执不伪装）:
  1. read    读取原文件（不存在/无权限如实报错；EVO-20260814-aab7eb0b 起记录基线 mtime+size）
  2. match   old_string 唯一性校验（0 处/多处均失败并给修正引导，防锚点失配）
  3. diff    生成统一 diff 预览（回执可见，dry_run=true 时仅预览不写入）
  4. apply+verify  临时文件 + os.replace 原子写入，写后复读校验（失败如实报）

EVO-20260814-aab7eb0b（思路借鉴 coding-tools-mcp patching.py，Apache License 2.0
https://github.com/coding-tools-mcp，本实现为独立改编：BOM/CRLF 归一化 + 基线校验）:
- 匹配前统一做 BOM 剥离 + CRLF→LF 归一化，写回时恢复原 BOM/换行风格——
  old_string 只需"内容对得上"，不再要求换行风格字节级一致（弱模型/跨平台友好）。
- FileBaseline：匹配后、写入前校验文件未被外部改动（mtime_ns+size），
  改动则拒绝写入并如实报"请重新读取"，堵住"读 A 写 B"并发隐患。

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
from llm_loop.tools.safety import link_shaped_paths
from llm_loop.workspace.artifacts import WorkspaceArtifactStore

_DIFF_MAX_LINES = 80  # 回执中 diff 预览最大行数（超出截断并如实标注）
_UTF8_BOM = b"\xef\xbb\xbf"


def _detect_line_ending(text: str) -> str:
    """检测主导换行风格（CRLF 占优则 "\\r\\n"，否则 "\\n"）。"""
    crlf = text.count("\r\n")
    lf_only = text.count("\n") - crlf
    return "\r\n" if crlf > lf_only else "\n"


def _normalize_lf(text: str) -> str:
    """CRLF/CR 统一归一化为 LF（匹配语义用）。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


class EditFileTool:
    name = "edit_file"
    description = (
        "四段式文件修改（read→match→diff→apply+verify，替代 sed/heredoc 盲替换）。"
        "何时用: 精确修改已有文件的部分内容（改函数/加字段/修配置），"
        "尤其多行字符串或需确认改动正确性时。dry_run=true 只预览 diff 不写入（建议首次修改先预览）。"
        "何时不用: 读文件用 read_file；新建文件/全量重写用 execute_command 重定向更合适；"
        "old_string 需与文件内容一致（缩进/文字），但换行风格与 BOM 差异已自动归一化容错，"
        "不确定原文时先 read_file 拿到目标区域文本再调用。"
        "失败对策: old_string 未匹配（0 处）→ read_file 核对原文（注意缩进差异）后重试；"
        "多处匹配 → 扩大 old_string 上下文保证唯一，或确认后 replace_all=true；"
        "外部修改冲突 → 重新 read_file 后基于最新内容重试；"
        "写入/校验失败会如实返回原因，文件保持原状（原子写入不产生半成品）。"
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目标文件路径"},
            "old_string": {
                "type": "string",
                "description": "要被替换的原文（需与文件内容一致；换行风格/BOM 自动归一化；默认需唯一匹配）",
            },
            "new_string": {"type": "string", "description": "替换后的新内容"},
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

    def __init__(self, artifact_store: WorkspaceArtifactStore | None = None) -> None:
        self.artifact_store = artifact_store

    def execute(self, **kwargs) -> ToolResult:
        """框架统一调用约定 execute(**kwargs) → 委托 run(arguments dict)."""
        return self.run(kwargs)

    def _symlink_write_guard(self, path_str: str) -> tuple[Path, ToolResult | None]:
        """T5b symlink 写防护（fail-closed，R9-IMM-04 三态化）.

        仅 no_links 放行；links_found / probe_failed 均拒写（错误信息两态区分）。
        返回 (解析后路径, 拒绝回执或 None)。
        """
        path = Path(path_str)
        # 工作区跟随: 相对路径基于当前工作区根（无工作区 → 进程 cwd，零回归）
        if not path.is_absolute():
            from llm_loop.core.run_context import workspace_base

            path = Path(workspace_base()) / path
        _probe = link_shaped_paths(path)
        if _probe.status == "links_found":
            return path, self._fail(
                f"写路径含符号链接，已拒绝写入（防越界写）: {' → '.join(_probe.links)}。"
                "如需修改目标文件请使用其真实路径（realpath 解析后重试）。",
                "SymlinkGuard",
            )
        if _probe.status == "probe_failed":
            return path, self._fail(
                "符号链接探测失败（ELOOP/权限等障碍，无法确认路径安全性），已拒绝写入。"
                "请用 execute_command realpath 确认真实路径后重试。",
                "SymlinkGuard",
            )
        return path, None

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

        # ── T5b: symlink 写防护（fail-closed；对齐 Harness Unlink 模式；读面 read_file 仅标注）──
        path, _reject = self._symlink_write_guard(path_str)
        if _reject is not None:
            return _reject

        # ── 段1: read（bytes 读取，保留 BOM/换行风格信息 + 基线快照）──
        try:
            raw = path.read_bytes()
            source_bytes = raw
        except FileNotFoundError:
            return self._fail(f"文件不存在: {path_str}（可用 execute_command ls 确认路径）", "FileNotFoundError")
        except OSError as exc:
            return self._fail(f"读取失败: {type(exc).__name__}: {exc}", type(exc).__name__)

        try:
            baseline = self._baseline(path)
        except OSError as exc:
            return self._fail(f"基线快照失败: {type(exc).__name__}: {exc}", type(exc).__name__)

        had_bom = raw.startswith(_UTF8_BOM)
        if had_bom:
            raw = raw[len(_UTF8_BOM):]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            return self._fail(f"解码失败（非 UTF-8 文本）: {exc}", "UnicodeDecodeError")

        ending = _detect_line_ending(text)
        original = _normalize_lf(text)
        old_n, new_n = _normalize_lf(old), _normalize_lf(new)

        # ── 段2: match（唯一性校验，防锚点失配；LF 归一化后匹配）──
        count = original.count(old_n)
        if count == 0:
            return self._fail(
                f"old_string 未匹配（0 处，换行/BOM 已归一化后仍无匹配）。原因通常是缩进/文字与原文有差异。"
                f"建议: read_file 读取 {path_str} 目标区域获取精确文本后重试（不要用记忆里的内容）；"
                f"追加内容场景可改用 execute_command 的 cat >> 追加。",
                "NoMatch",
            )
        if count > 1 and not replace_all:
            return self._fail(
                f"old_string 匹配 {count} 处（非唯一，默认拒绝防误改）。"
                f"建议: 扩大 old_string 上下文（含前后行）保证唯一；或确认全部替换后 replace_all=true。",
                "MultipleMatches",
            )

        updated = original.replace(old_n, new_n)

        # ── 段3: diff 预览（归一化视图，如实标注）──
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
        full_diff_text = "\n".join(diff_lines)
        truncated = len(diff_lines) > _DIFF_MAX_LINES
        diff_text = "\n".join(diff_lines[:_DIFF_MAX_LINES])
        if truncated:
            diff_text += f"\n... [diff 过长已截断: 共 {len(diff_lines)} 行，显示前 {_DIFF_MAX_LINES} 行]"
        added = sum(1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++"))
        removed = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))

        if dry_run:
            visible_content = (
                f"[预览模式 dry_run: 未写入] {path_str}\n"
                f"匹配 {count} 处，变更 +{added}/-{removed} 行。确认无误后去掉 dry_run 应用。\n"
                f"```diff\n{diff_text}\n```"
            )
            raw_content = (
                f"[预览模式 dry_run: 未写入] {path_str}\n"
                f"匹配 {count} 处，变更 +{added}/-{removed} 行。确认无误后去掉 dry_run 应用。\n"
                f"```diff\n{full_diff_text}\n```"
            )
            from llm_loop.core.run_context import current_evidence_shadow_enabled

            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=visible_content,
                tool_call_id="",
                tool_name=self.name,
                raw_observation=raw_content if current_evidence_shadow_enabled.get() else None,
                evidence_source_version_token=f"stat:{baseline[0]}:{baseline[1]}",
            )

        # ── 段4: apply（基线校验 + 原子写入）+ verify（写后复读校验）──
        try:
            if self._baseline(path) != baseline:
                return self._fail(
                    "文件在读取后已被外部修改（mtime/size 变化），为避免覆盖他人改动已拒绝写入。"
                    "建议: 重新 read_file 获取最新内容后重试。",
                    "BaselineChanged",
                )
        except OSError as exc:
            return self._fail(f"写入前基线校验失败: {type(exc).__name__}: {exc}", type(exc).__name__)

        out_text = updated if ending == "\n" else updated.replace("\n", ending)
        out_bytes = (_UTF8_BOM if had_bom else b"") + out_text.encode("utf-8")

        # EW2-B: when this edit is owned by a durable tool-execution attempt, persist
        # exact mechanical intent before bytes can change. This is not a semantic
        # write-set guess: edit_file itself knows the one canonical target and exact
        # before/expected bytes. Legacy/direct calls without a binding keep old behavior.
        from llm_loop.core.tool_execution_journal import current_tool_effect_binding

        effect_binding = current_tool_effect_binding()
        if effect_binding is not None and effect_binding.tool_name == self.name:
            prepared = effect_binding.journal.effect_prepared(
                effect_binding.session_id,
                execution_id=effect_binding.execution_id,
                round_no=effect_binding.round_no,
                tool_call_id=effect_binding.tool_call_id,
                tool_name=effect_binding.tool_name,
                workspace_root=effect_binding.workspace_root,
                canonical_path=str(path),
                effect_kind="file_replace",
                before_bytes=source_bytes,
                expected_after_bytes=out_bytes,
            )
            if not prepared:
                return self._fail(
                    "执行效果准备事实未能持久化或目标路径越出当前工作区；为避免无主写入已拒绝修改。",
                    "EffectPreparedUnavailable",
                )

        try:
            fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(out_bytes)
                    f.flush()
                    os.fsync(f.fileno())
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
            reread = path.read_bytes()
        except OSError as exc:
            return self._fail(f"写入后校验读取失败: {type(exc).__name__}: {exc}（写入可能已生效，请人工核对）", type(exc).__name__)
        if reread != out_bytes:
            return self._fail(
                "写后校验失败: 复读内容与预期不一致（可能被并发修改）。文件当前状态需人工核对。",
                "VerifyMismatch",
            )

        post_stat = path.stat()
        artifact_fact: dict[str, object] | None = None
        artifact_error_type = ""
        if (
            effect_binding is not None
            and effect_binding.tool_name == self.name
            and effect_binding.journal.enabled
            and self.artifact_store is not None
        ):
            try:
                artifact = self.artifact_store.create(
                    workspace_scope=effect_binding.workspace_root,
                    canonical_path=str(path),
                    data=reread,
                    owner_session_id=effect_binding.session_id,
                    execution_id=effect_binding.execution_id,
                    tool_call_id=effect_binding.tool_call_id,
                    tool_name=effect_binding.tool_name,
                    effect_kind="file_replace",
                )
                artifact_fact = artifact.public_facts()
            except Exception as exc:  # noqa: BLE001 - successful bytes must never be rolled back
                artifact_error_type = type(exc).__name__
        if effect_binding is not None and effect_binding.tool_name == self.name:
            # Observation durability is factual telemetry only. If this append fails,
            # the successful verified file mutation remains truthful; restart recovery
            # can only use the prepared fact + current read-only fingerprint comparison.
            effect_binding.journal.effect_observed(
                session_id=effect_binding.session_id,
                execution_id=effect_binding.execution_id,
                round_no=effect_binding.round_no,
                tool_call_id=effect_binding.tool_call_id,
                tool_name=effect_binding.tool_name,
                workspace_root=effect_binding.workspace_root,
                canonical_path=str(path),
                effect_kind="file_replace",
                actual_after_bytes=reread,
                expected_after_bytes=out_bytes,
                actual_mtime_ns=post_stat.st_mtime_ns,
                artifact_ref=(
                    str(artifact_fact.get("artifact_ref") or "")
                    if artifact_fact is not None
                    else ""
                ),
            )

        preserved = []
        if had_bom:
            preserved.append("BOM")
        if ending != "\n":
            preserved.append("CRLF")
        preserved_note = f"（已保留原 {', '.join(preserved)}）" if preserved else ""
        # EVO-20260823-12be9cac: 写成功 → 翻转登记（文件已存在，否定帧失效）
        try:
            from llm_loop.tools.path_registry import register_exists

            register_exists(str(path))
        except Exception:  # noqa: BLE001 — fail-open
            pass
        visible_content = (
            f"[修改完成并已校验] {path_str}\n"
            f"替换 {count} 处，变更 +{added}/-{removed} 行（原子写入，写后复读一致{preserved_note}）。\n"
            f"```diff\n{diff_text}\n```"
        )
        raw_content = (
            f"[修改完成并已校验] {path_str}\n"
            f"替换 {count} 处，变更 +{added}/-{removed} 行（原子写入，写后复读一致{preserved_note}）。\n"
            f"```diff\n{full_diff_text}\n```"
        )
        if artifact_fact is not None:
            artifact_line = (
                "[artifact] "
                f"ref={artifact_fact['artifact_ref']} path={artifact_fact['path']} "
                f"sha256={artifact_fact['sha256']} size_bytes={artifact_fact['size_bytes']} "
                "identity=immutable_snapshot task_applicability=not_evaluated"
            )
            visible_content += "\n" + artifact_line
            raw_content += "\n" + artifact_line
        elif artifact_error_type:
            artifact_line = (
                "[artifact] artifact_ref_unavailable=true; "
                f"error_type={artifact_error_type}; source_action_status=success"
            )
            visible_content += "\n" + artifact_line
            raw_content += "\n" + artifact_line
        from llm_loop.core.run_context import current_evidence_shadow_enabled

        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=visible_content,
            tool_call_id="",
            tool_name=self.name,
            raw_observation=raw_content if current_evidence_shadow_enabled.get() else None,
            evidence_source_version_token=f"stat:{post_stat.st_mtime_ns}:{post_stat.st_size}",
            artifact_facts=((artifact_fact,) if artifact_fact is not None else ()),
        )

    @staticmethod
    def _baseline(path: Path) -> tuple[int, int]:
        """文件基线快照（mtime_ns + size），用于检测 read→apply 间的外部改动。"""
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)

    def _fail(self, msg: str, error_type: str = "ValueError") -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.ERROR,
            content=f"[修改失败] {msg}",
            tool_call_id="",
            tool_name=self.name,
            error_type=error_type,
            error_detail=msg,
        )
