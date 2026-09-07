"""Model-authored synopsis persistence over exact durable source references."""

from __future__ import annotations

import json
from collections.abc import Callable

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_model_label, current_session_id, workspace_base
from llm_loop.memory.synopsis import (
    MAX_SOURCE_READ_CHARS,
    SourceSnapshot,
    SynopsisError,
    SynopsisStore,
)

SourceResolver = Callable[[str], SourceSnapshot]


class SourceSynopsisTool:
    name = "source_synopsis"
    description = (
        "保存或读取模型自己形成的长源摘要。save 仅在模型已读取所需 exact source/chunks 后，"
        "把模型提供的 summary 绑定到 source_ref 的确切 SHA/范围；程序不生成摘要、不判断重要性或任务适用性。"
        "read_summary 精确读取模型已保存摘要；read_source 按 synopsis:<id> 回读当时绑定的 immutable exact source snapshot；摘要永不替代原文。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["save", "read_summary", "read_source"]},
            "source_ref": {
                "type": "string",
                "maxLength": 512,
                "description": "save: attachment://, artifact://v1/, evidence://v1/ 或 truncated: exact source ref",
            },
            "summary": {"type": "string", "maxLength": 32000, "description": "save: 当前模型自己写出的摘要正文"},
            "source_start": {"type": "integer", "minimum": 0, "description": "save: 摘要绑定范围起点，0-based，默认0"},
            "source_end": {"type": "integer", "minimum": 1, "description": "save: 摘要绑定范围终点exclusive，默认exact source末尾"},
            "expected_source_sha256": {
                "type": "string",
                "description": "save: 若前一读取已给出source SHA，可作为版本前置条件；不匹配则拒绝保存",
            },
            "synopsis_ref": {"type": "string", "maxLength": 64, "description": "read_source: synopsis:<id>"},
            "offset": {"type": "integer", "minimum": 0, "description": "read_source: exact snapshot字符起点，默认0"},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_SOURCE_READ_CHARS,
                "description": f"read_source: 本次字符数，默认/硬上限 {MAX_SOURCE_READ_CHARS}",
            },
        },
        "required": ["action"],
    }

    def __init__(self, store: SynopsisStore, source_resolver: SourceResolver) -> None:
        self.store = store
        self.source_resolver = source_resolver

    def execute(self, **kwargs) -> ToolResult:
        action = str(kwargs.get("action") or "").strip()
        if action == "save":
            return self._save(kwargs)
        if action == "read_summary":
            return self._read_summary(kwargs)
        if action == "read_source":
            return self._read_source(kwargs)
        return self._failure("[参数错误] action 必须为 save、read_summary 或 read_source。")

    def _save(self, kwargs: dict) -> ToolResult:
        source_ref = str(kwargs.get("source_ref") or "").strip()
        summary = str(kwargs.get("summary") or "")
        if not source_ref:
            return self._failure("[参数错误] save 缺少 source_ref。")
        if not summary.strip():
            return self._failure("[参数错误] save 缺少非空 summary。")
        try:
            source = self.source_resolver(source_ref)
            end_raw = kwargs.get("source_end")
            record = self.store.create(
                workspace_scope=workspace_base(),
                session_id=current_session_id.get(),
                source=source,
                summary=summary,
                source_start=int(kwargs.get("source_start", 0) or 0),
                source_end=None if end_raw is None else int(end_raw),
                summary_model=current_model_label.get(),
                expected_source_sha256=str(kwargs.get("expected_source_sha256") or ""),
            )
        except (SynopsisError, TypeError, ValueError) as exc:
            return self._failure(f"[synopsis 保存失败] {exc}")
        payload = {
            "schema": "source_synopsis_v1",
            "kind": "synopsis_saved",
            "synopsis_ref": record.ref,
            "source_ref": record.source_ref,
            "source_kind": record.source_kind,
            "source_sha256": record.source_sha256,
            "source_chars": record.source_chars,
            "source_complete": record.source_complete,
            "snapshot_complete": True,
            "source_start": record.source_start,
            "source_end": record.source_end,
            "range_sha256": record.range_sha256,
            "summary_sha256": record.summary_sha256,
            "summary_chars": record.summary_chars,
            "summary_model": record.summary_model,
            "representation": record.representation,
            "coverage_semantics": "model_declared_source_range_not_semantically_verified",
            "task_applicability": "not_evaluated",
            "automatic_replay": False,
        }
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(payload, ensure_ascii=False),
            tool_call_id="",
            tool_name=self.name,
        )

    def _read_summary(self, kwargs: dict) -> ToolResult:
        ref = str(kwargs.get("synopsis_ref") or "").strip()
        if not ref:
            return self._failure("[参数错误] read_summary 缺少 synopsis_ref。")
        try:
            record = self.store.get(
                ref, workspace_scope=workspace_base(), session_id=current_session_id.get()
            )
        except (SynopsisError, TypeError, ValueError) as exc:
            return self._failure(f"[synopsis 读取失败] {exc}")
        if record is None:
            return self._failure("[synopsis 不可用] 当前 workspace/session 无此引用。")
        source_ref_state = "not_checked"
        try:
            current = self.source_resolver(record.source_ref)
            source_ref_state = (
                "same_snapshot"
                if current.source_sha256 == record.source_sha256
                else "changed_representation"
            )
        except Exception:  # noqa: BLE001 - optional source-ref identity probe only
            source_ref_state = "unavailable"
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(
                record.hydrated(source_ref_state=source_ref_state),
                ensure_ascii=False,
                sort_keys=True,
            ),
            tool_call_id="",
            tool_name=self.name,
        )

    def _read_source(self, kwargs: dict) -> ToolResult:
        ref = str(kwargs.get("synopsis_ref") or "").strip()
        if not ref:
            return self._failure("[参数错误] read_source 缺少 synopsis_ref。")
        try:
            offset = int(kwargs.get("offset", 0) or 0)
            limit = int(kwargs.get("limit", MAX_SOURCE_READ_CHARS) or MAX_SOURCE_READ_CHARS)
            if offset < 0 or limit <= 0:
                raise ValueError("offset>=0 且 limit>0")
            page = self.store.read_source(
                ref,
                workspace_scope=workspace_base(),
                session_id=current_session_id.get(),
                offset=offset,
                max_chars=limit,
            )
        except (SynopsisError, TypeError, ValueError) as exc:
            return self._failure(f"[synopsis source 读取失败] {exc}")
        if page is None:
            return self._failure("[synopsis 不可用] 当前 workspace/session 无此引用。")
        header = {
            key: value for key, value in page.items() if key != "content"
        }
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                json.dumps(header, ensure_ascii=False, sort_keys=True)
                + "\n[exact_source]\n"
                + str(page["content"])
            ),
            tool_call_id="",
            tool_name=self.name,
        )

    def _failure(self, content: str) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=content,
            tool_call_id="",
            tool_name=self.name,
        )


__all__ = ["SourceSynopsisTool"]
