"""基础工具: 四段式文件修改（edit_file）.

M51（能力盘点短板改进）: 替代 execute_command + sed/heredoc 盲替换的脆弱路径。
四段式语义（一次调用内完成，每段失败如实回执不伪装）:
  1. read    读取原文件（不存在/无权限如实报错；EVO-20260814-aab7eb0b 起记录基线 mtime+size）
  2. match   old_string 唯一性校验（0 处/多处均失败并给修正引导，防锚点失配）
  3. diff    生成统一 diff 预览（回执可见，dry_run=true 时仅预览不写入）
  4. apply+verify  临时文件 + os.replace 原子写入，写后复读校验（失败如实报）

P2-A: 上述机械字节算法由 workspace.file_service.FileService 统一承接；
本工具仅保留模型协议、现有安全入口和 ToolResult 适配。外部 schema 暂不改变。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.tools.safety import link_shaped_paths
from llm_loop.workspace.artifacts import WorkspaceArtifactStore
from llm_loop.workspace.file_service import FileEditResult, FileService, FileServiceError


class _ToolJournalFileEffectSink:
    """Adapt the existing model-tool WAL to the workspace FileEffectSink contract."""

    effect_kind = "file_replace"

    def __init__(self, binding: Any) -> None:
        self._binding = binding
        self.workspace_scope = str(binding.workspace_root)
        self.owner_session_id = str(binding.session_id)
        self.operation_id = str(binding.execution_id)
        self.tool_call_id = str(binding.tool_call_id)
        self.tool_name = str(binding.tool_name)

    @property
    def records_durable(self) -> bool:
        return bool(self._binding.journal.enabled)

    def prepared(
        self,
        *,
        canonical_path: Path,
        before_bytes: bytes,
        expected_after_bytes: bytes,
    ) -> bool:
        binding = self._binding
        return bool(
            binding.journal.effect_prepared(
                binding.session_id,
                execution_id=binding.execution_id,
                round_no=binding.round_no,
                tool_call_id=binding.tool_call_id,
                tool_name=binding.tool_name,
                workspace_root=binding.workspace_root,
                canonical_path=str(canonical_path),
                effect_kind=self.effect_kind,
                before_bytes=before_bytes,
                expected_after_bytes=expected_after_bytes,
            )
        )

    def observed(
        self,
        *,
        canonical_path: Path,
        actual_after_bytes: bytes,
        expected_after_bytes: bytes,
        actual_mtime_ns: int | None,
        artifact_ref: str,
    ) -> bool:
        binding = self._binding
        return bool(
            binding.journal.effect_observed(
                session_id=binding.session_id,
                execution_id=binding.execution_id,
                round_no=binding.round_no,
                tool_call_id=binding.tool_call_id,
                tool_name=binding.tool_name,
                workspace_root=binding.workspace_root,
                canonical_path=str(canonical_path),
                effect_kind=self.effect_kind,
                actual_after_bytes=actual_after_bytes,
                expected_after_bytes=expected_after_bytes,
                actual_mtime_ns=actual_mtime_ns,
                artifact_ref=artifact_ref,
            )
        )


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
        "versioned-write 机械合同: 先 read_file(snapshot=true) 取得 snapshot_ref，再把它原样传入 expected_snapshot_ref；"
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
            "expected_snapshot_ref": {
                "type": "string",
                "description": "read_file(snapshot=true) 返回的 artifact ref；提供时写前精确核对同工作区、同路径、完整字节版本",
            },
        },
        "required": ["path", "old_string", "new_string"],
    }

    def __init__(
        self,
        artifact_store: WorkspaceArtifactStore | None = None,
        file_service: FileService | None = None,
        *,
        require_version_precondition: bool = False,
    ) -> None:
        if require_version_precondition and artifact_store is None:
            raise ValueError("require_version_precondition requires artifact_store")
        self.artifact_store = artifact_store
        self.require_version_precondition = bool(require_version_precondition)
        # Strictness is an explicit assembly fact, never inferred from task meaning.
        # Bare/custom registries retain historical optional behavior.
        if self.require_version_precondition:
            self.parameters = {
                **type(self).parameters,
                "properties": dict(type(self).parameters["properties"]),
                "required": [
                    *type(self).parameters["required"],
                    "expected_snapshot_ref",
                ],
            }
            self.description = (
                type(self).description
                + "当前实例启用 immutable version precondition；机器 schema 要求 expected_snapshot_ref。"
            )
        self._file_service = file_service or FileService(
            artifact_store=artifact_store,
            # Keep the legacy baseline hook observable for existing tests/callers.
            baseline_reader=lambda path: self._baseline(path),
        )

    def execute(self, **kwargs) -> ToolResult:
        """框架统一调用约定 execute(**kwargs) → 委托 run(arguments dict)."""
        return self.run(kwargs)

    def _symlink_write_guard(self, path_str: str) -> tuple[Path, ToolResult | None]:
        """T5b symlink 写防护（fail-closed，R9-IMM-04 三态化）."""
        path = Path(path_str)
        if not path.is_absolute():
            from llm_loop.core.run_context import workspace_base

            path = Path(workspace_base()) / path
        probe = link_shaped_paths(path)
        if probe.status == "links_found":
            return path, self._fail(
                f"写路径含符号链接，已拒绝写入（防越界写）: {' → '.join(probe.links)}。"
                "如需修改目标文件请使用其真实路径（realpath 解析后重试）。",
                "SymlinkGuard",
            )
        if probe.status == "probe_failed":
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
        expected_snapshot_ref = str(arguments.get("expected_snapshot_ref") or "").strip()

        if not path_str:
            return self._fail("缺少必填参数 path")
        if old is None or new is None:
            return self._fail("缺少必填参数 old_string/new_string")
        old, new = str(old), str(new)
        if old == "":
            return self._fail("old_string 为空无法定位（插入内容请锚定相邻原文）")

        if self.require_version_precondition and not dry_run and not expected_snapshot_ref:
            return self._fail(
                "当前 edit_file 实例要求 expected_snapshot_ref 版本前置条件；本次未写入。"
                "请先 read_file(snapshot=true) 获取当前文件 snapshot_ref 后重试。",
                "VersionPreconditionRequired",
            )

        path, reject = self._symlink_write_guard(path_str)
        if reject is not None:
            return reject

        from llm_loop.core.tool_execution_journal import current_tool_effect_binding

        binding = current_tool_effect_binding()
        sink = (
            _ToolJournalFileEffectSink(binding)
            if binding is not None and binding.tool_name == self.name
            else None
        )
        if expected_snapshot_ref and (sink is None or not sink.records_durable):
            return self._fail(
                "版本化写入要求 durable effect journal；当前记录设施不可用，本次未写入。",
                "EffectPreparedUnavailable",
            )
        from llm_loop.core.run_context import workspace_base

        try:
            result = self._file_service.edit(
                path=path,
                old_string=old,
                new_string=new,
                replace_all=replace_all,
                dry_run=dry_run,
                effect_sink=sink,
                workspace_scope=workspace_base(),
                expected_snapshot_ref=expected_snapshot_ref,
            )
        except FileServiceError as exc:
            return self._map_service_error(exc, path_str)

        return self._success_result(result, path_str)

    def _map_service_error(self, exc: FileServiceError, path_str: str) -> ToolResult:
        if exc.error_type == "FileNotFoundError":
            return self._fail(
                f"文件不存在: {path_str}（可用 execute_command ls 确认路径）",
                "FileNotFoundError",
            )
        if exc.error_type == "ReadError":
            return self._fail(
                f"读取失败: {exc.cause_type}: {exc.detail}", exc.cause_type or "OSError"
            )
        if exc.error_type == "BaselineSnapshotFailed":
            return self._fail(
                f"基线快照失败: {exc.cause_type}: {exc.detail}",
                exc.cause_type or "OSError",
            )
        if exc.error_type == "UnicodeDecodeError":
            return self._fail(f"解码失败（非 UTF-8 文本）: {exc.detail}", "UnicodeDecodeError")
        if exc.error_type == "NoMatch":
            return self._fail(
                "old_string 未匹配（0 处，换行/BOM 已归一化后仍无匹配）。原因通常是缩进/文字与原文有差异。"
                f"建议: read_file 读取 {path_str} 目标区域获取精确文本后重试（不要用记忆里的内容）；"
                "追加内容场景可改用 execute_command 的 cat >> 追加。",
                "NoMatch",
            )
        if exc.error_type == "MultipleMatches":
            return self._fail(
                f"old_string 匹配 {exc.match_count} 处（非唯一，默认拒绝防误改）。"
                "建议: 扩大 old_string 上下文（含前后行）保证唯一；或确认全部替换后 replace_all=true。",
                "MultipleMatches",
            )
        if exc.error_type == "BaselineChanged":
            return self._fail(
                "文件在读取后已被外部修改（mtime/size 变化），为避免覆盖他人改动已拒绝写入。"
                "建议: 重新 read_file 获取最新内容后重试。",
                "BaselineChanged",
            )
        if exc.error_type == "BaselineCheckFailed":
            return self._fail(
                f"写入前基线校验失败: {exc.cause_type}: {exc.detail}",
                exc.cause_type or "OSError",
            )
        if exc.error_type == "VersionConflict":
            return self._fail(
                "版本冲突: 当前完整文件字节已不同于 expected_snapshot_ref；本次未写入。",
                "VersionConflict",
            )
        if exc.error_type in {"VersionPreconditionInvalid", "WorkspaceScopeMismatch"}:
            return self._fail(
                "版本前置条件无效: snapshot 不属于当前工作区/路径或无法完整验证；本次未写入。",
                "VersionPreconditionInvalid",
            )
        if exc.error_type == "PathLockUnavailable":
            return self._fail(
                "协调写锁不可用，无法保证本次文件写入的并发边界；本次未写入。",
                "PathLockUnavailable",
            )
        if exc.error_type == "EffectPreparedUnavailable":
            return self._fail(
                "执行效果准备事实未能持久化或目标路径越出当前工作区；为避免无主写入已拒绝修改。",
                "EffectPreparedUnavailable",
            )
        if exc.error_type == "WriteFailed":
            return self._fail(
                f"写入失败: {exc.cause_type}: {exc.detail}（文件保持原状，原子写入未产生半成品）",
                exc.cause_type or "OSError",
            )
        if exc.error_type == "VerifyReadFailed":
            return self._fail(
                f"写入后校验读取失败: {exc.cause_type}: {exc.detail}（写入可能已生效，请人工核对）",
                exc.cause_type or "OSError",
            )
        if exc.error_type == "VerifyMismatch":
            return self._fail(
                "写后校验失败: 复读内容与预期不一致（可能被并发修改）。文件当前状态需人工核对。",
                "VerifyMismatch",
            )
        return self._fail(exc.detail or exc.error_type, exc.error_type)

    def _success_result(self, result: FileEditResult, path_str: str) -> ToolResult:
        if result.dry_run:
            visible_content = (
                f"[预览模式 dry_run: 未写入] {path_str}\n"
                f"匹配 {result.match_count} 处，变更 +{result.added_lines}/-{result.removed_lines} 行。"
                "确认无误后去掉 dry_run 应用。\n"
                f"```diff\n{result.diff_text}\n```"
            )
            raw_content = (
                f"[预览模式 dry_run: 未写入] {path_str}\n"
                f"匹配 {result.match_count} 处，变更 +{result.added_lines}/-{result.removed_lines} 行。"
                "确认无误后去掉 dry_run 应用。\n"
                f"```diff\n{result.full_diff_text}\n```"
            )
            if result.expected_snapshot_ref:
                contract_line = (
                    "[file_contract] version=1 precondition_checked=true "
                    f"expected_snapshot_ref={result.expected_snapshot_ref}"
                )
                visible_content += "\n" + contract_line
                raw_content += "\n" + contract_line
            from llm_loop.core.run_context import current_evidence_shadow_enabled

            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=visible_content,
                tool_call_id="",
                tool_name=self.name,
                raw_observation=raw_content if current_evidence_shadow_enabled.get() else None,
                evidence_source_version_token=(
                    f"stat:{result.baseline_before[0]}:{result.baseline_before[1]}"
                ),
            )

        preserved = []
        if result.had_bom:
            preserved.append("BOM")
        if result.line_ending != "\n":
            preserved.append("CRLF")
        preserved_note = f"（已保留原 {', '.join(preserved)}）" if preserved else ""

        try:
            from llm_loop.tools.path_registry import register_exists

            register_exists(str(result.path))
        except Exception:  # noqa: BLE001 - path cache remains derived/fail-open
            pass

        visible_content = (
            f"[修改完成并已校验] {path_str}\n"
            f"替换 {result.match_count} 处，变更 +{result.added_lines}/-{result.removed_lines} 行"
            f"（原子写入，写后复读一致{preserved_note}）。\n"
            f"```diff\n{result.diff_text}\n```"
        )
        raw_content = (
            f"[修改完成并已校验] {path_str}\n"
            f"替换 {result.match_count} 处，变更 +{result.added_lines}/-{result.removed_lines} 行"
            f"（原子写入，写后复读一致{preserved_note}）。\n"
            f"```diff\n{result.full_diff_text}\n```"
        )
        if result.artifact_fact is not None:
            artifact = result.artifact_fact
            artifact_line = (
                "[artifact] "
                f"ref={artifact['artifact_ref']} path={artifact['path']} "
                f"sha256={artifact['sha256']} size_bytes={artifact['size_bytes']} "
                "identity=immutable_snapshot task_applicability=not_evaluated"
            )
            visible_content += "\n" + artifact_line
            raw_content += "\n" + artifact_line
        elif result.artifact_error_type:
            artifact_line = (
                "[artifact] artifact_ref_unavailable=true; "
                f"error_type={result.artifact_error_type}; source_action_status=success"
            )
            visible_content += "\n" + artifact_line
            raw_content += "\n" + artifact_line

        if result.expected_snapshot_ref:
            contract_line = (
                "[file_contract] version=1 precondition_checked=true "
                f"expected_snapshot_ref={result.expected_snapshot_ref} "
                f"receipt_state={result.receipt_state}"
            )
            visible_content += "\n" + contract_line
            raw_content += "\n" + contract_line
        from llm_loop.core.run_context import current_evidence_shadow_enabled

        post = result.post_baseline
        assert post is not None
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=visible_content,
            tool_call_id="",
            tool_name=self.name,
            raw_observation=raw_content if current_evidence_shadow_enabled.get() else None,
            evidence_source_version_token=f"stat:{post[0]}:{post[1]}",
            artifact_facts=((result.artifact_fact,) if result.artifact_fact is not None else ()),
        )

    @staticmethod
    def _baseline(path: Path) -> tuple[int, int]:
        """Legacy baseline hook retained while FileService owns the algorithm."""
        return FileService.baseline(path)

    def _fail(self, msg: str, error_type: str = "ValueError") -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.ERROR,
            content=f"[修改失败] {msg}",
            tool_call_id="",
            tool_name=self.name,
            error_type=error_type,
            error_detail=msg,
        )
