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
from llm_loop.tools.trim import truncate_output

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
        "状态契约: 长输出超 3000 字符将截断（首尾保留 + 完整原文落盘 data/audit/tool_outputs/，"
        "legacy 模式可 read_file 落盘路径取全文或 full=true；Evidence enforce 模式改用稳定 EvidenceRef + read_evidence 恢复完整 observation；"
        "TOOL_TRIM_MAX 可调）。"
        + SHARED_SOURCE_RECOVERY_CONTRACT
        + source_recovery_guidance(SourceRecoveryKind.PROBEABLE_FILE)
        + "Evidence enforce 中 verified-current 且 coverage 已覆盖时由 resolver 复用 Evidence 并内联正文；"
        "无法内联时该次复用按 failure 如实回执（force_refresh=true 显式要求物理重读）。"
        "legacy/off 模式下超大文件仍可用 offset/limit 分段读取。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要读取的文件路径"},
            "offset": {"type": "integer", "description": "起始行号（0-based，默认 0）"},
            "limit": {"type": "integer", "description": "最多读取行数（默认全部）"},
            "full": {
                "type": "boolean",
                "description": "legacy 模式 true=跳过工具内 3000 字符截断；Evidence enforce 模式仍受统一 projection budget，完整 observation 用 read_evidence 恢复",
            },
            "force_refresh": {
                "type": "boolean",
                "description": "Evidence enforce 模式显式要求物理重新读取，即使 verified-current Evidence 已覆盖；默认 false",
            },
        },
        "required": ["path"],
    }

    def execute(self, **kwargs) -> ToolResult:
        path = str(kwargs.get("path", "")).strip()
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
            )
        offset = int(kwargs.get("offset", 0) or 0)
        limit = kwargs.get("limit")
        # EVO-20260819 full=true（按需全量）：跳过本工具截断（注册表层仍保硬上限安全阀）
        full = bool(kwargs.get("full", False))

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
            # 2026-08-21 摘要前置（用户洞察: 截断区保留必要信息）: 元信息放首行——
            # 大文件截断（truncate_output 保留首 1500）时，AI 先看到"路径/行数/范围"
            # 再是内容；避免截断后只有内容无元信息（原实现 numbered 开头，首行是文件内容）。
            meta = f"[read_file] {p} 共 {total} 行，显示 {start + 1}-{start + len(selected)} 行"
            content = meta + "\n" + numbered + note + _link_note
            from llm_loop.core.run_context import (
                current_evidence_enforce_enabled,
                current_evidence_shadow_enabled,
            )

            raw_observation = content if current_evidence_shadow_enabled.get() else None
            # Phase3 enforce: Registry must see/capture the unprojected observation first.
            # off/shadow preserve the exact legacy tool-internal trim behavior.
            if not full and not current_evidence_enforce_enabled.get():
                content = truncate_output(content, source=str(p))
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
