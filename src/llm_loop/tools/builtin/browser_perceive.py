"""Model-facing read-only Browser SMC perception tool.

The tool can snapshot only a page already bound by the host backend and hydrate exact
GroundingRefs.  It intentionally has no URL/script/selector/action parameter and performs
no navigation or mutation.  Host/runtime activation is a separate integration decision.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from llm_loop.browser.method_card import SEMANTIC_OPERATION_METHOD_CARD
from llm_loop.browser.perception import BrowserPerceptionAdapter
from llm_loop.browser.predicate import predicate_parameter_schema, validate_predicate
from llm_loop.core.message import ToolResult, ToolResultStatus

_MAX_WAIT_MS = 60_000
_MAX_INTERVAL_MS = 5_000


def _iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


class BrowserCaptureBackend(Protocol):
    def capture(self) -> dict[str, Any]: ...


class BrowserPerceiveTool:
    name = "browser_perceive"
    description = (
        SEMANTIC_OPERATION_METHOD_CARD
        + " "
        "SMC Browser Phase 1 只读感知。snapshot=读取 host 已绑定的当前页面 DOM+AX，返回"
        "WorldSnapshot + SemanticObject；不会打开 URL、导航、点击、输入、滚动、执行脚本或自动重试。"
        "hydrate=按精确 GroundingRef 水合该次历史 observation；diff=仅比较两张已落盘 exact snapshot，"
        "不会重抓当前页面，也不会按名称/角色猜测对象对应关系。wait=对 structured Predicate 做只读轮询；"
        "wait 仅用于真实时间条件，不替代 snapshot/execute；scope predicate 必须 target=scope_ref，且两者都取当前 observation 的 exact scope_ref；"
        "interval_ms 必须为整数 1..5000。超时未满足是 observation，不是工具故障；感官/coverage 不足返回 indeterminate。"
        "ref 过期/跨 session/不可用会如实返回。"
        "模型面只出现 Semantic ID/scope/GroundingRef，不暴露 CSS/XPath/坐标/CDP node id/AX index。"
        "完整方法可按 method_ref 用 search_records(kind=method, query=<exact ref>) 精确水合；"
        "是否加载完整方法和如何应用由模型决定。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["snapshot", "hydrate", "diff", "wait"],
                "description": (
                    "snapshot=当前已绑定页面只读 DOM+AX 感知；"
                    "hydrate=精确水合 grounding_ref；diff=比较两张 exact snapshot；"
                    "wait=轮询一个 closed structured Predicate"
                ),
            },
            "projection_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 500,
                "description": "snapshot 首屏投影对象上限；不改变底层 observation completeness",
            },
            "grounding_ref": {
                "type": "string",
                "description": "hydrate 的精确 grounding://browser/v0.1/... 引用",
            },
            "from_version": {
                "type": "string",
                "description": "diff 起点的精确 Browser snapshot_id",
            },
            "to_version": {
                "type": "string",
                "description": "diff 终点的精确 Browser snapshot_id",
            },
            "predicate": predicate_parameter_schema(),
            "timeout_ms": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_WAIT_MS,
                "description": "wait 总观察预算；超时未满足返回 unsatisfied/indeterminate，不自动改动作策略",
            },
            "interval_ms": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_INTERVAL_MS,
                "description": "wait polling 采样间隔；必须为整数 1..5000；采样不是 action retry",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        adapter: BrowserPerceptionAdapter,
        backend: BrowserCaptureBackend | None,
        session_id_getter: Callable[[], str],
    ) -> None:
        self._adapter = adapter
        self._backend = backend
        self._session_id_getter = session_id_getter

    def _json_result(self, payload: dict[str, Any]) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1),
            tool_call_id="",
            tool_name=self.name,
        )

    def _fail(self, content: str) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=content,
            tool_call_id="",
            tool_name=self.name,
        )

    @staticmethod
    def _bounded_wait_int(raw: Any, *, name: str, maximum: int) -> tuple[int | None, str | None]:
        if isinstance(raw, bool) or not isinstance(raw, int):
            return None, f"{name} 必须是整数 1..{maximum}"
        if raw < 1 or raw > maximum:
            return None, f"{name} 必须在 1..{maximum}"
        return raw, None

    def _wait(self, session_id: str, kwargs: dict[str, Any]) -> ToolResult:
        if self._backend is None:
            return self._fail(
                "[browser_perceive:wait] read-only Browser backend unavailable; 未执行 mutation/legacy fallback。"
            )
        predicate = kwargs.get("predicate")
        validation_error = validate_predicate(predicate)
        if validation_error is not None:
            return self._fail(f"[browser_perceive:wait] predicate contract rejected: {validation_error}")
        assert isinstance(predicate, dict)  # narrowed by validate_predicate

        timeout_ms, timeout_error = self._bounded_wait_int(
            kwargs.get("timeout_ms"), name="timeout_ms", maximum=_MAX_WAIT_MS
        )
        if timeout_error is not None or timeout_ms is None:
            return self._fail(f"[browser_perceive:wait] {timeout_error}")
        interval_ms, interval_error = self._bounded_wait_int(
            kwargs.get("interval_ms"), name="interval_ms", maximum=_MAX_INTERVAL_MS
        )
        if interval_error is not None or interval_ms is None:
            return self._fail(f"[browser_perceive:wait] {interval_error}")

        start_mono = time.monotonic()
        deadline_mono = start_mono + timeout_ms / 1000.0
        deadline_epoch = time.time() + timeout_ms / 1000.0
        deadline = _iso_utc(deadline_epoch)
        sample_count = 0
        observer_error_count = 0
        observed_at = _iso_utc(time.time())
        observation: dict[str, Any] = {
            "result": "indeterminate",
            "snapshot_id": None,
            "scope_ref": str(predicate["scope_ref"]),
            "target": str(predicate["target"]),
            "property": str(predicate["property"]),
            "observed_value": None,
            "coverage_complete": False,
            "reason": "observer_error",
            "objects_ref": "",
        }

        while True:
            # The first sample is immediate.  Subsequent poll samples may start
            # only while the monotonic wait budget is still open; sleeping to
            # the deadline must not authorize one extra post-deadline capture.
            if sample_count > 0 and time.monotonic() >= deadline_mono:
                break
            sample_count += 1
            try:
                raw = self._backend.capture()
                snapshot_result = self._adapter.snapshot(
                    session_id,
                    raw,
                    projection_limit=1,
                )
            except Exception as exc:  # noqa: BLE001 - observer failure is a tri-state fact.
                observer_error_count += 1
                observed_at = _iso_utc(time.time())
                observation = {
                    "result": "indeterminate",
                    "snapshot_id": None,
                    "scope_ref": str(predicate["scope_ref"]),
                    "target": str(predicate["target"]),
                    "property": str(predicate["property"]),
                    "observed_value": None,
                    "coverage_complete": False,
                    "reason": "observer_error",
                    "observer_error_type": type(exc).__name__,
                    "objects_ref": "",
                }
            else:
                snapshot = dict(snapshot_result.get("snapshot") or {})
                snapshot_id = str(snapshot.get("snapshot_id") or "")
                observed_at = str(snapshot.get("observed_at") or "") or _iso_utc(time.time())
                try:
                    observation = self._adapter.evaluate_predicate(
                        session_id,
                        snapshot_id,
                        predicate,
                    )
                except Exception as exc:  # noqa: BLE001 - evaluator faults are implementation errors.
                    return ToolResult(
                        status=ToolResultStatus.ERROR,
                        content=(
                            "[browser_perceive:wait] predicate evaluation failed; "
                            f"error_type={type(exc).__name__}; error={exc}"
                        ),
                        tool_call_id="",
                        tool_name=self.name,
                        error_type=type(exc).__name__,
                        error_detail=str(exc),
                    )
                if observation.get("result") == "satisfied":
                    break

            now = time.monotonic()
            if now >= deadline_mono:
                break
            remaining = deadline_mono - now
            time.sleep(min(interval_ms / 1000.0, remaining))

        predicate_result = {
            "result": str(observation.get("result") or "indeterminate"),
            "evaluation_mode": "polling",
            "observed_at": observed_at,
            "deadline": deadline,
            "interval_ms": interval_ms,
            "sample_count": sample_count,
            "observer_error_count": observer_error_count,
        }
        return self._json_result(
            {
                "action": "wait",
                "predicate": predicate,
                "predicate_result": predicate_result,
                "observation": observation,
            }
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip()
        session_id = str(self._session_id_getter() or "").strip()
        if not session_id:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[browser_perceive] 当前 session identity 不可用；未执行 Browser observation。",
                tool_call_id="",
                tool_name=self.name,
            )
        if action == "wait":
            return self._wait(session_id, kwargs)
        if action == "hydrate":
            ref = str(kwargs.get("grounding_ref") or "").strip()
            if not ref:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[browser_perceive:hydrate] grounding_ref 为空；必须给精确 GroundingRef。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            return self._json_result(
                {"action": "hydrate", **self._adapter.hydrate(session_id, ref)}
            )
        if action == "diff":
            from_version = str(kwargs.get("from_version") or "").strip()
            to_version = str(kwargs.get("to_version") or "").strip()
            if not from_version or not to_version:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=(
                        "[browser_perceive:diff] from_version/to_version 必须都是精确 Browser snapshot_id。"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )
            try:
                return self._json_result(
                    self._adapter.diff(session_id, from_version, to_version)
                )
            except Exception as exc:  # noqa: BLE001 - exact diff failure must remain visible.
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    content=(
                        "[browser_perceive:diff] exact snapshot diff failed; "
                        f"error_type={type(exc).__name__}; error={exc}"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                    error_type=type(exc).__name__,
                    error_detail=str(exc),
                )
        if action == "snapshot":
            if self._backend is None:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=(
                        "[browser_perceive:snapshot] read-only Browser backend unavailable; "
                        "未执行 navigation/legacy playwright fallback。"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )
            try:
                projection_limit = int(kwargs.get("projection_limit", 200) or 200)
            except (TypeError, ValueError):
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[browser_perceive:snapshot] projection_limit 必须是整数 1..500。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            projection_limit = max(1, min(projection_limit, 500))
            try:
                raw = self._backend.capture()
                return self._json_result(
                    self._adapter.snapshot(
                        session_id,
                        raw,
                        projection_limit=projection_limit,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - observation failure must remain explicit.
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    content=(
                        "[browser_perceive:snapshot] observation failed; "
                        f"error_type={type(exc).__name__}; error={exc}"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                    error_type=type(exc).__name__,
                    error_detail=str(exc),
                )
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[browser_perceive] action 必须是 snapshot、hydrate、diff 或 wait。",
            tool_call_id="",
            tool_name=self.name,
        )
