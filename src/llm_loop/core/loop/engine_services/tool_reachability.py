"""Prompt-neutral tool reachability facts.

P1-B keeps this recorder as observability only: registered tools, the mechanically
available provider surface, runtime-health quarantine, model declarations, and actual
execution receipts. Retired eligibility/promotion/capability-selection state is not
reconstructed here.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

TOOL_REACHABILITY_LOG_ENV = "TOOL_REACHABILITY_LOG"
DEFAULT_LOG_PATH = os.path.join("data", "observability", "tool_reachability.jsonl")


def _log_path() -> str:
    """Resolve the prompt-neutral observability sink; ``off`` disables disk writes."""
    raw = str(os.environ.get(TOOL_REACHABILITY_LOG_ENV, "") or "").strip()
    if raw.lower() in {"off", "0", "false", "disabled"}:
        return ""
    return raw or DEFAULT_LOG_PATH


_BASE_FIELDS: tuple[str, ...] = (
    "ts",
    "session_id",
    "round",
    "registered_tools",
    "candidate_tools",
    "final_provider_callable_tools",
    "quarantined_tools",
    "emissions",
    "executed",
)


def _schema_tool_name(schema: Any) -> str:
    """从 provider tool schema 提取工具名（OpenAI function 风格优先，顶层 name 兜底）."""
    if not isinstance(schema, dict):
        return ""
    fn = schema.get("function")
    if isinstance(fn, dict):
        return str(fn.get("name", "") or "")
    return str(schema.get("name", "") or "")


def tool_schema_names(schemas: list[Any] | None) -> list[str]:
    """批量提取 schema 工具名（无名/非法条目过滤，保持次序）."""
    return [n for n in (_schema_tool_name(t) for t in schemas or []) if n]


class RoundReachabilityRecorder:
    """每轮工具可达性记录器（服务级单实例，逐轮覆盖后 flush 追加落盘）.

    轮次边界：projection（模型本轮实际可调用集）→ emission（模型 raw 声明）→
    executed（真实执行回执）→ flush（一行 JSONL）。
    flush 成功后当前轮清空并保留 last_flushed 供事后检视；重复 flush 不重复落盘。
    """

    def __init__(self, path: str | None = None) -> None:
        self._path_override = path
        self._record: dict[str, Any] = {}
        self._last_projection_template: dict[str, Any] = {}
        self._attempt_seq = 0
        self.last_flushed: dict[str, Any] = {}

    # ── 内部 ────────────────────────────────────────────────────

    def _ensure_base(self) -> None:
        """防御路径（未经 begin_round 直接记录）也保证字段形状完整."""
        if not self._record:
            self.begin_round()

    # ── 轮次生命周期 ──────────────────────────────────────────────

    def begin_round(
        self,
        *,
        session_id: str = "",
        round_no: int = 0,
    ) -> None:
        # A new projection must never silently overwrite an unfinished provider attempt.
        if self._record:
            self.finalize("superseded_unfinalized")
        self._record = {
            "ts": time.time(),
            "session_id": session_id,
            "round": round_no,
            "attempt_id": "",
            "attempt_kind": "",
            "attempt_index": 0,
            "model": "",
            "provider": "",
            "outcome": "",
            "registered_tools": [],
            "candidate_tools": [],
            "final_provider_callable_tools": [],
            "quarantined_tools": [],
            "emissions": [],
            "executed": [],
        }

    def record_projection(
        self,
        *,
        registered: list[str] | None = None,
        candidate: list[str] | None = None,
        final_callable: list[str] | None = None,
        quarantined: list[str] | None = None,
    ) -> None:
        self._ensure_base()
        self._record["registered_tools"] = list(registered or [])
        self._record["candidate_tools"] = list(candidate or [])
        self._record["final_provider_callable_tools"] = list(final_callable or [])
        self._record["quarantined_tools"] = list(quarantined or [])

        self._last_projection_template = copy.deepcopy(self._record)

    def bind_attempt(
        self,
        *,
        kind: str,
        attempt_index: int = 0,
        model: str = "",
        provider: str = "",
    ) -> str:
        """Bind provider-attempt identity to the current factual projection."""
        self._ensure_base()
        self._attempt_seq += 1
        attempt_id = f"attempt-{self._attempt_seq}"
        self._record["attempt_id"] = attempt_id
        self._record["attempt_kind"] = str(kind or "unknown")
        self._record["attempt_index"] = int(attempt_index or 0)
        self._record["model"] = str(model or "")
        self._record["provider"] = str(provider or "")
        return attempt_id

    def begin_attempt_from_last_projection(
        self,
        *,
        kind: str,
        attempt_index: int = 0,
        model: str = "",
        provider: str = "",
    ) -> str:
        """Start a retry provider attempt from the same factual tool projection."""
        if self._record:
            self.finalize("superseded_unfinalized")
        template = copy.deepcopy(self._last_projection_template)
        if not template:
            self.begin_round()
        else:
            template["ts"] = time.time()
            template["attempt_id"] = ""
            template["attempt_kind"] = ""
            template["attempt_index"] = 0
            template["model"] = ""
            template["provider"] = ""
            template["outcome"] = ""
            template["emissions"] = []
            template["executed"] = []
            self._record = template
        return self.bind_attempt(
            kind=kind, attempt_index=attempt_index, model=model, provider=provider
        )

    def ensure_attempt(
        self,
        *,
        kind: str,
        attempt_index: int = 0,
        model: str = "",
        provider: str = "",
    ) -> str:
        """Bind a fresh re-projection or clone the last projection for a retry."""
        if self._record and not self._record.get("attempt_id"):
            return self.bind_attempt(
                kind=kind, attempt_index=attempt_index, model=model, provider=provider
            )
        return self.begin_attempt_from_last_projection(
            kind=kind, attempt_index=attempt_index, model=model, provider=provider
        )

    def record_emission(self, calls: list[dict] | None) -> None:
        """raw→parsed 声明链：raw_arguments=线上 JSON 串；arguments=解析后 dict."""
        self._ensure_base()
        self._record["emissions"] = [
            {
                "tool_call_id": c.get("tool_call_id", ""),
                "name": c.get("name", ""),
                "raw_arguments": c.get("raw_arguments", ""),
                "arguments": c.get("arguments"),
                "valid": bool(c.get("valid")),
            }
            for c in calls or []
        ]

    def record_executed(self, entries: list[dict] | None) -> None:
        """executed 回执链（真实执行 + duplicate-guard 阻断帧一并如实记录）."""
        self._ensure_base()
        self._record["executed"] = [
            {
                "tool_call_id": e.get("tool_call_id", ""),
                "name": e.get("name", ""),
                "status": e.get("status", ""),
                "blocked": bool(e.get("blocked")),
            }
            for e in entries or []
        ]

    # ── 落盘 ────────────────────────────────────────────────────

    def finalize(self, outcome: str) -> bool:
        """Finalize exactly one provider attempt (idempotent after record is cleared)."""
        if not self._record:
            return False
        self._record["outcome"] = str(outcome or "unknown")
        self._record["finished_ts"] = time.time()
        if not self._record.get("attempt_id"):
            # Build/projection failed before a real provider call; preserve as explicit
            # non-provider diagnostic instead of pretending a request occurred.
            self._record["attempt_kind"] = self._record.get("attempt_kind") or "projection_only"
        path = self._path_override if self._path_override is not None else _log_path()
        if not path:
            self.last_flushed = copy.deepcopy(self._record)
            self._record = {}
            return False
        return self.flush()

    def flush(self) -> bool:
        """当前轮记录追加落盘（一行 JSONL）；返回是否成功（fail-open，不抛错）."""
        if not self._record:
            return False
        path = self._path_override if self._path_override is not None else _log_path()
        if not path:
            return False
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(self._record, ensure_ascii=False, default=str) + "\n")
            self.last_flushed = self._record
            self._record = {}
            return True
        except Exception:  # noqa: BLE001 — observability must not block the run
            logger.debug("tool reachability flush failed (fail-open)", exc_info=True)
            return False

    @property
    def current(self) -> dict[str, Any]:
        """当前轮未落盘快照（供测试与内存观测；只读约定）."""
        return self._record
