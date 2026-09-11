"""基础工具 1: 读取文件（design.md 模块 D / FR-TOOL-01）."""

from __future__ import annotations

import logging
from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.tools.safety import link_shaped_paths
from llm_loop.tools.source_recovery_contract import (
    SHARED_SOURCE_RECOVERY_CONTRACT,
    SourceRecoveryKind,
    source_recovery_guidance,
)
from llm_loop.workspace.artifacts import ARTIFACT_SCHEME, ArtifactError, WorkspaceArtifactStore
from llm_loop.workspace.file_effects import FileArtifactProvenance
from llm_loop.workspace.file_service import FileService, FileServiceError

logger = logging.getLogger(__name__)

# R8.24-C C-3.2（C-D6/C-G7）: 短路说明中被指名工具的声明式白名单——T8 式静态扫描
# 对照注册表逐一校验存在性（R8.7 注册事实原则：不得指名未注册工具）。
# capsule 退出后回执指名白名单收敛为两处：截断事实行（不含工具名）+ 本短路说明。
EVIDENCE_SHORT_CIRCUIT_REFERENCED_TOOLS: tuple[str, ...] = (
    "read_evidence",
    "get_tool_schema",
)


def evidence_ref_short_circuit_content(path: str) -> str:
    """C-D7: evidence:// 误用短路说明——陈述式协议事实（无祈使/劝导句式，C-G7 扫描口径）.

    四要素: ①这是 Evidence 引用非文件路径；②对应工具为 read_evidence；
    ③可经 get_tool_schema 检索发现；④evidence:// 不对应磁盘物理文件。
    """
    return (
        f"[参数误用] path 值 '{path}' 以 evidence:// 开头——这是 Evidence 引用"
        "（evidence:// scheme），不是文件系统路径；read_file 只处理文件系统路径。"
        "读取 Evidence 引用内容的工具是 read_evidence（已注册）。"
        "read_evidence 的完整定义可经 get_tool_schema 查询"
        "（如 tool_name='read_evidence' 或 '?evidence'）。"
        "evidence:// 引用不对应磁盘物理文件，物理文件操作需使用真实文件路径。"
    )


class ReadFileTool:
    name = "read_file"
    description = (
        "读取本地文件内容。何时用: 需要查看文件/代码/配置/任何文本文件内容时。"
        "何时不用: 需要列出目录或查找文件时（应选目录/查找类工具）；URL 不是文件路径。"
        "失败对策: 文件不存在/无权限会如实返回失败原因，请核对路径后重试或换工具。"
        "状态契约: 选定行范围的真实文本默认完整返回；仅统一 ToolRegistry/Evidence 的真实输出硬上限可截断，"
        "且只在存在真实 durable recovery 时声明可恢复。超大文件可用 offset/limit 分段读取。"
        + SHARED_SOURCE_RECOVERY_CONTRACT
        + source_recovery_guidance(SourceRecoveryKind.PROBEABLE_FILE)
        + "Evidence enforce 中 verified-current 且 coverage 已覆盖时由 resolver 复用 Evidence 并内联正文；"
        "无法内联时该次复用按 failure 如实回执（evidence_force_refresh=true 显式要求物理重读）。"
        "evidence_force_refresh 只改变 Evidence 复用/读取来源，不创建 snapshot_ref，也不能替代 snapshot=true 的版本 baseline；"
        "legacy/off 模式下超大文件仍可用 offset/limit 分段读取。"
        "snapshot=true 时强制物理观察当前完整文件并返回 file_contract_version=1 的 immutable baseline ref；"
        "versioned write 的机械配对是 read_file(snapshot=true) 取得当前完整字节 baseline，再由 "
        "edit_file(expected_snapshot_ref=<snapshot_ref>) 使用该 baseline；普通 snapshot=false 读取不会产生这个精确写前置条件；"
        "path 也可为 artifact://v1/...；此时读取当前工作区绑定的 immutable artifact snapshot，"
        "并如实报告其 workspace path 当前是否仍匹配该版本。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要读取的文件路径"},
            "offset": {"type": "integer", "description": "起始行号（0-based，默认 0）"},
            "limit": {"type": "integer", "description": "最多读取行数（默认全部）"},
            "evidence_force_refresh": {
                "type": "boolean",
                "description": "仅用于 Evidence enforce：即使 verified-current Evidence 已覆盖也绕过复用并物理重读；默认 false。它不创建 snapshot_ref，不能满足 edit_file.expected_snapshot_ref 的版本前置条件",
            },
            "snapshot": {
                "type": "boolean",
                "description": "为 true 时强制物理读取完整当前文件并保存 immutable baseline，返回 file_contract_version=1/snapshot_ref，可供 edit_file.expected_snapshot_ref 做精确写前置条件；默认 false，普通读取不产生该前置条件",
            },
        },
        "required": ["path"],
    }

    def __init__(
        self,
        artifact_store: WorkspaceArtifactStore | None = None,
        file_service: FileService | None = None,
    ) -> None:
        self.artifact_store = artifact_store
        self.file_service = file_service or (
            FileService(artifact_store=artifact_store) if artifact_store is not None else None
        )

    def execute(self, **kwargs) -> ToolResult:
        path = str(kwargs.get("path", "")).strip()
        if path.startswith(ARTIFACT_SCHEME):
            return self._read_artifact(path, kwargs)
        # R8.24-C C-D7: evidence:// 引用短路——path 取值后立即判定，先于 path_registry
        # 否定帧登记与任何磁盘 IO（防 evidence:// 被登记为"永不存在的物理路径"污染
        # 跨会话复用；r-p-r §0 死循环诱饵根除）。返回参数误用类 FAILURE（调用方式错误，
        # 非环境异常）+ 陈述式协议事实；失败回执零新 ref 零胶囊由 D2 status 门保证。
        if path.startswith("evidence://"):
            logger.info(
                "event=read_file_evidence_short_circuit kind=misuse_evidence_ref path=%s",
                path,
            )
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=evidence_ref_short_circuit_content(path),
                tool_call_id="",  # 由注册表填充
                tool_name=self.name,
                error_type="MisuseEvidenceRef",
                error_detail=(
                    "read_file received an evidence:// Evidence reference instead of a "
                    "filesystem path; read_evidence is the registered tool for Evidence refs"
                ),
                short_circuit_kind="misuse_evidence_ref",
                capability_requirements=("read_evidence",),
            )
        offset = int(kwargs.get("offset", 0) or 0)
        limit = kwargs.get("limit")
        snapshot_requested = bool(kwargs.get("snapshot", False))
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
        # R9-IMM-04 三态化：探测结果透传——links_found 标注链；probe_failed 标注
        # 探测障碍（读面 fail-open 不拒读；写面由 edit_file 对 probe_failed 拒写）
        _probe = link_shaped_paths(p)
        if _probe.status == "links_found":
            _link_note = f"\n[symlink] 路径含符号链接: {' → '.join(_probe.links)}"
        elif _probe.status == "probe_failed":
            _link_note = "\n[symlink] 符号链接探测失败（ELOOP/权限障碍）：路径安全性未确认（该路径写入将被 edit_file 拒绝）"
        else:
            _link_note = ""
        try:
            if not p.exists():
                # EVO-20260823-12be9cac: 失败登记否定帧 + 回执内嵌"已登记不存在"提示
                from llm_loop.tools.path_registry import (
                    known_missing_note,
                    register_missing,
                )

                register_missing(str(p), source="tool:read_file")
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=(
                        f"[文件不存在] {p} 不存在。请检查路径是否正确"
                        f"（可先用 list 类工具确认）。{known_missing_note(str(p))}"
                    ),
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
            if snapshot_requested:
                return self._read_physical_snapshot(
                    p,
                    offset=offset,
                    limit=(None if limit is None else int(limit)),
                    link_note=_link_note,
                )
            st_before = p.stat()
            file_text = p.read_text(encoding="utf-8", errors="replace")
            st_after = p.stat()
            version_token = (
                f"stat:{st_after.st_mtime_ns}:{st_after.st_size}"
                if (st_before.st_mtime_ns, st_before.st_size)
                == (st_after.st_mtime_ns, st_after.st_size)
                else None
            )
            lines = file_text.splitlines()
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
                    evidence_source_version_token=version_token,
                )
            numbered = "\n".join(f"{start + i + 1} | {ln}" for i, ln in enumerate(selected))
            note = f"\n[共 {total} 行，已显示 {len(selected)} 行]" if len(selected) < total else ""
            # 元信息首行提供路径/总行数/选定范围；正文保持真实字节直到统一 hard cap。
            meta = f"[read_file] {p} 共 {total} 行，显示 {start + 1}-{start + len(selected)} 行"
            content = meta + "\n" + numbered + note + _link_note
            from llm_loop.core.run_context import current_evidence_shadow_enabled

            raw_observation = content if current_evidence_shadow_enabled.get() else None
            # EVO-20260823-12be9cac: 成功翻转 + 登记正帧（存在 + 元数据，查询时 stat 对账）
            from llm_loop.tools.path_registry import register_seen

            register_seen(
                str(p),
                mtime=st_after.st_mtime_ns,
                size=st_after.st_size,
                kind="file",
            )
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=content,
                tool_call_id="",
                tool_name=self.name,
                raw_observation=raw_observation,
                evidence_source_version_token=version_token,
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

    def _read_physical_snapshot(
        self,
        path: Path,
        *,
        offset: int,
        limit: int | None,
        link_note: str,
    ) -> ToolResult:
        if self.file_service is None or self.artifact_store is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[snapshot unavailable] 当前运行时未装配共享 file service/artifact store。",
                tool_call_id="",
                tool_name=self.name,
                error_type="SnapshotUnavailable",
            )
        from llm_loop.core.run_context import (
            current_evidence_shadow_enabled,
            current_session_id,
            workspace_base,
        )
        from llm_loop.core.tool_execution_journal import current_tool_effect_binding

        scope = workspace_base()
        binding = current_tool_effect_binding()
        if binding is not None and binding.tool_name == self.name:
            provenance = FileArtifactProvenance(
                workspace_scope=scope,
                owner_session_id=str(binding.session_id),
                operation_id=str(binding.execution_id),
                tool_call_id=str(binding.tool_call_id),
                tool_name=self.name,
                effect_kind="file_observation",
            )
        else:
            provenance = FileArtifactProvenance(
                workspace_scope=scope,
                owner_session_id=str(current_session_id.get() or ""),
                operation_id="",
                tool_name=self.name,
                effect_kind="file_observation",
            )
        try:
            observation = self.file_service.observe(
                path=path,
                workspace_scope=scope,
                provenance=provenance,
                offset=offset,
                limit=limit,
            )
        except FileServiceError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[snapshot 失败] {exc.error_type}",
                tool_call_id="",
                tool_name=self.name,
                error_type=exc.error_type,
                error_detail=exc.detail or exc.error_type,
            )

        start, end = observation.content_range
        header = (
            f"[read_file snapshot] {path} 共 {observation.total_lines} 行，"
            f"显示 {start + 1}-{end} 行 "
            f"file_contract_version={observation.file_contract_version} "
            f"snapshot_ref={observation.snapshot_ref} sha256={observation.sha256} "
            f"size_bytes={observation.size_bytes} "
            f"workspace_path_state={observation.workspace_path_state}"
        )
        selected = observation.content.splitlines()
        if selected:
            numbered = "\n".join(f"{start + i + 1} | {line}" for i, line in enumerate(selected))
            note = (
                f"\n[共 {observation.total_lines} 行，已显示 {len(selected)} 行]"
                if len(selected) < observation.total_lines
                else ""
            )
            content = header + "\n" + numbered + note + link_note
        else:
            content = header + "\n[空文件或所选范围无内容]" + link_note
        facts = {
            "artifact_ref": observation.snapshot_ref,
            "path": observation.path,
            "size_bytes": observation.size_bytes,
            "sha256": observation.sha256,
            "created_at": observation.observed_at,
            "artifact_identity": "immutable_snapshot",
            "task_applicability": "not_evaluated",
        }
        try:
            from llm_loop.tools.path_registry import register_seen

            stat = path.stat()
            register_seen(
                str(path),
                mtime=stat.st_mtime_ns,
                size=stat.st_size,
                kind="file",
            )
        except Exception:  # noqa: BLE001 - derived path cache remains fail-open
            pass
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=content,
            tool_call_id="",
            tool_name=self.name,
            raw_observation=content if current_evidence_shadow_enabled.get() else None,
            evidence_source_version_token=observation.source_version_token,
            artifact_facts=(facts,),
        )

    def _read_artifact(self, ref: str, kwargs: dict) -> ToolResult:
        if self.artifact_store is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    "[artifact unavailable] 当前运行时未装配 artifact store；"
                    "该引用未被当作文件系统路径处理。"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type="ArtifactStoreUnavailable",
            )
        from llm_loop.core.run_context import current_evidence_shadow_enabled, workspace_base

        scope = workspace_base()
        try:
            snapshot, data = self.artifact_store.hydrate(ref, workspace_scope=scope)
        except ArtifactError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[artifact 无法读取] {exc}",
                tool_call_id="",
                tool_name=self.name,
                error_type="ArtifactError",
                error_detail=str(exc),
            )

        offset = int(kwargs.get("offset", 0) or 0)
        limit = kwargs.get("limit")
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        start = max(0, min(offset, total))
        selected = lines[start:]
        if limit is not None:
            selected = selected[: int(limit)]
        record = snapshot.record
        header = (
            f"[read_file artifact] ref={record.ref} path={record.relative_path} "
            f"sha256={record.sha256} size_bytes={record.size_bytes} "
            f"workspace_path_state={snapshot.workspace_path_state} "
            "artifact_identity=immutable_snapshot task_applicability=not_evaluated"
        )
        if selected:
            numbered = "\n".join(f"{start + i + 1} | {line}" for i, line in enumerate(selected))
            note = f"\n[共 {total} 行，已显示 {len(selected)} 行]" if len(selected) < total else ""
            content = header + "\n" + numbered + note
        else:
            content = header + "\n[空 artifact 或所选范围无内容]"
        facts = snapshot.public_facts()
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=content,
            tool_call_id="",
            tool_name=self.name,
            raw_observation=content if current_evidence_shadow_enabled.get() else None,
            evidence_source_version_token=f"artifact-sha256:{record.sha256}",
            artifact_facts=(facts,),
        )
