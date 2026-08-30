"""Agent-facing Evidence recovery tools for ERC Phase 4.

Owner scope is injected by runtime and is never accepted from model arguments.  These tools
operate on already-captured Evidence and are intentionally bounded; ToolRegistry treats them
as recovery control-plane calls and does not recursively capture their own outputs.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.memory.evidence import (
    BlobStore,
    EvidenceAuthDeniedError,
    EvidenceBlobLostError,
    EvidenceCorruptedError,
    EvidenceFreshness,
    EvidenceHydration,
    EvidenceLedgerStore,
    EvidenceRef,
    EvidenceRefUnknownError,
    EvidenceSearch,
    FreshnessState,
    OwnerScope,
    RangeType,
    SourceKind,
    SourceVersionPolicy,
)

_OWNER_HIDDEN = "当前会话无权访问该 Evidence，或该 Evidence 不存在。"


class EvidenceReadTool:
    name = "read_evidence"
    description = (
        "按稳定 EvidenceRef 精确恢复此前已获取的工具观察，不重新执行原工具。"
        "适用于上下文压缩/截断后恢复原证据；必须分页读取，不能传 workspace/session。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "evidence_ref": {"type": "string", "description": "evidence://v1/... 稳定引用"},
            "range_type": {
                "type": "string",
                "enum": ["text_char", "line"],
                "description": "text_char=Unicode字符范围；line=Evidence observation 行范围",
            },
            "start": {"type": "integer", "description": "0-based 起点，默认 0"},
            "limit": {"type": "integer", "description": "本次最多读取数量，默认 200，硬上限 4000"},
            "allow_stale": {
                "type": "boolean",
                "description": "仅历史/审计用途显式读取已确认 stale 的 FILE Evidence；默认 false",
            },
        },
        "required": ["evidence_ref"],
    }

    def __init__(
        self,
        blobs: BlobStore,
        ledger: EvidenceLedgerStore,
        *,
        freshness: EvidenceFreshness,
        owner_resolver: Callable[[], OwnerScope],
        max_limit: int = 4000,
    ) -> None:
        self.hydration = EvidenceHydration(blobs, ledger, max_limit=max_limit)
        self.ledger = ledger
        self.freshness = freshness
        self.owner_resolver = owner_resolver

    def execute(self, **kwargs) -> ToolResult:
        try:
            ref = EvidenceRef(str(kwargs.get("evidence_ref", "")).strip())
            range_type = RangeType(str(kwargs.get("range_type", "text_char") or "text_char"))
            start = int(kwargs.get("start", 0) or 0)
            limit = int(kwargs.get("limit", 200) or 200)
            allow_stale = kwargs.get("allow_stale", False)
            if not isinstance(allow_stale, bool):
                raise ValueError("allow_stale must be boolean")
        except (TypeError, ValueError) as exc:
            return _failure(self.name, f"[参数错误] {exc}")
        owner = self.owner_resolver()
        try:
            state = self.freshness.refresh(owner=owner, evidence_ref=ref)
            record = self.ledger.require_authorized(owner, ref)
            if (
                state.freshness is FreshnessState.STALE
                and record.source.kind is SourceKind.FILE
                and record.source.version_policy is SourceVersionPolicy.PROBEABLE
                and not allow_stale
            ):
                return _failure(
                    self.name,
                    json.dumps(
                        {
                            "schema": "evidence_hydration_v2",
                            "kind": "evidence_hydration_blocked",
                            "transport": _transport_payload(ref),
                            "source": _source_payload(record),
                            "freshness": _freshness_payload(state.freshness),
                            "policy": {
                                "reason": "probeable_source_stale",
                                "refresh_required": True,
                                "historical_read_requires": "allow_stale=true",
                            },
                        },
                        ensure_ascii=False,
                    ),
                )
            result = self.hydration.read(
                owner=owner,
                evidence_ref=ref,
                range_type=range_type,
                start=start,
                limit=limit,
            )
        except (EvidenceAuthDeniedError, EvidenceRefUnknownError):
            return _failure(self.name, f"[Evidence 不可用] {_OWNER_HIDDEN}")
        except EvidenceBlobLostError:
            return _error(self.name, "[Evidence blob 丢失] logical record 存在，但 durable blob 不可读取。")
        except EvidenceCorruptedError:
            return _error(self.name, "[Evidence 损坏] durable blob 完整性校验失败。")
        except (TypeError, ValueError) as exc:
            return _failure(self.name, f"[范围错误] {exc}")

        payload = {
            "schema": "evidence_hydration_v2",
            "kind": "evidence_hydration",
            "transport": _transport_payload(result.evidence_ref),
            "source": _source_payload(record),
            "freshness": _freshness_payload(state.freshness),
            "range": {
                "type": result.range_type.value,
                "start": result.start,
                "count": result.count,
                "next_start": result.next_start,
                "complete": result.next_start is None,
            },
            "integrity": {
                "blob_sha256": result.blob_sha256,
                "range_sha256": result.range_sha256,
            },
            "content": result.content,
        }
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(payload, ensure_ascii=False),
            tool_call_id="",
            tool_name=self.name,
        )


class EvidenceListTool:
    name = "list_evidence"
    description = (
        "无需关键词列出当前会话最近 Evidence 恢复清单。"
        "当压缩后忘了文件名/命令名时先用本工具发现稳定 ref，再 read_evidence 精确恢复。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "条目数，默认 10，最大 20"},
            "scope": {
                "type": "string",
                "enum": ["recent", "recovery"],
                "description": (
                    "recent=最近 Evidence；recovery=按 durable Recovery Manifest 优先级"
                    "列出最值得恢复的 bounded refs（忘记关键词/path 时优先）"
                ),
            },
        },
        "required": [],
    }

    def __init__(
        self,
        ledger: EvidenceLedgerStore,
        *,
        freshness: EvidenceFreshness,
        owner_resolver: Callable[[], OwnerScope],
        recovery_manifest_provider: Callable[[int], str] | None = None,
    ) -> None:
        self.ledger = ledger
        self.freshness = freshness
        self.owner_resolver = owner_resolver
        self.recovery_manifest_provider = recovery_manifest_provider

    def execute(self, **kwargs) -> ToolResult:
        try:
            limit = int(kwargs.get("limit", 10) or 10)
        except (TypeError, ValueError) as exc:
            return _failure(self.name, f"[参数错误] {exc}")
        if limit <= 0 or limit > 20:
            return _failure(self.name, "[参数错误] limit 必须在 1..20")
        scope = str(kwargs.get("scope", "recent") or "recent").strip().lower()
        if scope not in {"recent", "recovery"}:
            return _failure(self.name, "[参数错误] scope 必须是 recent 或 recovery")
        if scope == "recovery":
            if self.recovery_manifest_provider is None:
                return _failure(self.name, "[恢复目录不可用] 当前运行时未配置 Recovery Manifest。")
            try:
                manifest = str(self.recovery_manifest_provider(limit) or "")
            except Exception as exc:  # noqa: BLE001 — explicit recovery failure is reported
                return _failure(self.name, f"[恢复目录不可用] {type(exc).__name__}: {exc}")
            if not manifest:
                return ToolResult(
                    status=ToolResultStatus.SUCCESS,
                    content="[list_evidence/recovery] 当前会话暂无可恢复 Evidence。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=manifest,
                tool_call_id="",
                tool_name=self.name,
            )
        owner = self.owner_resolver()
        records = self.ledger.list_recent(owner, limit=limit)
        if not records:
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="[list_evidence] 当前会话暂无可恢复 Evidence。",
                tool_call_id="",
                tool_name=self.name,
            )
        total = self.ledger.count(owner)
        lines = [f"[list_evidence] 最近 {len(records)}/{total} 条："]
        for record in records:
            try:
                state = self.freshness.refresh(owner=owner, evidence_ref=record.evidence_ref)
                freshness = state.freshness.value
            except (EvidenceAuthDeniedError, EvidenceRefUnknownError):
                continue
            lines.append(
                f"- ref={record.evidence_ref.ref} source={record.tool_name}:"
                f"{record.source.safe_locator} coverage={record.coverage.label} "
                f"freshness={freshness} acquired_at={record.acquired_at}"
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="\n".join(lines),
            tool_call_id="",
            tool_name=self.name,
        )


class EvidenceSearchTool:
    name = "search_evidence"
    description = (
        "在当前会话 durable Evidence 中检索已获取证据，不重新执行原 source。"
        "默认多词 AND；显式 OR 表示备选；双引号表示连续 phrase；返回命中位置附近片段和 EvidenceRef。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索表达式，如 error timeout、foo OR bar、\"exact phrase\""},
            "limit": {"type": "integer", "description": "最大命中条数，默认 10，最大 20"},
            "tool_name": {"type": "string", "description": "可选：只检索指定原始工具的 Evidence"},
            "allow_stale": {
                "type": "boolean",
                "description": "仅历史/审计用途显式返回已确认 stale 的 FILE Evidence snippet；默认 false",
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        search: EvidenceSearch,
        *,
        freshness: EvidenceFreshness,
        owner_resolver: Callable[[], OwnerScope],
    ) -> None:
        self.search = search
        self.freshness = freshness
        self.owner_resolver = owner_resolver

    def execute(self, **kwargs) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        try:
            limit = int(kwargs.get("limit", 10) or 10)
        except (TypeError, ValueError) as exc:
            return _failure(self.name, f"[参数错误] {exc}")
        if limit <= 0 or limit > 20:
            return _failure(self.name, "[参数错误] limit 必须在 1..20")
        allow_stale = kwargs.get("allow_stale", False)
        if not isinstance(allow_stale, bool):
            return _failure(self.name, "[参数错误] allow_stale must be boolean")
        owner = self.owner_resolver()
        tool_name = str(kwargs.get("tool_name", "") or "").strip() or None
        try:
            result = self.search.search(
                owner=owner, query=query, limit=limit, tool_name=tool_name
            )
        except ValueError as exc:
            return _failure(self.name, f"[参数错误] {exc}")
        if not result.hits:
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=f"[search_evidence] 未找到匹配 {query!r} 的当前会话 Evidence。",
                tool_call_id="",
                tool_name=self.name,
            )
        lines = [f"[search_evidence] 命中 {len(result.hits)}/{result.total_hits}："]
        for hit in result.hits:
            try:
                state = self.freshness.refresh(owner=owner, evidence_ref=hit.evidence_ref)
                record = self.search.ledger.require_authorized(owner, hit.evidence_ref)
            except (EvidenceAuthDeniedError, EvidenceRefUnknownError):
                continue
            freshness = state.freshness.value
            currentness = _currentness(state.freshness)
            stale_probeable_file = (
                state.freshness is FreshnessState.STALE
                and record.source.kind is SourceKind.FILE
                and record.source.version_policy is SourceVersionPolicy.PROBEABLE
            )
            if stale_probeable_file and not allow_stale:
                lines.append(
                    f"- ref={hit.evidence_ref.ref} source={hit.source_label} "
                    f"freshness={freshness} currentness={currentness} content=blocked "
                    "historical_search_requires=allow_stale=true"
                )
                continue
            snippet = " ".join(hit.snippet.split())
            lines.append(
                f"- ref={hit.evidence_ref.ref} source={hit.source_label} "
                f"freshness={freshness} currentness={currentness} "
                f"match_char={hit.snippet_start_char}\n  {snippet}"
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="\n".join(lines),
            tool_call_id="",
            tool_name=self.name,
        )



def _currentness(freshness: FreshnessState) -> str:
    if freshness is FreshnessState.VERIFIED_CURRENT:
        return "current"
    if freshness is FreshnessState.STALE:
        return "historical_only"
    return "unverified"


def _transport_payload(ref: EvidenceRef) -> dict[str, object]:
    return {
        "evidence_ref": ref.ref,
        "role": "recovery_handle",
        "is_domain_content": False,
    }


def _freshness_payload(freshness: FreshnessState) -> dict[str, object]:
    return {
        "state": freshness.value,
        "currentness": _currentness(freshness),
        "verified_current": freshness is FreshnessState.VERIFIED_CURRENT,
    }


def _source_payload(record) -> dict[str, str]:
    return {
        "tool_name": record.tool_name,
        "kind": record.source.kind.value,
        "label": record.source.safe_locator,
        "coverage": record.coverage.label,
    }

def _failure(tool_name: str, content: str) -> ToolResult:
    return ToolResult(
        status=ToolResultStatus.FAILURE,
        content=content,
        tool_call_id="",
        tool_name=tool_name,
    )


def _error(tool_name: str, content: str) -> ToolResult:
    return ToolResult(
        status=ToolResultStatus.ERROR,
        content=content,
        tool_call_id="",
        tool_name=tool_name,
    )


class SearchArchiveCompatTool(EvidenceSearchTool):
    """Enforce-mode compatibility alias for historical search_archive instructions.

    It intentionally uses the new Evidence search semantics and never calls legacy ArchiveStore
    substring search.  ``with_summary`` is accepted for schema compatibility but ignored: Phase5
    recovery returns exact match snippets + stable refs instead of generating a new LLM summary.
    """

    name = "search_archive"
    description = (
        "Evidence enforce 兼容入口：历史提示中的 search_archive 会转入新的 owner-scoped "
        "Evidence 检索。多词默认 AND，支持 OR/引号 phrase；命中返回稳定 ref，完整内容用 "
        "read_evidence。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索表达式"},
            "limit": {"type": "integer", "description": "最大命中条数，默认 10，最大 20"},
            "tool_name": {"type": "string", "description": "可选工具名过滤"},
            "allow_stale": {
                "type": "boolean",
                "description": "仅历史/审计用途显式返回 stale FILE snippet；默认 false",
            },
            "with_summary": {
                "type": "boolean",
                "description": "兼容旧参数；新路径不自动生成 LLM 摘要",
            },
        },
        "required": ["query"],
    }

    def execute(self, **kwargs) -> ToolResult:
        result = super().execute(**kwargs)
        result.content = result.content.replace(
            "[search_evidence]", "[search_archive→search_evidence]", 1
        )
        return result
