"""Model-facing read-only desktop perception tool — M3 (DESIGN-20261027 §5.3).

Contract highlights (delegated M3 spec + U13/U14/U18/U19):

- Four single-dispatch read-only actions: status / apps / windows / snapshot.
  No hydrate/wait/operate; no AXPress, no typing, no clicking (M4).
- Every call returns the same envelope keys: ok / action / error_code /
  guidance / permissions / platform / session / elapsed_ms.  Deterministic
  receipts only — no exceptions, no stack traces.
- Graded honesty: a missing layer is reported where it is missing (degraded),
  never as a whole-call failure; but a privacy hit (D8) or allowlist miss
  (U14) refuses the snapshot outright with zero capture and zero AX reads.
- vision=evidence is per-call explicit (default none); screen capture is
  prefetched with CGPreflightScreenCaptureAccess and, when ungranted, the
  tool refuses BEFORE any screencapture run (no black images, U18).
"""

from __future__ import annotations

import contextlib
import json
import platform as _platform
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.desktop.models import (
    AX_NODE_LIMIT_DEFAULT,
    DEFAULT_AX_DEPTH,
    DesktopErrorCode,
    PermissionSnapshot,
    ax_error_reason,
    clamp_depth,
    jsonable,
)
from llm_loop.desktop.privacy import PrivacyPolicy, SeeAllowlist
from llm_loop.timekeeping import system_local_now

_ACTIONS = ("status", "apps", "windows", "snapshot")
_ALLOWED_FIELDS: dict[str, set[str]] = {
    "status": {"action"},
    "apps": {"action"},
    "windows": {"action", "include_offscreen"},
    "snapshot": {"action", "window_id", "depth", "vision"},
}

GUIDANCE_AX = (
    "AX（辅助功能）未授权：打开 系统设置 → 隐私与安全性 → 辅助功能，"
    "将运行 LFL 的终端/宿主应用加入并开启，然后重试 status 自检。"
    "授权绑定启动进程，重启宿主后需复核。"
)
GUIDANCE_CAPTURE = (
    "屏幕录制未授权：打开 系统设置 → 隐私与安全性 → 屏幕录制，"
    "将运行 LFL 的终端/宿主应用加入并开启。未授权时 screencapture 会静默产出"
    "黑图/壁纸，本工具已拒绝调用它；授权后重试。"
)
GUIDANCE_UNSUPPORTED = "desktop_perceive 仅支持 macOS（darwin）；当前平台不支持，工具保持只读不可用。"
GUIDANCE_NO_GUI = "当前进程无图形控制台会话（SSH/无登录用户）；需在已登录桌面会话内运行。"
GUIDANCE_LOCKED = "屏幕已锁定；解锁后重试（锁屏下感知被拒绝）。"
GUIDANCE_NOT_FOUND = "window_id 不在当前窗口清单中；先调用 windows 获取有效 CGWindowID 再 snapshot。"


def _guidance_for_error(code: DesktopErrorCode) -> str:
    return {
        DesktopErrorCode.UNSUPPORTED_PLATFORM: GUIDANCE_UNSUPPORTED,
        DesktopErrorCode.NO_GUI_SESSION: GUIDANCE_NO_GUI,
        DesktopErrorCode.SCREEN_LOCKED: GUIDANCE_LOCKED,
        DesktopErrorCode.AX_UNAVAILABLE: GUIDANCE_AX,
        DesktopErrorCode.CAPTURE_UNAVAILABLE: GUIDANCE_CAPTURE,
        DesktopErrorCode.WINDOW_NOT_FOUND: GUIDANCE_NOT_FOUND,
    }.get(code, "")


def make_jsonl_audit_sink(path: Path | str) -> Callable[[dict[str, Any]], None]:
    """§6.4 append-only JSONL 审计：vision=evidence 与 privacy_blocked 事件各一行。

    无删除/改写接口；文件以追加模式打开（宿主进程写入，模型侧只读）。
    """
    target = Path(path)

    def sink(row: dict[str, Any]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    return sink


class DesktopPerceiveTool:
    name = "desktop_perceive"
    description = (
        "桌面只读感知（macOS，M3/D2 分级）。status=TCC 权限/显示器/进程能力自检："
        "ax_trusted/screen_capture_granted 如实回 false 并给可执行修复指引，绝不产黑图；"
        "apps=lsappinfo 应用清单（bundle_id/pid/是否前台/是否隐藏/allowed，无需授权）；"
        "windows=CGWindowList 窗口清单（bounds_pt 单位为点；无屏幕录制授权时窗口标题为空 → "
        "title_available=false，不用应用名冒充标题）；snapshot=按 CGWindowID 取窗口元数据+AX 树"
        "（depth 默认 3 上限 6、节点上限 1500、ax_ref 为 app 根索引路径；AX 缺失记 degraded 不整单失败）"
        "+可选 vision=evidence 窗口截图（默认 none 零落盘，逐次显式；截图前先 CGPreflight，"
        "无授权确定性 capture_unavailable 且不调用 screencapture；像素/点双单位并校验 "
        "|px-pt*scale|≤2，超差记 capture_size_mismatch）。敏感应用（1Password/Bitwarden/Keychain/"
        "登录窗口等硬编码核心名单）windows 隐去标题、snapshot 直接 privacy_blocked（零截图零 AX，"
        "连窗口元数据也不给）；desktop.see_allowlist 非空时名单外 app 的 snapshot 拒绝 app_not_allowed。"
        "非 macOS 返回 unsupported_platform；本工具不导航、不键入、不点击（操作属 M4）。"
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "apps", "windows", "snapshot"],
                "description": "status=权限/能力自检；apps=应用清单；windows=窗口清单；snapshot=单窗口 L0+AX+可选截图",
            },
            "window_id": {
                "type": "integer",
                "minimum": 0,
                "description": "snapshot 必填：目标窗口 CGWindowID（来自 windows 回执的 window_id）",
            },
            "depth": {
                "type": "integer",
                "minimum": 0,
                "maximum": 6,
                "description": "snapshot：AX 遍历深度，默认 3；0..6 之外会被裁剪并回执 clipped_depth=true",
            },
            "vision": {
                "type": "string",
                "enum": ["none", "evidence"],
                "description": (
                    "snapshot：默认 none（零截图、零落盘、零子进程）。evidence=逐次显式请求窗口级截图"
                    "（PNG 落盘 workspace 缓存目录，回执 image{ref,path,sha256,像素宽高,scale,bounds_pt}）"
                ),
            },
            "include_offscreen": {
                "type": "boolean",
                "description": "windows：默认 false 只列在屏窗口；true 时包含离屏窗口",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }
    lazy_parameters = parameters

    def __init__(
        self,
        *,
        backend: Any | None = None,
        session_id_getter: Callable[[], str] | None = None,
        audit_sink: Callable[[dict[str, Any]], None] | None = None,
        privacy_extra: tuple[str, ...] = (),
        see_allowlist: tuple[str, ...] = (),
    ) -> None:
        self._backend = backend
        self._session_id_getter = session_id_getter or (lambda: "")
        self._audit = audit_sink
        self._privacy = PrivacyPolicy(privacy_extra)
        self._allowlist = SeeAllowlist(see_allowlist)

    # ── 基础回执 ─────────────────────────────────────────────────────────
    def _fail(self, message: str) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=message,
            tool_call_id="",
            tool_name=self.name,
        )

    def _result(self, ok: bool, payload: dict[str, Any]) -> ToolResult:
        return ToolResult(
            status=(ToolResultStatus.SUCCESS if ok else ToolResultStatus.FAILURE),
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1),
            tool_call_id="",
            tool_name=self.name,
        )

    def _envelope(
        self,
        *,
        action: str,
        ok: bool,
        error_code: DesktopErrorCode | None,
        guidance: str | None,
        started: float,
        permissions: dict[str, Any] | None = None,
        platform_info: dict[str, Any] | None = None,
        session: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ToolResult:
        receipt: dict[str, Any] = {
            "ok": bool(ok),
            "action": action,
            "error_code": (error_code.value if error_code else None),
            "guidance": guidance or None,
            "permissions": permissions or {"ax_trusted": False, "screen_capture_granted": False},
            "platform": platform_info or {"os": _platform.system().lower(), "version": ""},
            "session": session
            or {"gui_available": False, "console_user": None, "screen_locked": None},
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
        if payload:
            receipt.update(payload)
        return self._result(ok, receipt)

    def _audit_event(
        self,
        *,
        window_id: int | None,
        app_bundle: str | None,
        error_code: str | None,
        sha256: str | None,
    ) -> None:
        if self._audit is None:
            return
        row = {
            "ts": system_local_now().isoformat(timespec="milliseconds"),
            "session_id": str(self._session_id_getter() or ""),
            "tool": self.name,
            "window_id": window_id,
            "app_bundle": app_bundle,
            "risk_class": "see",
            "error_code": error_code,
            "sha256": sha256,
        }
        with contextlib.suppress(Exception):  # 审计写失败不得改变工具回执语义
            self._audit(row)

    # ── 参数校验 ─────────────────────────────────────────────────────────
    def _validate(self, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any], ToolResult | None]:
        action = str(kwargs.get("action") or "").strip()
        if action not in _ACTIONS:
            return action, {}, self._fail(
                f"[desktop_perceive] action 不受支持: {action or '<missing>'}"
                f"（可选: {', '.join(_ACTIONS)}）。"
            )
        allowed = _ALLOWED_FIELDS[action]
        extras = sorted(set(kwargs) - allowed)
        if extras:
            return action, {}, self._fail(
                f"[desktop_perceive:{action}] fields_mismatch: action 不接受字段 {extras}。"
            )
        options: dict[str, Any] = {}
        if action == "snapshot":
            window_id = kwargs.get("window_id")
            if isinstance(window_id, bool) or not isinstance(window_id, int) or window_id < 0:
                return action, {}, self._fail(
                    "[desktop_perceive:snapshot] window_id 必填且必须是非负整数"
                    "（来自 windows 回执的 CGWindowID）。"
                )
            options["window_id"] = int(window_id)
            depth_raw = kwargs.get("depth", DEFAULT_AX_DEPTH)
            if isinstance(depth_raw, bool) or not isinstance(depth_raw, int):
                return action, {}, self._fail("[desktop_perceive:snapshot] depth 必须是整数（0..6）。")
            options["depth_raw"] = int(depth_raw)
            vision = str(kwargs.get("vision") or "none").strip()
            if vision not in ("none", "evidence"):
                return action, {}, self._fail(
                    "[desktop_perceive:snapshot] vision 只接受 none | evidence（默认 none）。"
                )
            options["vision"] = vision
        if action == "windows":
            include_offscreen = kwargs.get("include_offscreen", False)
            if not isinstance(include_offscreen, bool):
                return action, {}, self._fail(
                    "[desktop_perceive:windows] include_offscreen 必须是布尔值。"
                )
            options["include_offscreen"] = include_offscreen
        return action, options, None

    # ── 预检与分发 ───────────────────────────────────────────────────────
    def execute(self, **kwargs: Any) -> ToolResult:
        started = time.monotonic()
        action, options, invalid = self._validate(dict(kwargs))
        if invalid is not None:
            return invalid
        backend = self._backend
        if backend is None or not bool(getattr(backend, "supported", False)):
            return self._envelope(
                action=action,
                ok=False,
                error_code=DesktopErrorCode.UNSUPPORTED_PLATFORM,
                guidance=GUIDANCE_UNSUPPORTED,
                started=started,
            )
        try:
            platform_info = backend.platform_info()
            session = backend.session_snapshot()
        except Exception:  # noqa: BLE001 - 后端异常确定性回执，不带栈
            return self._envelope(
                action=action,
                ok=False,
                error_code=DesktopErrorCode.BACKEND_ERROR,
                guidance="桌面后端初始化失败（平台/会话探测异常）；本回执不含栈，请重试或检查运行环境。",
                started=started,
            )
        platform_dict = jsonable(platform_info)
        session_dict = jsonable(session)
        if not session.gui_available:
            return self._envelope(
                action=action,
                ok=False,
                error_code=DesktopErrorCode.NO_GUI_SESSION,
                guidance=GUIDANCE_NO_GUI,
                started=started,
                platform_info=platform_dict,
                session=session_dict,
            )
        if session.screen_locked:
            return self._envelope(
                action=action,
                ok=False,
                error_code=DesktopErrorCode.SCREEN_LOCKED,
                guidance=GUIDANCE_LOCKED,
                started=started,
                platform_info=platform_dict,
                session=session_dict,
            )
        try:
            perms = backend.permission_snapshot()
        except Exception:  # noqa: BLE001 - 权限探测失败按未授权口径报告
            perms = PermissionSnapshot(ax_trusted=False, screen_capture_granted=False, ax_error=None)
        context = {
            "backend": backend,
            "perms": perms,
            "platform": platform_dict,
            "session": session_dict,
        }
        try:
            if action == "status":
                return self._status_action(started, **context)
            if action == "apps":
                return self._apps_action(started, **context)
            if action == "windows":
                return self._windows_action(started, include_offscreen=options["include_offscreen"], **context)
            return self._snapshot_action(started, options=options, **context)
        except Exception:  # noqa: BLE001 - 分发层兜底：确定性 backend_error，无栈
            return self._envelope(
                action=action,
                ok=False,
                error_code=DesktopErrorCode.BACKEND_ERROR,
                guidance="桌面后端执行失败（确定性回执，不含栈）；可重试 status 自检定位缺失层。",
                started=started,
                permissions=self._perms_dict(perms),
                platform_info=platform_dict,
                session=session_dict,
            )

    @staticmethod
    def _perms_dict(perms: PermissionSnapshot, include_error: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "ax_trusted": bool(perms.ax_trusted),
            "screen_capture_granted": bool(perms.screen_capture_granted),
        }
        if include_error:
            data["ax_error"] = perms.ax_error
        return data

    # ── status ──────────────────────────────────────────────────────────
    def _status_action(self, started: float, *, backend: Any, perms: PermissionSnapshot,
                       platform: dict, session: dict) -> ToolResult:
        try:
            displays = [jsonable(item) for item in backend.list_displays()]
            process = backend.process_info()
            capability = backend.capability_snapshot()
        except Exception:  # noqa: BLE001
            return self._envelope(
                action="status", ok=False, error_code=DesktopErrorCode.BACKEND_ERROR,
                guidance="status 自检后端调用失败（确定性回执，不含栈）。",
                started=started, permissions=self._perms_dict(perms, include_error=True),
                platform_info=platform, session=session,
            )
        guidance_parts = []
        if not bool(capability.get("can_read_ax")):
            guidance_parts.append(GUIDANCE_AX)
        if not perms.screen_capture_granted:
            guidance_parts.append(GUIDANCE_CAPTURE)
        return self._envelope(
            action="status",
            ok=True,
            error_code=None,
            guidance=(" ".join(guidance_parts) if guidance_parts else None),
            started=started,
            permissions=self._perms_dict(perms, include_error=True),
            platform_info=platform,
            session=session,
            payload={
                "displays": displays,
                "process": process,
                "capability": capability,
            },
        )

    # ── apps ────────────────────────────────────────────────────────────
    def _apps_action(self, started: float, *, backend: Any, perms: PermissionSnapshot,
                     platform: dict, session: dict) -> ToolResult:
        apps = [
            {**jsonable(app), "allowed": self._allowlist.is_allowed(app.bundle_id)}
            for app in backend.list_apps()
        ]
        return self._envelope(
            action="apps",
            ok=True,
            error_code=None,
            guidance=None,
            started=started,
            permissions=self._perms_dict(perms),
            platform_info=platform,
            session=session,
            payload={"apps": apps},
        )

    # ── windows ─────────────────────────────────────────────────────────
    def _redact_window(self, window: Any) -> dict[str, Any]:
        data = jsonable(window)
        if self._privacy.is_sensitive(window.bundle_id) or not self._allowlist.is_allowed(
            window.bundle_id
        ):
            # D8/U14：命中核心隐私名单或 see 名单外 → 标题置空并显式标注，绝不过滤行
            data["title"] = None
            data["title_redacted"] = True
        return data

    def _windows_action(self, started: float, *, include_offscreen: bool, backend: Any,
                        perms: PermissionSnapshot, platform: dict, session: dict) -> ToolResult:
        windows = [
            self._redact_window(window)
            for window in backend.list_windows(include_offscreen=include_offscreen)
        ]
        return self._envelope(
            action="windows",
            ok=True,
            error_code=None,
            guidance=None,
            started=started,
            permissions=self._perms_dict(perms),
            platform_info=platform,
            session=session,
            payload={"windows": windows},
        )

    # ── snapshot ────────────────────────────────────────────────────────
    def _snapshot_action(self, started: float, *, options: dict[str, Any], backend: Any,
                         perms: PermissionSnapshot, platform: dict, session: dict) -> ToolResult:
        window = backend.get_window(int(options["window_id"]))
        if window is None:
            return self._envelope(
                action="snapshot", ok=False,
                error_code=DesktopErrorCode.WINDOW_NOT_FOUND, guidance=GUIDANCE_NOT_FOUND,
                started=started, permissions=self._perms_dict(perms),
                platform_info=platform, session=session,
            )
        bundle = window.bundle_id
        # 优先级：privacy_blocked（核心敏感名单）> app_not_allowed（配置名单）
        if self._privacy.is_sensitive(bundle):
            self._audit_event(
                window_id=window.window_id, app_bundle=bundle,
                error_code=DesktopErrorCode.PRIVACY_BLOCKED.value, sha256=None,
            )
            return self._envelope(
                action="snapshot", ok=False,
                error_code=DesktopErrorCode.PRIVACY_BLOCKED,
                guidance=(
                    f"目标窗口属于隐私核心名单（bundle_id={bundle}）；按 D8 拒绝感知，"
                    "不提供窗口元数据、不读 AX、不截图，无降级路径。"
                ),
                started=started, permissions=self._perms_dict(perms),
                platform_info=platform, session=session,
            )
        if not self._allowlist.is_allowed(bundle):
            # U14：零截图、零 AX；保留 L0 元数据（标题隐去）供可观测性
            redacted = self._redact_window(window)
            return self._envelope(
                action="snapshot", ok=False,
                error_code=DesktopErrorCode.APP_NOT_ALLOWED,
                guidance=(
                    f"目标应用不在 desktop.see_allowlist（bundle_id={bundle}，U14）；"
                    "需要感知时由用户在配置中追加该 bundle_id。"
                ),
                started=started, permissions=self._perms_dict(perms),
                platform_info=platform, session=session,
                payload={"window": redacted},
            )
        depth, clipped = clamp_depth(options.get("depth_raw", DEFAULT_AX_DEPTH))
        vision = str(options.get("vision") or "none")
        ax_view = backend.ax_snapshot(window, depth, AX_NODE_LIMIT_DEFAULT)
        degraded: list[str] = []
        ax_payload: dict[str, Any] = {
            "available": bool(ax_view.available),
            "root_role": ax_view.root_role,
            "node_count": len(ax_view.nodes),
            "truncated": bool(ax_view.truncated),
            "clipped_depth": bool(clipped),
            "nodes": [jsonable(node) for node in ax_view.nodes],
        }
        error_code: DesktopErrorCode | None = None
        guidance: str | None = None
        if not ax_view.available:
            failure = str(ax_view.failure or "ax_unavailable")
            degraded.append(failure)
            if failure == "window_ambiguous":
                error_code = DesktopErrorCode.WINDOW_AMBIGUOUS
                guidance = (
                    "AX 侧存在多个 (标题相等且 bounds 差≤2pt) 的候选窗口，绑定歧义；"
                    "请换用无歧义的 window_id 或稍后重试。回执附候选清单。"
                )
                ax_payload["candidates"] = [jsonable(c) for c in ax_view.candidates]
            else:
                guidance = self._ax_failure_guidance(ax_view)
        image_payload: dict[str, Any] | None = None
        if vision == "evidence":
            outcome = backend.capture_window(window)
            if outcome.error is not None:
                error_code = outcome.error
                guidance = " ".join(
                    part
                    for part in (
                        outcome.detail,
                        GUIDANCE_CAPTURE
                        if outcome.error == DesktopErrorCode.CAPTURE_UNAVAILABLE
                        else "",
                    )
                    if part
                )
                self._audit_event(
                    window_id=window.window_id,
                    app_bundle=bundle,
                    error_code=outcome.error.value,
                    sha256=None,
                )
            else:
                degraded.extend(outcome.degraded)
                image_payload = jsonable(outcome.image)
                self._audit_event(
                    window_id=window.window_id,
                    app_bundle=bundle,
                    error_code=None,
                    sha256=outcome.image.sha256 if outcome.image else None,
                )
        ok = error_code is None
        return self._envelope(
            action="snapshot",
            ok=ok,
            error_code=error_code,
            guidance=(guidance or None),
            started=started,
            permissions=self._perms_dict(perms),
            platform_info=platform,
            session=session,
            payload={
                "window": jsonable(window),
                "ax": ax_payload,
                "image": image_payload,
                "degraded": degraded,
            },
        )

    @staticmethod
    def _ax_failure_guidance(ax_view: Any) -> str:
        """AX 缺层的指引：-25211 给修复指引；其余给确定性原因；未绑定给不猜声明。"""
        if ax_view.ax_error is not None:
            reason = ax_error_reason(ax_view.ax_error)
            if ax_view.ax_error == -25211:
                return f"{reason}。{GUIDANCE_AX}"
            return reason
        return "AX 绑定未命中（title 相等且 bounds 差≤2pt 无唯一窗口）；不猜测、不退回前台窗口。"


