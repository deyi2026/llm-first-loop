"""Model-facing read-only Browser SMC perception tool.

The tool observes only a page already bound by the host backend and hydrates exact
GroundingRefs. It performs no navigation or mutation. Provider-facing wait is a flat,
root-discriminated read-only branch that compiles mechanically to internal typed waits;
poll cadence stays runtime-owned. Host/runtime activation is a separate integration decision.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, Protocol

from llm_loop.browser.errors import (
    MultiPageAmbiguityError,
    PageTargetNotFoundError,
)
from llm_loop.browser.method_card import SEMANTIC_OPERATION_METHOD_REF
from llm_loop.browser.perception import BrowserPerceptionAdapter
from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.timekeeping import system_local_now
from llm_loop.tools.builtin.browser_wait import (
    ABSENT_SETTLE_DEFAULT_MS,
    BrowserWaitObjectStateTool,
    BrowserWaitObjectTextTool,
    BrowserWaitScopeReadyTool,
    BrowserWaitScopeUrlTool,
)


class BrowserCaptureBackend(Protocol):
    def capture(self) -> dict[str, Any]: ...


class BrowserPerceiveTool:
    name = "browser_perceive"
    description = (
        "Browser 只读感知：snapshot 读取 host 已绑定当前页面，hydrate 精确水合既有 ref，"
        "diff 比较两张 exact snapshot，wait 只读等待页面 ready/URL 或已观察对象 state/text。"
        "页面 wait 机械绑定当前 host-bound page；对象 wait 必须使用 exact grounding_ref。"
        "M2-B B7：wait kind=object_absent 为负条件等待——元素消失需在窗口内累计稳定"
        " settle_ms（默认 300，可覆盖 50..10000）才成立，中途回闪重置计时；"
        "超时回执 state=present（明确失败）。"
        "M2-B B9：action=pages 健康态只读页面清单（id/url/title/是否绑定 + 当前"
        " world_version）；不换绑、不建会话——需要切页仍走显式 target_id 独立动作。"
        "运行时拥有轮询节奏和默认超时；不导航、不 mutation、不 fuzzy/latest/auto-select/retry，"
        "多标签歧义时返回只读页面清单；可用显式 target_id 换绑指定页（EVO-20261007）。"
        "不判断 task completion，也不暴露 selector/坐标/CDP node id/AX index。"
        f"method_ref={SEMANTIC_OPERATION_METHOD_REF}。"
    )
    _PROVIDER_BRANCHES = [
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["snapshot"]},
                "target_id": {"type": "string", "minLength": 1},
                "projection_limit": {"type": "integer", "minimum": 1, "maximum": 500},
                "projection_kinds": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "projection_cursor": {"type": "integer", "minimum": 0},
                "vision": {"type": "string", "enum": ["evidence"]},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["hydrate"]},
                "target_id": {"type": "string", "minLength": 1},
                "grounding_ref": {"type": "string", "minLength": 1},
            },
            "required": ["action", "grounding_ref"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["diff"]},
                "target_id": {"type": "string", "minLength": 1},
                "from_version": {"type": "string", "minLength": 1},
                "to_version": {"type": "string", "minLength": 1},
            },
            "required": ["action", "from_version", "to_version"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["wait"]},
                "target_id": {"type": "string", "minLength": 1},
                "kind": {"type": "string", "enum": ["page_ready"]},
                "state": {"type": "string", "enum": ["loading", "interactive", "complete"]},
                "within_ms": {"type": "integer", "minimum": 1, "maximum": 60_000},
            },
            "required": ["action", "kind", "state"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["wait"]},
                "target_id": {"type": "string", "minLength": 1},
                "kind": {"type": "string", "enum": ["page_url"]},
                "match": {
                    "type": "string",
                    "enum": ["equals", "contains", "starts_with", "ends_with"],
                },
                "expected_url": {"type": "string"},
                "within_ms": {"type": "integer", "minimum": 1, "maximum": 60_000},
            },
            "required": ["action", "kind", "match", "expected_url"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["wait"]},
                "target_id": {"type": "string", "minLength": 1},
                "kind": {"type": "string", "enum": ["object_state"]},
                "grounding_ref": {"type": "string", "minLength": 1},
                "state": {
                    "type": "string",
                    "enum": [
                        "exists",
                        "enabled",
                        "checked",
                        "selected",
                        "expanded",
                        "focused",
                        "editable",
                    ],
                },
                "value": {"type": "boolean"},
                "within_ms": {"type": "integer", "minimum": 1, "maximum": 60_000},
            },
            "required": ["action", "kind", "grounding_ref", "state", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["wait"]},
                "target_id": {"type": "string", "minLength": 1},
                "kind": {"type": "string", "enum": ["object_text"]},
                "grounding_ref": {"type": "string", "minLength": 1},
                "field": {"type": "string", "enum": ["name", "value_text"]},
                "match": {
                    "type": "string",
                    "enum": ["equals", "contains", "starts_with", "ends_with"],
                },
                "text": {"type": "string"},
                "within_ms": {"type": "integer", "minimum": 1, "maximum": 60_000},
            },
            "required": ["action", "kind", "grounding_ref", "field", "match", "text"],
            "additionalProperties": False,
        },
        {
            # M2-A B6 (DESIGN-20261027 §5.2): download completion wait. The
            # session-fenced dir + event state come from the mutation
            # actuator's download_state; completed returns path/size/sha256.
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["wait"]},
                "target_id": {"type": "string", "minLength": 1},
                "kind": {"type": "string", "enum": ["download_state"]},
                "expected": {"type": "string", "enum": ["completed", "failed"]},
                "within_ms": {"type": "integer", "minimum": 1, "maximum": 60_000},
            },
            "required": ["action", "kind", "expected"],
            "additionalProperties": False,
        },
        {
            # M2-B B7 (DESIGN-20261027 §4.1/B7, §7.3.4): negative-condition
            # wait. Absence only succeeds after settle_ms of UNBROKEN
            # absence (default 300ms; mid-window re-appearance resets the
            # timer); timeout reports state=present - an explicit failure,
            # never a maybe-gone answer.
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["wait"]},
                "target_id": {"type": "string", "minLength": 1},
                "kind": {"type": "string", "enum": ["object_absent"]},
                "grounding_ref": {"type": "string", "minLength": 1},
                "settle_ms": {"type": "integer", "minimum": 50, "maximum": 10_000},
                "within_ms": {"type": "integer", "minimum": 1, "maximum": 60_000},
            },
            "required": ["action", "kind", "grounding_ref"],
            "additionalProperties": False,
        },
        {
            # M2-B B9 (DESIGN-20261027 §4.1/B9): healthy-state read-only page
            # listing. Same /json/list channel the multi-page miss receipt
            # uses (EVO-20261007-11ae668f); NO target_id here - rebind is a
            # separate explicit action, a listing must never side-effect one.
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["pages"]},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    ]
    parameters = {
        "type": "object",
        # Keep the shallow union for provider compatibility, while oneOf branches below
        # are the authority for action-specific closed fields.
        "properties": {
            "action": {"type": "string", "enum": ["snapshot", "hydrate", "diff", "wait", "pages"]},
            "projection_kinds": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "description": (
                    "仅 snapshot（EVO-20260918-c69527a1）：按 SemanticObject.kind 过滤投影"
                    "（如 button/input/select/link）；matched_total/next_cursor 支持模型驱动分页；"
                    "零程序策略，服务端只机械限幅并如实回执"
                ),
            },
            "projection_cursor": {
                "type": "integer",
                "minimum": 0,
                "description": "仅 snapshot：配合 projection_kinds/limit 的投影窗口起点（0-based）",
            },
            "vision": {
                "type": "string",
                "enum": ["evidence"],
                "description": (
                    "仅 snapshot（EVO-20260918-f2310800）：请求视觉证据。固定参数截图（PNG）落盘并"
                    "在回执 vision 块返回 ref+path+sha256；M1 B10 起回执另带 page_id/world_version/"
                    "captured_at 与 content_unchanged（同 sha 复用同一 ref 时显式标注，不伪称新内容）；"
                    "视觉输出永远停在证据层，不进 objects/grounding/version；模型用 read_image 消费并自行裁决"
                ),
            },
            "projection_limit": {"type": "integer", "minimum": 1, "maximum": 500},
            "grounding_ref": {"type": "string", "minLength": 1},
            "from_version": {"type": "string", "minLength": 1},
            "to_version": {"type": "string", "minLength": 1},
            "kind": {
                "type": "string",
                "enum": [
                    "page_ready",
                    "page_url",
                    "object_state",
                    "object_text",
                    "download_state",
                    "object_absent",
                ],
            },
            "expected": {
                "type": "string",
                "enum": ["completed", "failed"],
                "description": (
                    "仅 wait kind=download_state（M2-A B6）：completed 返回会话下载目录内"
                    "该下载的 path/size/sha256/completed_by；failed 等待 canceled/失败态；"
                    "目录 realpath 围栏拒绝 ../ 与 symlink 逃逸（path_not_allowed）"
                ),
            },
            "settle_ms": {
                "type": "integer",
                "minimum": 50,
                "maximum": 10_000,
                "description": (
                    "仅 wait kind=object_absent（M2-B B7）：元素消失需在窗口内累计稳定"
                    " settle_ms（默认 300）才成立，中途回闪即重置计时；超时回执 state=present"
                ),
            },
            "state": {"type": "string"},
            "match": {
                "type": "string",
                "enum": ["equals", "contains", "starts_with", "ends_with"],
            },
            "expected_url": {"type": "string"},
            "value": {"type": "boolean"},
            "field": {"type": "string", "enum": ["name", "value_text"]},
            "text": {"type": "string"},
            "within_ms": {"type": "integer", "minimum": 1, "maximum": 60_000},
            "target_id": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "EVO-20261007-11ae668f：显式指定要绑定的 CDP page target_id"
                    "（来自页面清单回执的 page_id）。携带 target_id 的调用是一个独立动作："
                    "本调用只执行换绑（两 host 原子换到该页，同浏览器实例内，跨实例拒绝）并返回"
                    "回执；观察/操作动作需在下一次不带 target_id 的调用发起。"
                    "target_id 不在当前清单 ⇒ 确定性失败并返回当前页面清单。"
                ),
            },
        },
        "required": ["action"],
        "oneOf": _PROVIDER_BRANCHES,
        "additionalProperties": False,
    }

    # Generic lazy projection drops oneOf. This explicit provider schema preserves the
    # exact same root-direct branch structure on the stable prefix.
    lazy_parameters = parameters

    _FLAT_WAIT_FIELDS = {
        "page_ready": {"action", "kind", "state", "within_ms", "target_id"},
        "page_url": {"action", "kind", "match", "expected_url", "within_ms", "target_id"},
        "object_state": {"action", "kind", "grounding_ref", "state", "value", "within_ms", "target_id"},
        "object_text": {
            "action",
            "kind",
            "grounding_ref",
            "field",
            "match",
            "text",
            "within_ms",
            "target_id",
        },
        # M2-A B6: flat provider wait on the session download state machine.
        "download_state": {"action", "kind", "expected", "within_ms", "target_id"},
        # M2-B B7: negative-condition wait (absence + settle window).
        "object_absent": {"action", "kind", "grounding_ref", "settle_ms", "within_ms", "target_id"},
    }

    def __init__(
        self,
        *,
        adapter: BrowserPerceptionAdapter,
        backend: BrowserCaptureBackend | None,
        session_id_getter: Callable[[], str],
        exact_ref_hydrator: Callable[[str, str], dict[str, Any]] | None = None,
        profile_annotation: dict[str, Any] | None = None,
        page_controller: Any | None = None,
        download_state_getter: Callable[[], dict[str, Any]] | None = None,
        dialog_state_getter: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._adapter = adapter
        self._backend = backend
        self._session_id_getter = session_id_getter
        self._exact_ref_hydrator = exact_ref_hydrator
        # S2 三级授权（DESIGN-20261005 v4 §4.2）：仅 profile_class=real 且 ACK 合法时非 None，
        # 回执顶层带 profile_class/ack_digest/ack_expires；默认档保持 None ⇒ 输出字节级不变。
        self._profile_annotation = profile_annotation
        # EVO-20261007-11ae668f：显式换页协调器（可选注入；缺省 ⇒ target_id 参数不可用）。
        self._page_controller = page_controller
        # M2-A B6：下载状态探针（mutation actuator 的 download_state；可选注入，
        # 缺省 ⇒ wait kind=download_state 确定性失败，不静默轮询空状态）。
        self._download_state_getter = download_state_getter
        # R5：dialog 状态探针（mutation actuator 的 dialog_state；可选注入，
        # 缺省 ⇒ snapshot 快路径关闭，行为与之前逐字节一致）。
        self._dialog_state_getter = dialog_state_getter
        common_wait = {
            "adapter": adapter,
            "backend": backend,
            "session_id_getter": session_id_getter,
        }
        self._wait_scope_ready = BrowserWaitScopeReadyTool(**common_wait)
        self._wait_scope_url = BrowserWaitScopeUrlTool(**common_wait)
        self._wait_object_state = BrowserWaitObjectStateTool(**common_wait)
        self._wait_object_text = BrowserWaitObjectTextTool(**common_wait)

    def attach_download_state_probe(self, getter: Callable[[], dict[str, Any]]) -> None:
        """M2-A B6：装配期后挂（factory 在 mutation actuator 建好后注入其
        download_state 观察面；perceive 仍不获得任何 mutation 能力）。"""
        self._download_state_getter = getter

    def attach_dialog_state_probe(self, getter: Callable[[], dict[str, Any]]) -> None:
        """R5：装配期后挂（factory 注入 mutation actuator 的 dialog_state 观察面；
        perceive 仍不获得任何 mutation 能力，探针只读）。"""
        self._dialog_state_getter = getter

    def _dialog_block_facts(self) -> dict[str, Any] | None:
        """R5：capture 前的只读 dialog 探测；fail-open（探针自身异常一律
        fall through 到原 capture 路径，绝不让探针弄坏 snapshot）。"""
        if self._dialog_state_getter is None:
            return None
        try:
            state = self._dialog_state_getter()
        except Exception:  # noqa: BLE001 - probe failure must not break the snapshot path
            return None
        if isinstance(state, dict) and state.get("open") is True:
            return state
        return None

    def _dialog_blocked_snapshot_result(self, state: dict[str, Any], vision_request: str | None) -> ToolResult:
        """R5：dialog 打开期间的 snapshot 快路径回执。

        显式事实（blocked_by_dialog），零 capture、零 CDP mutation、零落盘；
        不伪装成正常快照（无 version/world_version——冻结页上不可能有新观察）。
        """
        dialog = state.get("dialog")
        dialog = dialog if isinstance(dialog, dict) else {}
        payload: dict[str, Any] = {
            "action": "snapshot",
            "observation_status": "blocked_by_dialog",
            "blocked_reason": "dialog_open",
            "dialog": {
                "type": dialog.get("type") if dialog.get("type") is not None else "unknown",
                "message": dialog.get("message"),
                "default_prompt": dialog.get("default_prompt"),
            },
            "objects": [],
            "degraded": False,
            "guidance": (
                "页面被同步 JS dialog 阻塞，快照通道冻结；请先调用 browser_operate "
                "do=dialog（action=accept 或 dismiss）处理 dialog，再重新发起 snapshot。"
            ),
        }
        if vision_request == "evidence":
            # 冻结页不可能产出新视觉证据：显式 unavailable，不落盘假图。
            payload["vision"] = {
                "status": "capture_unavailable",
                "reason": "dialog_open",
            }
        return self._json_result(payload)

    def _page_list_result(self, exc: MultiPageAmbiguityError) -> ToolResult:
        """多页歧义 ⇒ 结构化只读页面清单（不绑定、不建会话、无副作用）。"""

        payload = {
            "action": "page_list",
            "reason": "multi_page_ambiguity",
            "hint": (
                "CDP 端点当前暴露多个 page 且无已建绑定；不做任何自动选择。"
                "请人工/模型决策后，在下次 browser_perceive / browser_operate 调用中"
                "显式携带 target_id=<page_id> 换绑到目标页。"
            ),
            "pages": [page.to_dict() for page in exc.pages],
            "page_count": len(exc.pages),
        }
        return self._json_result(payload)

    def _json_result(self, payload: dict[str, Any]) -> ToolResult:
        if self._profile_annotation:
            payload = {**self._profile_annotation, **payload}
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


    def _pages_action(self, session_id: str, request: dict[str, Any]) -> ToolResult:
        """M2-B B9 (DESIGN-20261027 §4.1/B9): healthy-state read-only page listing.

        Rides the SAME /json/list channel the multi-page miss receipt uses
        (EVO-20261007-11ae668f) - no new CDP method, no session, no capture,
        no store write.  target_id (or any extra field) is a deterministic
        fields mismatch: a listing must never trigger the rebind path, and
        rebind stays its own explicit single action.  The receipt echoes the
        current binding and world_version so the caller can verify the
        no-change contract on the receipt itself.
        """
        if set(request) != {"action"}:
            extras = sorted(set(request) - {"action"})
            return self._fail(
                f"[browser_perceive:pages] fields_mismatch: 只读清单不接受字段 {extras}"
                "（换绑 target_id 是独立动作）。"
            )
        if self._page_controller is None:
            return self._fail(
                "[browser_perceive:pages] page controller 未装配；页面清单不可用。"
            )
        try:
            pages = self._page_controller.list_pages()
            binding = self._page_controller.current_binding()
        except Exception as exc:  # noqa: BLE001 - listing failure must stay explicit
            return self._fail(
                "[browser_perceive:pages] 页面清单读取失败："
                f"error_type={type(exc).__name__}; error={exc}"
            )
        bound_id = str((binding or {}).get("target_id") or "") or str(
            getattr(self._backend, "bound_target_id", "") or ""
        )
        payload = {
            "action": "pages",
            "read_only": True,
            "pages": [
                {**page.to_dict(), "bound": page.page_id == bound_id} for page in pages
            ],
            "page_count": len(pages),
            "binding_page_id": bound_id or None,
            "world_version": self._adapter.latest_world_version(session_id),
        }
        return self._json_result(payload)

    def _wait_download_state(
        self, *, expected: str, timeout_ms: int, interval_ms: int
    ) -> ToolResult:
        """M2-A B6 (§5.2/§7.3.5): poll the session download state machine.

        The getter IS the actuator's download_state (event drain + fenced-dir
        facts); this layer only owns cadence and honest timeout receipts.
        Runtime owns polling; no mutation capability leaks into perceive.
        """
        from llm_loop.browser.download_contract import download_wait_verdict

        if self._download_state_getter is None:
            return self._fail(
                "[browser_perceive:wait] download_state 探针未装配"
                "（本会话未启用 browser action / 下载通道）；未开始轮询。"
            )
        size_samples: dict[str, tuple[float, int]] = {}
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            state = self._download_state_getter()
            verdict = (
                download_wait_verdict(state, expected, size_samples=size_samples)
                if isinstance(state, dict)
                else None
            )
            if verdict is not None:
                if verdict.get("result") == "rejected":
                    return self._fail(
                        "[browser_perceive:wait] download_state 拒绝："
                        f"{verdict.get('reason')}（路径未通过会话下载目录 realpath 围栏，"
                        "未报告任何文件事实）。"
                    )
                payload = {
                    "action": "wait",
                    "kind": "download_state",
                    **{k: v for k, v in verdict.items() if k != "status"},
                }
                return self._json_result(payload)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._fail(
                    "[browser_perceive:wait] download_state 超时：期望 "
                    f"{expected} 未在 {timeout_ms}ms 内出现"
                    "（事件态未达终态且文件未满足稳定判据）。"
                )
            time.sleep(min(interval_ms / 1000.0, remaining))

    def _field_mismatch(self, action: str, kwargs: dict[str, Any]) -> ToolResult | None:
        allowed_by_action = {
            "snapshot": {
                "action",
                "projection_limit",
                "projection_kinds",
                "projection_cursor",
                "vision",
                "target_id",
            },
            "hydrate": {"action", "grounding_ref", "target_id"},
            "diff": {"action", "from_version", "to_version", "target_id"},
        }
        if action == "wait":
            # Historical nested condition remains executable for frozen evidence and
            # deterministic compatibility, but it is absent from the provider schema.
            if "condition" in kwargs:
                allowed = {"action", "condition", "within_ms", "target_id"}
            else:
                kind = str(kwargs.get("kind") or "").strip()
                allowed = self._FLAT_WAIT_FIELDS.get(kind)
                if allowed is None:
                    return self._fail(f"[browser_perceive:wait] kind 不受支持: {kind or '<missing>'}。")
        else:
            allowed = allowed_by_action.get(action)
        if allowed is None:
            return None
        extras = sorted(set(kwargs) - allowed)
        if extras:
            return self._fail(
                f"[browser_perceive:{action}] fields_mismatch: action 不接受字段 {extras}。"
            )
        return None

    @staticmethod
    def _accept_legacy_wait_aliases(action: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """历史/内部直调兼容：url→expected_url、object_ref→grounding_ref。

        provider 契约只暴露 expected_url / grounding_ref，导航目标与已观察 URL 不再
        共用同一参数角色；两个别名互斥（kind 不同），按 kind 分派。
        """
        if action != "wait" or "condition" in kwargs:
            return kwargs
        kind = str(kwargs.get("kind") or "").strip()
        if kind == "page_url" and "expected_url" not in kwargs and "url" in kwargs:
            kwargs = dict(kwargs)
            kwargs["expected_url"] = kwargs.pop("url")
        if (
            kind in {"object_state", "object_text"}
            and "grounding_ref" not in kwargs
            and "object_ref" in kwargs
        ):
            kwargs = dict(kwargs)
            kwargs["grounding_ref"] = kwargs.pop("object_ref")
        return kwargs

    def execute(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip()
        kwargs = self._accept_legacy_wait_aliases(action, kwargs)
        session_id = str(self._session_id_getter() or "").strip()
        if not session_id:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[browser_perceive] 当前 session identity 不可用；未执行 Browser observation。",
                tool_call_id="",
                tool_name=self.name,
            )
        # M2-B B9：pages 是只读清单动作，必须在通用 target_id 换绑拦截之前
        # 分发——任何附带的 target_id 都在 _pages_action 内确定性拒绝，
        # 读取路径绝不产生换绑副作用。
        if action == "pages":
            return self._pages_action(session_id, dict(kwargs))
        # EVO-20261007-11ae668f：显式 target_id ⇒ 先换绑（确定性，非静默），再执行观察。
        explicit_target_id = str(kwargs.get("target_id") or "").strip()
        if explicit_target_id:
            if self._page_controller is None:
                return self._fail(
                    "[browser_perceive] target_id 换绑不可用：本会话未装配 page controller。"
                )
            try:
                rebind_receipt = self._page_controller.rebind(explicit_target_id)
            except PageTargetNotFoundError as exc:
                return self._json_result(
                    {
                        "action": "rebind",
                        "status": "failed",
                        "reason": "target_not_found",
                        "target_id": exc.target_id,
                        "pages": [page.to_dict() for page in exc.pages],
                        "hint": "target_id 不在当前页面清单中；请从 pages 里选择确切 page_id 重试。",
                    }
                )
            except Exception as exc:  # noqa: BLE001 - rebind failure must stay explicit.
                return self._fail(
                    f"[browser_perceive] target_id 换绑失败：error_type={type(exc).__name__}; error={exc}"
                )
            else:
                result = self._json_result(
                    {
                        "action": "rebind",
                        "status": "ok",
                        "rebound": rebind_receipt,
                    }
                )
                # 换绑本身是一个已完成的显式动作：本次调用到此为止，观察动作需
                # 在下一次调用发起（单一动作、复验分离，避免换绑+观察耦合）。
                return result
        mismatch = self._field_mismatch(action, dict(kwargs))
        if mismatch is not None:
            return mismatch
        if action == "wait":
            condition = kwargs.get("condition")
            if condition is None:
                condition = {
                    key: value
                    for key, value in kwargs.items()
                    if key not in {"action", "within_ms", "target_id"}
                }
            elif not isinstance(condition, dict):
                return self._fail("[browser_perceive:wait] condition 必须是闭合 object。")
            else:
                condition = dict(condition)
                if (
                    str(condition.get("kind") or "").strip() == "page_url"
                    and "expected_url" not in condition
                    and "url" in condition
                ):
                    # Historical nested-condition compatibility is execution-only; it
                    # is absent from both lazy and full provider schemas.
                    condition["expected_url"] = condition.pop("url")
                if (
                    str(condition.get("kind") or "").strip() in {"object_state", "object_text"}
                    and "grounding_ref" not in condition
                    and "object_ref" in condition
                ):
                    # Historical nested object_ref remains execution-only.  It is
                    # normalized mechanically to the exact GroundingRef field.
                    condition["grounding_ref"] = condition.pop("object_ref")
            try:
                timeout_ms = int(kwargs.get("within_ms", 60_000) or 60_000)
            except (TypeError, ValueError):
                return self._fail("[browser_perceive:wait] within_ms 必须是整数 1..60000。")
            if not 1 <= timeout_ms <= 60_000:
                return self._fail("[browser_perceive:wait] within_ms 必须在 1..60000。")
            interval_ms = min(250, timeout_ms)
            kind = str(condition.get("kind") or "").strip()
            if kind in {"page_ready", "page_url"}:
                if self._backend is None:
                    return self._fail(
                        "[browser_perceive:wait] read-only Browser backend unavailable; no polling started."
                    )
                try:
                    seed = self._adapter.snapshot(
                        session_id, self._backend.capture(), projection_limit=1
                    )
                    page_scope = next(
                        item
                        for item in list(seed.get("scope_facts") or [])
                        if isinstance(item, dict) and item.get("kind") == "page"
                    )
                    scope_ref = str(page_scope.get("scope_ref") or "").strip()
                except MultiPageAmbiguityError as ambiguity:
                    # EVO-20261007-11ae668f：多页且未显式指定 target ⇒ 只读页面清单。
                    return self._page_list_result(ambiguity)
                except Exception as exc:  # noqa: BLE001 - observation failure must stay explicit.
                    return ToolResult(
                        status=ToolResultStatus.ERROR,
                        content=(
                            "[browser_perceive:wait] page binding observation failed; "
                            f"error_type={type(exc).__name__}; error={exc}"
                        ),
                        tool_call_id="",
                        tool_name=self.name,
                        error_type=type(exc).__name__,
                        error_detail=str(exc),
                    )
                if not scope_ref:
                    return self._fail("[browser_perceive:wait] host-bound page scope unavailable.")
                if kind == "page_ready":
                    request = {
                        "scope_ref": scope_ref,
                        "state": condition.get("state"),
                        "timeout_ms": timeout_ms,
                        "interval_ms": interval_ms,
                    }
                    result = self._wait_scope_ready.execute_request(session_id, request)
                else:
                    match_to_operator = {
                        "equals": "eq",
                        "contains": "contains",
                        "starts_with": "prefix",
                        "ends_with": "suffix",
                    }
                    match = str(condition.get("match") or "").strip()
                    operator = match_to_operator.get(match)
                    if operator is None:
                        return self._fail("[browser_perceive:wait] page_url match 不受支持。")
                    request = {
                        "scope_ref": scope_ref,
                        "operator": operator,
                        "value": condition.get("expected_url"),
                        "timeout_ms": timeout_ms,
                        "interval_ms": interval_ms,
                    }
                    result = self._wait_scope_url.execute_request(session_id, request)
            elif kind == "object_state":
                request = {
                    "object_ref": condition.get("grounding_ref"),
                    "property": condition.get("state"),
                    "value": condition.get("value"),
                    "timeout_ms": timeout_ms,
                    "interval_ms": interval_ms,
                }
                result = self._wait_object_state.execute_request(session_id, request)
            elif kind == "object_absent":
                # M2-B B7 (§7.3.4): the negative condition compiles to the
                # canonical exists=false predicate; settle_ms (default 300)
                # rides the waiter's stability window - mid-window
                # re-appearance resets, timeout reports state=present.
                request = {
                    "object_ref": condition.get("grounding_ref"),
                    "property": "exists",
                    "value": False,
                    "settle_ms": condition.get("settle_ms", ABSENT_SETTLE_DEFAULT_MS),
                    "timeout_ms": timeout_ms,
                    "interval_ms": interval_ms,
                }
                result = self._wait_object_state.execute_request(session_id, request)
            elif kind == "object_text":
                match_to_operator = {
                    "equals": "eq",
                    "contains": "contains",
                    "starts_with": "prefix",
                    "ends_with": "suffix",
                }
                match = str(condition.get("match") or "").strip()
                operator = match_to_operator.get(match)
                if operator is None:
                    return self._fail("[browser_perceive:wait] object_text match 不受支持。")
                request = {
                    "object_ref": condition.get("grounding_ref"),
                    "property": condition.get("field"),
                    "operator": operator,
                    "value": condition.get("text"),
                    "timeout_ms": timeout_ms,
                    "interval_ms": interval_ms,
                }
                result = self._wait_object_text.execute_request(session_id, request)
            elif kind == "download_state":
                # M2-A B6: session-scoped download completion wait (§5.2).
                return self._wait_download_state(
                    expected=str(condition.get("expected") or ""),
                    timeout_ms=timeout_ms,
                    interval_ms=interval_ms,
                )
            else:
                return self._fail(
                    "[browser_perceive:wait] condition.kind 必须是 "
                    "page_ready/page_url/object_state/object_text/download_state/object_absent。"
                )
            return ToolResult(
                status=result.status,
                content=result.content,
                tool_call_id="",
                tool_name=self.name,
                error_type=result.error_type,
                error_detail=result.error_detail,
                partial_output=result.partial_output,
            )
        if action == "hydrate":
            ref = str(kwargs.get("grounding_ref") or "").strip()
            if not ref:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[browser_perceive:hydrate] grounding_ref 为空；必须给精确 GroundingRef。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            if ref.startswith("browser-operation-receipt://") and self._exact_ref_hydrator is not None:
                hydrated = self._exact_ref_hydrator(session_id, ref)
            else:
                hydrated = self._adapter.hydrate(session_id, ref)
            return self._json_result({"action": "hydrate", **hydrated})
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
            projection_kinds_raw = kwargs.get("projection_kinds")
            projection_kinds: list[str] | None = None
            if projection_kinds_raw is not None:
                if not isinstance(projection_kinds_raw, list) or not all(
                    isinstance(item, str) and item.strip() for item in projection_kinds_raw
                ):
                    return ToolResult(
                        status=ToolResultStatus.FAILURE,
                        content="[browser_perceive:snapshot] projection_kinds 必须是非空字符串数组。",
                        tool_call_id="",
                        tool_name=self.name,
                    )
                projection_kinds = [str(item).strip() for item in projection_kinds_raw]
            try:
                projection_cursor = int(kwargs.get("projection_cursor", 0) or 0)
            except (TypeError, ValueError):
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[browser_perceive:snapshot] projection_cursor 必须是 >=0 的整数。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            if projection_cursor < 0:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[browser_perceive:snapshot] projection_cursor 必须是 >=0 的整数。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            vision_request = str(kwargs.get("vision") or "").strip() or None
            if vision_request is not None and vision_request != "evidence":
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[browser_perceive:snapshot] vision 只接受 evidence。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            # R5：capture 前的只读 dialog 探测（探针未挂载/异常 ⇒ 原路径不变）。
            if (blocked_state := self._dialog_block_facts()) is not None:
                return self._dialog_blocked_snapshot_result(blocked_state, vision_request)
            try:
                raw = self._backend.capture()
            except MultiPageAmbiguityError as ambiguity:
                # EVO-20261007-11ae668f：多页且未显式指定 target ⇒ 只读页面清单。
                return self._page_list_result(ambiguity)
            try:
                result = self._adapter.snapshot(
                    session_id,
                    raw,
                    projection_limit=projection_limit,
                    projection_kinds=projection_kinds,
                    projection_cursor=projection_cursor,
                )
                if vision_request == "evidence":
                    self._attach_vision_evidence(session_id, result)
                return self._json_result(result)
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
            content="[browser_perceive] action 必须是 snapshot、hydrate、diff、wait 或 pages。",
            tool_call_id="",
            tool_name=self.name,
        )

    def _attach_vision_evidence(self, session_id: str, result: dict[str, Any]) -> None:
        """EVO-20260918-f2310800: evidence-layer vision only.

        The DOM+AX snapshot already succeeded; vision failure is reported in
        the vision block and never masks the main result.
        """
        capture_vision = getattr(self._backend, "capture_vision_evidence", None)
        if not callable(capture_vision):
            result["vision"] = {"status": "unavailable"}
            return
        try:
            payload = capture_vision()
            # M1 B10 (DESIGN-20261027 §4.1): captured_at is stamped right at
            # capture time. fix(gate2, review-M1): host-local wall-clock
            # authority (system_local_now) — aware, offset-bearing, comparable
            # — replaces the former UTC wall clock per the LFL timekeeping
            # contract.
            captured_at = system_local_now().isoformat(timespec="milliseconds")
        except Exception as vision_exc:  # noqa: BLE001 - vision failure must stay visible, non-fatal.
            result["vision"] = {
                "status": "failed",
                "error_type": type(vision_exc).__name__,
                "error": str(vision_exc),
            }
            return
        if not isinstance(payload, bytes):
            # Mechanical payload boundary: the backend declared the capability
            # but did not return raw bytes.
            result["vision"] = {
                "status": "unavailable",
                "reason": "payload_not_bytes",
            }
            return
        result["vision"] = {
            "status": "ok",
            **self._adapter.store_vision_evidence(
                session_id,
                payload,
                **_vision_meta(self._backend, result, captured_at),
            ),
        }


def _vision_meta(backend: Any, result: dict[str, Any], captured_at: str) -> dict[str, Any]:
    """M1 B10 (DESIGN-20261027 §4.1): determinability metadata for the evidence
    receipt. world_version is the snapshot_id of the observation this
    screenshot belongs to; page_id is the backend's bound target (absent on
    backends without a bound page id).
    """
    return {
        "page_id": str(getattr(backend, "bound_target_id", "") or "") or None,
        "world_version": (str((result.get("snapshot") or {}).get("snapshot_id") or "") or None),
        "captured_at": captured_at,
    }
