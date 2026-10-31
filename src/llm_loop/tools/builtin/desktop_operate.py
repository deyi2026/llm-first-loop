"""Model-facing desktop actuation tool — M4 (DESIGN-20261027 §5.4/§6, D5-D9).

Contract (§5.4 args, closed key set):

- ``do`` ∈ {click, type, press_key, scroll}; ``window_id`` required (CGWindowID);
  ``target`` = {ax_ref} | {point:{x,y}} (unit: POINTS; press_key may omit);
  ``text?`` (type only, ≤2000); ``keys?`` (press_key closed named-key set /
  scroll "down|up[:n]"); ``dry_run`` default true; ``confirm_token?`` one-shot
  token issued by the dry-run receipt; ``force?`` needs a one-time credential
  (``force_credential``); as-built extra key over §5.4: force_credential (D7).

Gates, in order: platform/session → window binding → privacy (D8) → act
allowlist (D6: Finder/Safari/Chrome/Preview; terminal/IDE read-only) →
see_allowlist alignment (S10) → target resolution (act-time exact addressing,
T5; Chrome/Safari web content → web_target_not_allowed → browser_operate —
R1 also hit-tests {point} against AXWebArea bounds, and scrolls/press_key in
browser windows pass the same web boundary) → publish/submit/pay targets →
review_required fail-closed (M2: host review_admission gate or refusal, never
this tool's own token) → key/text policy (B3 blacklist, IME-polluted letter
typing is NOT offered) → risk class (§6.2 heuristic; browser point/press_key/
scroll never land in plain "act", M1) → [dry_run: issue one-shot confirm token]
→ [apply: writes_enabled switch (default OFF) → EXEC_MODE blocked/readonly
refusal (M3) → D7 HID idle user-present refusal → §6.2 token/session gate
(point channel NEVER session-exempt, M1) → D4 world re-bind → U18 AX self-probe
→ real delivery (force credential consumed only here, S2) → post fingerprint +
session approval (point channel excluded)].

Receipts (§5.4): risk_class / pre_sha256 / post_sha256 / target_identity /
applied / needs_confirmation / privacy_blocked (+ dry_run, confirm_token,
world_version, hid_idle_ms, foreground_before/after, verified).

Audit (§6.4, append-only JSONL via make_jsonl_audit_sink): one row per
terminal outcome, refusals included. No delete/rewrite surface exists.

Non-darwin → unsupported_platform (same as desktop_perceive).
"""

from __future__ import annotations

import contextlib
import json
import platform as _platform
import secrets as _secrets
import time
from collections.abc import Callable
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.desktop.hid_idle import USER_PRESENT_WINDOW_MS
from llm_loop.desktop.models import (
    AX_NODE_LIMIT_DEFAULT,
    MAX_AX_DEPTH,
    DesktopErrorCode,
    PermissionSnapshot,
    WindowInfo,
    jsonable,
)
from llm_loop.desktop.operate import (
    MAX_TYPE_CHARS,
    RISK_HEURISTIC_DISCLAIMER,
    ActAllowlist,
    ConfirmTokenStore,
    SessionActGate,
    action_fingerprint,
    channel_risk_override,
    classify_risk,
    focused_ax_ref,
    has_web_area,
    hits_review_markers,
    is_browser_bundle,
    is_web_subtree,
    parse_keycombo,
    parse_scroll,
    point_in_web_area,
    web_area_rects,
    window_gone_fingerprint,
    world_fingerprint,
)
from llm_loop.desktop.privacy import PrivacyPolicy, SeeAllowlist
from llm_loop.timekeeping import system_local_now

_DOS = ("click", "type", "press_key", "scroll")
_BASE_FIELDS = {"do", "window_id", "target", "text", "keys", "dry_run", "confirm_token", "force", "force_credential"}

# S3：force 凭据失败节流（进程内）——连续 3 次不匹配锁定 60s
_FORCE_FAIL_LIMIT = 3
_FORCE_LOCK_S = 60.0

GUIDANCE_UNSUPPORTED = "desktop_operate 仅支持 macOS（darwin）；当前平台不可操作桌面。"
GUIDANCE_NO_GUI = "当前进程无图形控制台会话；需在已登录桌面会话内运行。"
GUIDANCE_LOCKED = "屏幕已锁定；锁屏下桌面操作被拒绝（D10）。"
GUIDANCE_AX = (
    "AX（辅助功能）未授权或目标应用不支持 AX：打开 系统设置 → 隐私与安全性 → 辅助功能，"
    "将运行 LFL 的终端/宿主应用加入并开启，然后重试。授权绑定启动进程，重启宿主后需复核。"
)
GUIDANCE_WRITES_DISABLED = (
    "desktop_operate 写能力默认关闭（T8：能力不随代码自动上线）。"
    "需要真实投递时由用户显式设置 LFL_DESKTOP_OPERATE_ENABLED=1 并重启宿主；"
    "dry_run 与只读探测不受该开关限制。"
)
GUIDANCE_FORCE = (
    "force 需要一次性授权凭据（D7）：宿主启动前由用户设置 LFL_DESKTOP_FORCE_CREDENTIAL，"
    "并在 force 调用中携带 force_credential；凭据每会话仅可用一次。"
    "当前宿主没有面向本工具的人工审批/凭据铸造通道，这是已登记的凭据来源缺口。"
)
GUIDANCE_WEB_TARGET = (
    "目标属于浏览器网页内容层（AXWebArea 子树）：按裁决路线 A，网页层操作走既有"
    " browser_operate（DOM+AX sensor 的 CDP 通道）；desktop_operate 只服务原生 app 与"
    " 窗口 chrome 级动作（如关闭/最小化按钮）。"
)
GUIDANCE_TERMINAL_READONLY = (
    "终端/IDE 应用为只读感知面（T3/Q-05：放开 act 等于不受沙箱约束的任意命令执行）；"
    "需要执行命令请用 execute_command。"
)
GUIDANCE_REVIEW_REQUIRED = (
    "发布/提交/支付类目标（§6.2/§6.3 MUST）必须走宿主发表闸（review_admission），"
    "desktop_operate 不自行放行：宿主当前没有面向桌面动作的发表审批通道，"
    "故 fail-closed 拒绝——本工具的一次性 confirm_token 对该类目标一律无效。"
    "如需发布/提交/支付，请由宿主侧行政通道（人工或既有发表闸）执行。"
)
GUIDANCE_EXEC_MODE_BLOCKED = (
    "宿主 EXEC_MODE={mode}：桌面真实投递被拒绝（M3：desktop_operate 尊重宿主命令分级；"
    "与 execute_command/写文件工具同语义，需人工执行）；dry_run 与只读门控不受限。"
)


class DesktopOperateTool:
    name = "desktop_operate"
    description = (
        "桌面窄操作（macOS，M4/D5-D9）。do ∈ {click,type,press_key,scroll}；window_id 必填"
        "（来自 desktop_perceive windows 回执）；target={ax_ref}（snapshot 回执的索引路径）或"
        " {point:{x,y}}（单位=点；press_key 可省略 target=作用于绑定窗口焦点）。"
        "dry_run 默认 true（只回执不投递，并签发一次性 confirm_token）；apply 需 dry_run 后的"
        " confirm_token。同 app 同动作类型在 session 内放行——注意该免令牌放行路径"
        "**不重做 world 比对**（§6.2 字面允许）：窗口内结构漂移可能换靶，故坐标 point 目标"
        "不享受该放行（每次都要令牌+world 比对）。不可逆启发式命中（关闭按钮/删除/发布/"
        "支付/浏览器 Enter 等）永远单步每次都要新 token。发布/提交/支付类目标一律"
        " review_required 拒绝（§6.3：须走宿主发表闸，本工具 token 不放行）。"
        "浏览器窗口内：网页内容区域（AXWebArea）的 point 点击、滚轮与网页焦点按键一律拒绝"
        " web_target_not_allowed → browser_operate（路线 A）；无法证明在网页区外的浏览器"
        " point/press_key/scroll 按不可逆处理（每次都要新令牌）。act 白名单硬编码"
        " Finder/Safari/Chrome/Preview，终端与 IDE 只读拒绝；敏感 app（1Password/Keychain/"
        "loginwindow 等核心名单）拒绝操作；desktop.see_allowlist 非空时名单外 app 同样不可"
        " act（与 perceive 可见范围对齐）。press_key 只接受闭合命名键集"
        "（Enter/Escape/Tab/方向/F1-F12 等，可带 Ctrl/Alt/Shift），"
        "Meta 系与字母键一律拒绝（B3 黑名单族；字母 CGEvent 通道被输入法污染，文本输入走 do=type"
        " 的 AX set-value 并回读校验）。用户在场（HID idle<60s 或探针失败）默认拒绝 mutate"
        "（user_present）；force 必须携带一次性授权凭据（宿主 env 预置），缺失即拒，"
        "凭据失败有进程内节流。写能力总开关默认关（LFL_DESKTOP_OPERATE_ENABLED），关闭时"
        "真实投递一律 writes_disabled；宿主 EXEC_MODE=blocked/readonly 时真实投递同样被拒"
        "（exec_mode_blocked）。dry_run 不受上述两开关限制。"
        "risk_class 由启发式判定，不构成安全保证。"
        "非 macOS 返回 unsupported_platform。审计 append-only JSONL，不提供删除/改写"
        "（审计只记令牌的 sha256 短摘要，不落明文片段）。"
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "do": {
                "type": "string",
                "enum": list(_DOS),
                "description": "click=点击（ax_ref 走 AXPress / point 走 CGEvent）；type=AX set-value 写入并回读校验；press_key=闭合命名键；scroll=滚轮（down/up 可带 :n 行数，默认 3）",
            },
            "window_id": {
                "type": "integer",
                "minimum": 0,
                "description": "必填：目标窗口 CGWindowID（来自 desktop_perceive action=windows）",
            },
            "target": {
                "type": "object",
                "properties": {
                    "ax_ref": {"type": "string", "description": "snapshot 回执的 ax_ref 索引路径（如 0.2.1）"},
                    "point": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number", "description": "全局 X（单位=点）"},
                            "y": {"type": "number", "description": "全局 Y（单位=点）"},
                        },
                        "required": ["x", "y"],
                        "additionalProperties": False,
                    },
                },
                "additionalProperties": False,
                "description": "寻址：ax_ref（exact，act-time 重解析）或 point（点单位；必须落在窗口 bounds 内；浏览器窗口内须落在 AXWebArea 网页区之外，且每次 apply 都要新令牌）。press_key 可省略（作用于绑定窗口当前焦点）；type 只接受 ax_ref",
            },
            "text": {
                "type": "string",
                "description": "type 专用：写入文本（整体替换语义，≤2000 字符；逐字符回读校验）",
            },
            "keys": {
                "type": "string",
                "description": "press_key：闭合命名键（enter/escape/tab/delete/backspace/space/arrows/home/end/pageup/pagedown/f1..f12），可带 ctrl/alt/shift 前缀；scroll：down|up 可带 :n（行数 1..20）",
            },
            "dry_run": {
                "type": "boolean",
                "description": "默认 true：只做门控/寻址/风险分级并签发 confirm_token，不投递",
            },
            "confirm_token": {
                "type": "string",
                "description": "dry_run 回执签发的一次性令牌（绑定 window_id+do+目标+world_version；重放/错绑即拒）",
            },
            "force": {
                "type": "boolean",
                "description": "D7：绕过用户在场检测；必须携带一次性 force_credential，缺失即拒",
            },
            "force_credential": {
                "type": "string",
                "description": "一次性授权凭据（宿主 env LFL_DESKTOP_FORCE_CREDENTIAL 由用户预置；每会话一次）",
            },
        },
        "required": ["do", "window_id"],
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
        act_allowlist_extra: tuple[str, ...] = (),
        see_allowlist: tuple[str, ...] = (),
        writes_enabled: bool = False,
        force_credential: str = "",
        exec_mode: str = "",
        exec_allowlist: tuple[str, ...] = (),
    ) -> None:
        self._backend = backend
        self._session_id_getter = session_id_getter or (lambda: "")
        self._audit = audit_sink
        self._privacy = PrivacyPolicy(privacy_extra)
        self._act_allowlist = ActAllowlist(act_allowlist_extra)
        # S10：perceive 可见范围（desktop.see_allowlist）对 act 生效——perceive 隐藏
        # 的 app 不可 act（默认空 = 不限制，零回归）。
        self._see_allowlist = SeeAllowlist(see_allowlist)
        self._writes_enabled = bool(writes_enabled)
        self._force_secret = str(force_credential or "")
        self._tokens = ConfirmTokenStore()
        self._gate = SessionActGate()
        # M3：尊重宿主 EXEC_MODE（blocked/readonly 拒绝真实投递；空 = 不启用，零回归；
        # allowlist 模式须显式列出 "desktop_operate" 才放行投递）。
        self._exec_mode = str(exec_mode or "").strip().lower()
        self._exec_allowlist = frozenset(
            str(item).strip().lower() for item in exec_allowlist if str(item).strip()
        )
        # S3：force 凭据失败节流（进程内；宿主无桌面动作审批通道时的暴力面收窄）
        self._force_fail_count = 0
        self._force_lock_until = 0.0

    # ── 基础回执 ─────────────────────────────────────────────────────────
    def _fail(
        self,
        message: str,
        *,
        do: str | None = None,
        error_code: DesktopErrorCode | None = None,
    ) -> ToolResult:
        """S6：参数校验失败也走统一 JSON 信封（不再是纯文本）。"""
        started = time.monotonic()
        return self._envelope(
            do=do or "", ok=False, error_code=error_code, guidance=message,
            started=started,
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
        do: str,
        ok: bool,
        error_code: DesktopErrorCode | None,
        guidance: str | None,
        started: float,
        base: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ToolResult:
        receipt: dict[str, Any] = {
            "ok": bool(ok),
            "do": do,
            "error_code": (error_code.value if error_code else None),
            "guidance": guidance or None,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
        if base:
            receipt.update(base)
        if payload:
            receipt.update(payload)
        return self._result(ok, receipt)

    def _audit_event(self, row: dict[str, Any]) -> None:
        """§6.4 append-only 审计行（拒绝/干跑/投递全记；写失败不改回执语义）。"""
        if self._audit is None:
            return
        full = {
            "ts": system_local_now().isoformat(timespec="milliseconds"),
            "session_id": str(self._session_id_getter() or ""),
            "tool": self.name,
            "do": None,
            "app_bundle": None,
            "window_id": None,
            "target_identity": None,
            "risk_class": None,
            "dry_run": None,
            "confirm_token_id": None,
            "applied": False,
            "pre_sha256": None,
            "post_sha256": None,
            "foreground_before": None,
            "foreground_after": None,
            "hid_idle_ms": None,
            "error_code": None,
        }
        full.update({k: v for k, v in row.items() if v is not None or k in ("dry_run", "applied")})
        with contextlib.suppress(Exception):
            self._audit(full)

    # ── 参数校验（闭合键集 + per-do 规则）─────────────────────────────────
    def _validate(
        self, kwargs: dict[str, Any]
    ) -> tuple[str, dict[str, Any], ToolResult | None, DesktopErrorCode | None]:
        do = str(kwargs.get("do") or "").strip()

        def bad(
            message: str, code: DesktopErrorCode = DesktopErrorCode.INVALID_ARGS
        ) -> tuple[str, dict[str, Any], ToolResult, DesktopErrorCode]:
            return do, {}, self._fail(message, do=do, error_code=code), code

        if do not in _DOS:
            return bad(
                f"[desktop_operate] do 不受支持: {do or '<missing>'}（可选: {', '.join(_DOS)}）。"
            )
        extras = sorted(set(kwargs) - _BASE_FIELDS)
        if extras:
            return bad(f"[desktop_operate:{do}] fields_mismatch: 不接受字段 {extras}。")
        window_id_raw = kwargs.get("window_id")
        if (
            isinstance(window_id_raw, bool)
            or not isinstance(window_id_raw, int)
            or window_id_raw < 0
        ):
            return bad(
                "[desktop_operate] window_id 必填且必须是非负整数（来自 desktop_perceive windows 回执）。"
            )
        window_id = int(window_id_raw)
        options: dict[str, Any] = {"window_id": window_id}
        for key in ("confirm_token", "force_credential", "text", "keys"):
            if kwargs.get(key) is not None and not isinstance(kwargs.get(key), str):
                return bad(f"[desktop_operate] {key} 必须是字符串。")
        dry_run = kwargs.get("dry_run", True)
        if not isinstance(dry_run, bool):
            return bad("[desktop_operate] dry_run 必须是布尔值（默认 true）。")
        force = kwargs.get("force", False)
        if not isinstance(force, bool):
            return bad("[desktop_operate] force 必须是布尔值。")
        options["dry_run"] = dry_run
        options["force"] = force
        options["confirm_token"] = str(kwargs.get("confirm_token") or "")
        options["force_credential"] = str(kwargs.get("force_credential") or "")
        # per-do 字段规则（§5.4 键集共享；非法组合在入口即拒）
        text = kwargs.get("text")
        keys = kwargs.get("keys")
        if do == "click" and (text is not None or keys is not None):
            return bad("[desktop_operate:click] fields_mismatch: click 不接受 text/keys。")
        if do == "type":
            if text is None or not str(text):
                return bad("[desktop_operate:type] text 必填。", DesktopErrorCode.TYPE_ARGS_INVALID)
            if keys is not None:
                return bad(
                    "[desktop_operate:type] fields_mismatch: type 不接受 keys。",
                    DesktopErrorCode.TYPE_ARGS_INVALID,
                )
            options["text"] = str(text)
        if do == "press_key":
            if keys is None or not str(keys).strip():
                return bad("[desktop_operate:press_key] keys 必填。")
            if text is not None:
                return bad("[desktop_operate:press_key] fields_mismatch: 不接受 text。")
        if do == "scroll":
            if keys is None or not str(keys).strip():
                return bad("[desktop_operate:scroll] keys 必填（down|up[:n]）。")
            if text is not None:
                return bad("[desktop_operate:scroll] fields_mismatch: 不接受 text。")
        if keys is not None:
            options["keys"] = str(keys)
        target = kwargs.get("target")
        if target is not None:
            if not isinstance(target, dict):
                return bad("[desktop_operate] target 必须是对象。")
            target_fields = set(target)
            if target_fields == {"ax_ref"}:
                if not isinstance(target["ax_ref"], str) or not target["ax_ref"].strip():
                    return bad("[desktop_operate] target.ax_ref 必须是非空字符串。")
            elif target_fields == {"point"}:
                point = target["point"]
                if not isinstance(point, dict) or set(point) != {"x", "y"}:
                    return bad("[desktop_operate] target.point 形如 {x,y}。")
                for axis in ("x", "y"):
                    if isinstance(point[axis], bool) or not isinstance(point[axis], (int, float)):
                        return bad(f"[desktop_operate] target.point.{axis} 必须是数字（单位=点）。")
                # S1（R1）：type 的 AX set-value 通道只接受 ax_ref 寻址；point 会在投递层
                # KeyError→backend_error，提前在校验层用 §5.5 预留码拒绝。
                if do == "type":
                    return bad(
                        "[desktop_operate:type] fields_mismatch: type 只接受 target={ax_ref}"
                        "（AX set-value 通道；point 坐标不可用于键入）。",
                        DesktopErrorCode.TYPE_ARGS_INVALID,
                    )
            else:
                return bad(
                    "[desktop_operate] target 必须是 {ax_ref} 或 {point:{x,y}} 之一（键互斥）。"
                )
            options["target"] = target
        elif do in ("click", "type", "scroll"):
            return bad(f"[desktop_operate:{do}] target 必填。")
        return do, options, None, None

    # ── 主分发 ───────────────────────────────────────────────────────────
    def execute(self, **kwargs: Any) -> ToolResult:
        started = time.monotonic()
        do, options, invalid, invalid_code = self._validate(dict(kwargs))
        if invalid is not None:
            # S5：参数校验失败也是终态拒绝，补审计行（window_id 尽力取整）
            raw_wid = kwargs.get("window_id")
            wid = int(raw_wid) if isinstance(raw_wid, int) and not isinstance(raw_wid, bool) else None
            self._audit_event({
                "do": do or None,
                "window_id": wid,
                "dry_run": bool(kwargs.get("dry_run", True)),
                "error_code": (invalid_code or DesktopErrorCode.INVALID_ARGS).value,
            })
            return invalid
        backend = self._backend
        wid_early = {"do": do, "window_id": int(options["window_id"]),
                     "dry_run": bool(options.get("dry_run"))}
        if backend is None or not bool(getattr(backend, "supported", False)):
            self._audit_event({**wid_early, "error_code": DesktopErrorCode.UNSUPPORTED_PLATFORM.value})
            return self._envelope(
                do=do, ok=False,
                error_code=DesktopErrorCode.UNSUPPORTED_PLATFORM,
                guidance=GUIDANCE_UNSUPPORTED, started=started,
            )
        try:
            platform_dict = jsonable(backend.platform_info())
            session = backend.session_snapshot()
            perms: PermissionSnapshot = backend.permission_snapshot()
        except Exception:  # noqa: BLE001 - 后端异常确定性回执，不带栈
            self._audit_event({**wid_early, "error_code": DesktopErrorCode.BACKEND_ERROR.value})
            return self._envelope(
                do=do, ok=False, error_code=DesktopErrorCode.BACKEND_ERROR,
                guidance="桌面后端初始化失败（确定性回执，不含栈）。", started=started,
            )
        session_dict = jsonable(session)
        base: dict[str, Any] = {
            "permissions": {
                "ax_trusted": bool(perms.ax_trusted),
                "screen_capture_granted": bool(perms.screen_capture_granted),
            },
            "platform": platform_dict or {"os": _platform.system().lower(), "version": ""},
            "session": session_dict or {"gui_available": False, "console_user": None, "screen_locked": None},
            "privacy_blocked": False,
        }
        if not session.gui_available:
            self._audit_event({**wid_early, "error_code": DesktopErrorCode.NO_GUI_SESSION.value})
            return self._envelope(
                do=do, ok=False, error_code=DesktopErrorCode.NO_GUI_SESSION,
                guidance=GUIDANCE_NO_GUI, started=started, base=base,
            )
        if session.screen_locked:
            self._audit_event({**wid_early, "error_code": DesktopErrorCode.SCREEN_LOCKED.value})
            return self._envelope(
                do=do, ok=False, error_code=DesktopErrorCode.SCREEN_LOCKED,
                guidance=GUIDANCE_LOCKED, started=started, base=base,
            )
        try:
            return self._dispatch(do, options, backend, base, started)
        except Exception:  # noqa: BLE001 - 分发兜底：确定性回执，无栈
            self._audit_event({**wid_early, "error_code": DesktopErrorCode.BACKEND_ERROR.value})
            return self._envelope(
                do=do, ok=False, error_code=DesktopErrorCode.BACKEND_ERROR,
                guidance="desktop_operate 执行失败（确定性回执，不含栈）；可先用 desktop_perceive status 自检。",
                started=started, base=base,
            )

    # ── 门控与投递 ───────────────────────────────────────────────────────
    def _dispatch(
        self,
        do: str,
        options: dict[str, Any],
        backend: Any,
        base: dict[str, Any],
        started: float,
    ) -> ToolResult:
        if do == "type" and len(str(options.get("text") or "")) > MAX_TYPE_CHARS:
            self._audit_event({"do": do, "window_id": options["window_id"],
                               "dry_run": bool(options.get("dry_run")),
                               "error_code": DesktopErrorCode.TYPE_TEXT_TOO_LONG.value})
            return self._envelope(
                do=do, ok=False, error_code=DesktopErrorCode.TYPE_TEXT_TOO_LONG,
                guidance=f"type 文本超过 {MAX_TYPE_CHARS} 字符上限（§5.5）；请分段输入。",
                started=started, base=base,
                payload={"applied": False, "needs_confirmation": False},
            )
        window = backend.get_window(int(options["window_id"]))
        if window is None:
            # S5：早期拒绝也写审计行（one row per terminal outcome, refusals included）
            self._audit_event({
                "do": do, "window_id": int(options["window_id"]),
                "dry_run": bool(options.get("dry_run")),
                "error_code": DesktopErrorCode.WINDOW_NOT_FOUND.value,
            })
            return self._envelope(
                do=do, ok=False, error_code=DesktopErrorCode.WINDOW_NOT_FOUND,
                guidance="window_id 不在当前窗口清单中；先 desktop_perceive action=windows 重新绑定。",
                started=started, base=base,
            )
        bundle = window.bundle_id
        audit: dict[str, Any] = {
            "do": do,
            "app_bundle": bundle,
            "window_id": window.window_id,
            "dry_run": bool(options.get("dry_run")),
        }

        def refuse(error: DesktopErrorCode, guidance: str, **extra: Any) -> ToolResult:
            audit.update({"error_code": error.value, **{k: v for k, v in extra.items()}})
            self._audit_event(audit)
            payload: dict[str, Any] = {"applied": False, "needs_confirmation": False}
            if error == DesktopErrorCode.PRIVACY_BLOCKED:
                payload["privacy_blocked"] = True
            return self._envelope(
                do=do, ok=False, error_code=error, guidance=guidance,
                started=started, base=base, payload=payload,
            )

        # D8：核心隐私名单（优先级最高；不投递、不读树）
        if self._privacy.is_sensitive(bundle):
            return refuse(
                DesktopErrorCode.PRIVACY_BLOCKED,
                f"目标应用属于隐私核心名单（bundle_id={bundle}）；按 D8 拒绝操作，无降级路径。",
            )
        # D6/T3：act 白名单（终端/IDE 只读）
        actable, deny_kind = self._act_allowlist.is_actable(bundle)
        if not actable:
            if deny_kind == "terminal_readonly":
                return refuse(
                    DesktopErrorCode.APP_NOT_ALLOWED,
                    f"终端/IDE 应用为只读面（bundle_id={bundle}）。{GUIDANCE_TERMINAL_READONLY}",
                )
            return refuse(
                DesktopErrorCode.APP_NOT_ALLOWED,
                f"目标应用不在 act 白名单（bundle_id={bundle}；核心名单硬编码"
                " Finder/Safari/Chrome/Preview，配置只能追加，终端/IDE 永不放开）。",
            )
        # S10：see_allowlist（perceive 可见范围）对 act 对齐——perceive 隐藏的 app 不可 act。
        # 默认空 = 全部允许（零回归）；与 M3/U14 同为 app_not_allowed（可见性是配置层语义）。
        if not self._see_allowlist.is_allowed(bundle):
            return refuse(
                DesktopErrorCode.APP_NOT_ALLOWED,
                f"目标应用不在 desktop.see_allowlist 可见范围（bundle_id={bundle}，U14 对齐）："
                "perceive 隐藏的 app 不可 act；如需操作请先把该 app 加入"
                " LFL_DESKTOP_SEE_ALLOWLIST。",
            )

        # ── 目标解析（只读；act-time exact addressing 的第一半）───────────
        windows = backend.list_windows()
        frontmost_before = next((w.bundle_id for w in windows if w.is_foreground), None)
        # S9：快照节点上限与 desktop_perceive 对齐（AX_NODE_LIMIT_DEFAULT=1500），
        # 否则 perceive 回执里的深位 ax_ref 在本工具侧解析不到 → window_unbound。
        ax_view = backend.ax_snapshot(window, MAX_AX_DEPTH, AX_NODE_LIMIT_DEFAULT)
        nodes = ax_view.nodes if ax_view.available else ()
        browser = is_browser_bundle(bundle)
        target = options.get("target")
        target_identity: dict[str, Any]
        if isinstance(target, dict) and "ax_ref" in target:
            ax_ref = str(target["ax_ref"]).strip()
            if not ax_view.available:
                return refuse(
                    DesktopErrorCode.AX_UNAVAILABLE,
                    f"AX 树不可用（{ax_view.failure}），无法解析 ax_ref。{GUIDANCE_AX}",
                )
            node_map = {n.ax_ref: n for n in nodes}
            node = node_map.get(ax_ref)
            if node is None:
                return refuse(
                    DesktopErrorCode.WINDOW_UNBOUND,
                    f"ax_ref={ax_ref} 不在当前窗口 AX 树中（目标已变化）；重新 snapshot 后再试。",
                )
            audit["target_identity"] = target_identity = {
                "kind": "ax_ref",
                "ax_ref": ax_ref,
                "role": node.role,
                "subrole": node.subrole,
                "title": node.title,
            }
            # 路线 A 边界：目标自身或任何祖先命中 AXWebArea → 网页内容层
            if is_web_subtree(ax_ref, nodes):
                return refuse(
                    DesktopErrorCode.WEB_TARGET_NOT_ALLOWED, GUIDANCE_WEB_TARGET,
                )
            if (node.role or "").lower() == "axsecuretextfield" or (
                node.subrole or ""
            ).lower() == "axsecuretextfield":
                return refuse(
                    DesktopErrorCode.PRIVACY_BLOCKED,
                    "目标是密码型输入框（AXSecureTextField）；按 N4 红线拒绝键入，无降级路径。",
                )
        elif isinstance(target, dict) and "point" in target:
            point = target["point"]
            px, py = float(point["x"]), float(point["y"])
            bounds = window.bounds_pt
            within = (
                bounds.x <= px < bounds.x + bounds.w and bounds.y <= py < bounds.y + bounds.h
            )
            if not within:
                return refuse(
                    DesktopErrorCode.COORDINATE_OUT_OF_BOUNDS,
                    f"point({px:.1f},{py:.1f}) 不在窗口 bounds 内"
                    f"（{bounds.x:.1f},{bounds.y:.1f},{bounds.w:.1f}x{bounds.h:.1f}，单位=点；§7.3.2）。",
                )
            audit["target_identity"] = target_identity = {
                "kind": "point", "x": px, "y": py, "within_window_id": window.window_id
            }
            # M1：point 必须对当前窗口 AX 快照的 AXWebArea 做命中判定（不许绕过路线 A）。
            # 快照不可用、或存在 AXWebArea 但 bounds 不可读，都无法排除网页内容 →
            # 一律 fail-closed 拒绝（坐标点击是精确命中通道，不能证明不在网页区就不投）。
            point_hits_web = browser and (
                not ax_view.available
                or has_web_area(nodes)
                and (not web_area_rects(nodes) or point_in_web_area(px, py, nodes))
            )
            if point_hits_web:
                why = (
                    "AX 快照不可用，无法排除网页内容"
                    if not ax_view.available
                    else "AXWebArea bounds 命中，或存在 AXWebArea 但 bounds 不可读、无法排除"
                )
                return refuse(
                    DesktopErrorCode.WEB_TARGET_NOT_ALLOWED,
                    f"point({px:.1f},{py:.1f}) 落在浏览器窗口网页内容区域（{why}）。"
                    f"{GUIDANCE_WEB_TARGET}",
                )
        else:
            audit["target_identity"] = target_identity = {
                "kind": "focused", "window_id": window.window_id
            }

        # M2：发布/提交/支付类目标 fail-closed 拒绝（宿主发表闸缺失 ⇒ 不自行放行）。
        # ax_ref 通道用目标自身标题；point/focused/scroll 无法证明目标身份，退而用
        # 窗口标题（宁可误拒：该类目标是 §6.2/§6.3 的显式 MUST）。
        _review_texts: tuple[str | None, ...]
        if target_identity["kind"] == "ax_ref":
            _review_texts = (target_identity.get("title"), target_identity.get("subrole"))
        else:
            _review_texts = (window.title,)
        if hits_review_markers(*_review_texts):
            return refuse(
                DesktopErrorCode.REVIEW_REQUIRED, GUIDANCE_REVIEW_REQUIRED,
                risk_class="irreversible",
            )

        # M1：浏览器窗口内 scroll（滚轮投递到 app 进程，默认作用于网页视口）与
        # press_key（作用于窗口焦点，网页焦点通常 AX 不可见）同样要过 web 边界。
        if browser and do == "scroll" and has_web_area(nodes):
            return refuse(
                DesktopErrorCode.WEB_TARGET_NOT_ALLOWED,
                "浏览器窗口存在 AXWebArea：滚轮事件投递到 app 进程将作用于网页视口。"
                f"{GUIDANCE_WEB_TARGET}",
            )
        if browser and do == "press_key":
            focused_ref = focused_ax_ref(nodes)
            if focused_ref is not None and is_web_subtree(focused_ref, nodes):
                return refuse(
                    DesktopErrorCode.WEB_TARGET_NOT_ALLOWED,
                    f"窗口焦点（ax_ref={focused_ref}）位于浏览器网页内容层。{GUIDANCE_WEB_TARGET}",
                )

        # ── per-do 参数策略（B3 黑名单 / IME 缺口 / scroll 规格）──────────
        keys = str(options.get("keys") or "")
        if do == "press_key":
            status, detail, flags = parse_keycombo(keys)
            if status != "ok":
                return refuse(DesktopErrorCode.KEY_NOT_ALLOWED, detail)
            options["key_flags"] = flags
        if do == "scroll":
            status, detail, signed = parse_scroll(keys)
            if status != "ok":
                return refuse(DesktopErrorCode.KEY_NOT_ALLOWED, detail)
            options["scroll_signed_lines"] = signed

        risk_class = classify_risk(
            do,
            bundle_id=bundle,
            role=target_identity.get("role"),
            subrole=target_identity.get("subrole"),
            title=target_identity.get("title"),
            keys=keys,
        )
        # M1：浏览器窗口内 point/press_key/scroll 通道不得落在普通 act（按不可逆处理）
        risk_class = channel_risk_override(
            risk_class, browser=browser, do=do, target_kind=target_identity["kind"]
        )
        audit["target_identity"] = target_identity
        audit["risk_class"] = risk_class

        # S9：ax_ref 通道的目标节点无条件进 world 指纹（深位目标漂移必须打破令牌）
        dry_target_node = next(
            (n for n in nodes if n.ax_ref == target_identity.get("ax_ref")), None
        ) if target_identity["kind"] == "ax_ref" else None
        world = world_fingerprint(window, nodes, frontmost_before, target_node=dry_target_node)
        audit["pre_sha256"] = world
        audit["foreground_before"] = frontmost_before
        # M1：point 通道永不进会话放行（坐标点击每次都要令牌 + world 比对）
        channel_token_required = target_identity["kind"] == "point"
        # 令牌绑定的 action_id 用**稳定寻址**（do/window/ax_ref|point/text|keys）：
        # role/title 属展示属性（会合法变化，如文档标题自更新），其漂移由
        # world_version 相等性捕捉（foreground_changed 语义），不该把令牌烧成 mismatch。
        binding_address: dict[str, Any]
        if target_identity["kind"] == "ax_ref":
            binding_address = {"kind": "ax_ref", "ax_ref": target_identity["ax_ref"]}
        elif target_identity["kind"] == "point":
            binding_address = {"kind": "point", "x": target_identity["x"], "y": target_identity["y"]}
        else:
            binding_address = {"kind": "focused"}
        action_fp = action_fingerprint(
            do, window.window_id, binding_address, options.get("text"), keys
        )
        risk_note = RISK_HEURISTIC_DISCLAIMER if risk_class == "irreversible" else None

        # ── dry_run：不投递，签发一次性令牌（§5.4/§6.3）──────────────────
        if bool(options.get("dry_run")):
            token = self._tokens.issue(
                window_id=window.window_id,
                do=do,
                action_fp=action_fp,
                world_version=world,
                risk_class=risk_class,
                now=time.time(),
            )
            audit.update(
                {"applied": False, "confirm_token_id": self._tokens.token_id(token)}
            )
            self._audit_event(audit)
            dry_payload: dict[str, Any] = {
                "applied": False,
                "dry_run": True,
                "needs_confirmation": True,
                "confirm_token": token,
                "risk_class": risk_class,
                "target_identity": target_identity,
                "pre_sha256": world,
                "post_sha256": None,
                "world_version": world,
                "foreground_before": frontmost_before,
            }
            if risk_note:
                dry_payload["risk_note"] = risk_note
            return self._envelope(
                do=do, ok=True, error_code=None, guidance=None, started=started,
                base=base, payload=dry_payload,
            )

        # ── apply：真实投递路径（以下每一关失败都拒绝且不投递）────────────
        audit["dry_run"] = False
        idle_ms = backend.hid_idle_ms()
        audit["hid_idle_ms"] = idle_ms
        user_present = idle_ms is None or int(idle_ms) < USER_PRESENT_WINDOW_MS
        force_used = False
        if user_present:
            if not bool(options.get("force")):
                audit["error_code"] = DesktopErrorCode.USER_PRESENT.value
                self._audit_event(audit)
                return self._envelope(
                    do=do, ok=False, error_code=DesktopErrorCode.USER_PRESENT,
                    guidance=(
                        f"用户在场（HID idle={idle_ms if idle_ms is not None else '探针不可用，按在场处理'}ms"
                        f" < {USER_PRESENT_WINDOW_MS}ms，D7）：默认拒绝 mutate；"
                        f"可稍后重试或携带一次性 force 凭据。{GUIDANCE_FORCE}"
                    ),
                    started=started, base=base,
                    payload={"applied": False, "needs_confirmation": False,
                             "hid_idle_ms": idle_ms},
                )
            force_used = True
            credential = str(options.get("force_credential") or "")
            if not self._force_secret:
                audit["error_code"] = DesktopErrorCode.FORCE_CREDENTIAL_MISSING.value
                self._audit_event(audit)
                return self._envelope(
                    do=do, ok=False, error_code=DesktopErrorCode.FORCE_CREDENTIAL_MISSING,
                    guidance=f"force=true 但宿主未配置一次性凭据来源（LFL_DESKTOP_FORCE_CREDENTIAL 为空）。{GUIDANCE_FORCE}",
                    started=started, base=base,
                    payload={"applied": False, "needs_confirmation": False, "hid_idle_ms": idle_ms},
                )
            if self._gate.force_consumed(self._session_id_getter()):
                audit["error_code"] = DesktopErrorCode.FORCE_CREDENTIAL_INVALID.value
                self._audit_event(audit)
                return self._envelope(
                    do=do, ok=False, error_code=DesktopErrorCode.FORCE_CREDENTIAL_INVALID,
                    guidance="本会话的一次性 force 凭据已被消耗；需用户重新预置新凭据。",
                    started=started, base=base,
                    payload={"applied": False, "needs_confirmation": False, "hid_idle_ms": idle_ms},
                )
            # S3：失败节流——锁定窗内直接拒绝（不比较、不消耗），防进程内暴力试凭据
            now_mono = time.monotonic()
            if self._force_fail_count >= _FORCE_FAIL_LIMIT and now_mono < self._force_lock_until:
                audit["error_code"] = DesktopErrorCode.FORCE_CREDENTIAL_INVALID.value
                self._audit_event(audit)
                return self._envelope(
                    do=do, ok=False, error_code=DesktopErrorCode.FORCE_CREDENTIAL_INVALID,
                    guidance=(
                        f"force 凭据连续失败 {self._force_fail_count} 次，已临时锁定"
                        f"（{_FORCE_LOCK_S:.0f}s 内拒绝所有 force 尝试，S3 节流）；稍后重试。"
                    ),
                    started=started, base=base,
                    payload={"applied": False, "needs_confirmation": False, "hid_idle_ms": idle_ms},
                )
            # S3：恒时比较（secrets.compare_digest），不泄露比较进度
            if not (
                isinstance(credential, str)
                and isinstance(self._force_secret, str)
                and _secrets.compare_digest(credential, self._force_secret)
            ):
                self._force_fail_count += 1
                if self._force_fail_count >= _FORCE_FAIL_LIMIT:
                    self._force_lock_until = now_mono + _FORCE_LOCK_S
                audit["error_code"] = DesktopErrorCode.FORCE_CREDENTIAL_INVALID.value
                self._audit_event(audit)
                return self._envelope(
                    do=do, ok=False, error_code=DesktopErrorCode.FORCE_CREDENTIAL_INVALID,
                    guidance=(
                        "force_credential 与宿主预置凭据不匹配（D7）。"
                        + (f"连续失败 {self._force_fail_count} 次，已进入 {_FORCE_LOCK_S:.0f}s 锁定。"
                           if self._force_fail_count >= _FORCE_FAIL_LIMIT else "")
                    ),
                    started=started, base=base,
                    payload={"applied": False, "needs_confirmation": False, "hid_idle_ms": idle_ms},
                )
            # S2：凭据**校验通过 ≠ 消耗**——消耗推迟到即将投递（所有可拒绝关卡之后），
            # 写开关关闭/令牌不符/世界漂移等拒绝路径不得烧掉用户预置的一次性凭据。
            self._force_fail_count = 0

        # 写能力总开关（T8：默认关；先于令牌校验，避免烧毁令牌）
        if not self._writes_enabled:
            audit["error_code"] = DesktopErrorCode.WRITES_DISABLED.value
            self._audit_event(audit)
            return self._envelope(
                do=do, ok=False, error_code=DesktopErrorCode.WRITES_DISABLED,
                guidance=GUIDANCE_WRITES_DISABLED, started=started, base=base,
                payload={"applied": False, "needs_confirmation": False, "hid_idle_ms": idle_ms},
            )

        # M3：宿主 EXEC_MODE 分级（blocked/readonly 拒绝真实投递；allowlist 需显式列出
        # 本工具；空 = 不启用，默认零回归）。dry_run 不走 apply 路径，天然不受限。
        exec_mode_blocks = bool(self._exec_mode) and (
            self._exec_mode in ("blocked", "readonly")
            or (self._exec_mode == "allowlist" and self.name not in self._exec_allowlist)
        )
        if exec_mode_blocks:
            audit["error_code"] = DesktopErrorCode.EXEC_MODE_BLOCKED.value
            self._audit_event(audit)
            return self._envelope(
                do=do, ok=False, error_code=DesktopErrorCode.EXEC_MODE_BLOCKED,
                guidance=GUIDANCE_EXEC_MODE_BLOCKED.format(mode=self._exec_mode),
                started=started, base=base,
                payload={"applied": False, "needs_confirmation": False, "hid_idle_ms": idle_ms},
            )

        # §6.2 会话门 + T6 令牌（M1：point 通道永不享受会话免令牌放行）
        session_id = self._session_id_getter()
        approved = self._gate.is_approved(session_id, bundle, do)
        token_str = str(options.get("confirm_token") or "")
        if (channel_token_required or risk_class == "irreversible" or not approved) and not token_str:
            audit["error_code"] = DesktopErrorCode.DRY_RUN_REQUIRED.value
            self._audit_event(audit)
            return self._envelope(
                do=do, ok=False, error_code=DesktopErrorCode.DRY_RUN_REQUIRED,
                guidance=(
                    "该 (app, do) 组合在本会话尚未确认"
                    + ("，且 irreversible 类永远需要逐步 confirm_token" if risk_class == "irreversible" else "")
                    + ("；坐标 point 目标不享受会话内放行，每次 apply 都需要新的"
                       " confirm_token + world 比对（M1）" if channel_token_required else "")
                    + "；先以 dry_run=true 获取一次性 confirm_token 再 apply。"
                ),
                started=started, base=base,
                payload={"applied": False, "needs_confirmation": True,
                         "risk_class": risk_class, "hid_idle_ms": idle_ms},
            )
        token_record = None
        if token_str:
            audit["confirm_token_id"] = self._tokens.token_id(token_str)
            status, token_record = self._tokens.redeem(
                token_str,
                window_id=window.window_id,
                do=do,
                action_fp=action_fp,
            )
            token_error = {
                "invalid": DesktopErrorCode.CONFIRM_TOKEN_INVALID,
                "replayed": DesktopErrorCode.CONFIRM_TOKEN_REPLAYED,
                "mismatch": DesktopErrorCode.CONFIRM_TOKEN_MISMATCH,
            }.get(status)
            if token_error is not None:
                audit["error_code"] = token_error.value
                self._audit_event(audit)
                guidance_map = {
                    DesktopErrorCode.CONFIRM_TOKEN_INVALID: "confirm_token 未知或不可解析（T6）。",
                    DesktopErrorCode.CONFIRM_TOKEN_REPLAYED: "confirm_token 已使用过（U17/T6：一次性，重放拒绝且已记审计）。",
                    DesktopErrorCode.CONFIRM_TOKEN_MISMATCH: "confirm_token 绑定不符（window_id/do/目标与签发时不一致，U16）；令牌已作废，需重新 dry_run。",
                }
                return self._envelope(
                    do=do, ok=False, error_code=token_error,
                    guidance=guidance_map[token_error], started=started, base=base,
                    payload={"applied": False, "needs_confirmation": True,
                             "risk_class": risk_class, "hid_idle_ms": idle_ms},
                )

        # D4：apply 时世界重绑（窗口仍存在且仍前台；token 路径还要求 world 未漂移）
        fresh_window = backend.get_window(int(options["window_id"]))
        if fresh_window is None or not fresh_window.is_foreground:
            audit["error_code"] = DesktopErrorCode.FOREGROUND_CHANGED.value
            self._audit_event(audit)
            return self._envelope(
                do=do, ok=False, error_code=DesktopErrorCode.FOREGROUND_CHANGED,
                guidance=(
                    "绑定窗口已消失或不再是前台（D4/U16/U20）；令牌已作废，"
                    "重新 windows+snapshot 绑定后再 dry_run。"
                ),
                started=started, base=base,
                payload={"applied": False, "needs_confirmation": True,
                         "risk_class": risk_class, "hid_idle_ms": idle_ms,
                         "window": jsonable(fresh_window) if fresh_window else None,
                         "foreground_before": frontmost_before},
            )
        fresh_view = backend.ax_snapshot(fresh_window, MAX_AX_DEPTH, AX_NODE_LIMIT_DEFAULT)
        fresh_nodes = fresh_view.nodes if fresh_view.available else ()
        fresh_frontmost = next(
            (w.bundle_id for w in backend.list_windows() if w.is_foreground), None
        )
        fresh_target_node = next(
            (n for n in fresh_nodes if n.ax_ref == target_identity.get("ax_ref")), None
        ) if target_identity["kind"] == "ax_ref" else None
        fresh_world = world_fingerprint(
            fresh_window, fresh_nodes, fresh_frontmost, target_node=fresh_target_node
        )
        if token_record is not None and fresh_world != token_record.world_version:
            audit["error_code"] = DesktopErrorCode.FOREGROUND_CHANGED.value
            self._audit_event(audit)
            return self._envelope(
                do=do, ok=False, error_code=DesktopErrorCode.FOREGROUND_CHANGED,
                guidance=(
                    "dry_run 与 apply 之间世界已变化（窗口/目标子树/前台归属，U16）；"
                    "令牌已作废，需重新 dry_run。"
                ),
                started=started, base=base,
                payload={"applied": False, "needs_confirmation": True,
                         "risk_class": risk_class, "hid_idle_ms": idle_ms,
                         "world_version_expected": token_record.world_version,
                         "world_version_actual": fresh_world,
                         "window": jsonable(fresh_window)},
            )

        # U18 同构自检：投递前 AX 探针（授权位有假阴性，探针才作数）
        probe = backend.ax_probe(fresh_window.pid)
        if probe is None or int(probe) != 0:
            audit["error_code"] = DesktopErrorCode.AX_UNAVAILABLE.value
            self._audit_event(audit)
            return self._envelope(
                do=do, ok=False, error_code=DesktopErrorCode.AX_UNAVAILABLE,
                guidance=f"AX 探针失败（err={probe}），拒绝投递。{GUIDANCE_AX}",
                started=started, base=base,
                payload={"applied": False, "needs_confirmation": False,
                         "risk_class": risk_class, "hid_idle_ms": idle_ms},
            )

        # ── 真实投递 ──────────────────────────────────────────────────────
        # S2：一次性 force 凭据在此刻才消耗——此前所有关卡（写开关/EXEC_MODE/令牌/
        # 世界重绑/AX 探针）都可能拒绝，拒绝路径不得烧掉用户预置的凭据。
        if force_used:
            self._gate.mark_force_consumed(session_id)
        outcome = self._deliver(do, options, backend, fresh_window)
        if not outcome.ok:
            audit.update(
                {"error_code": (outcome.error or DesktopErrorCode.BACKEND_ERROR).value,
                 "applied": False}
            )
            self._audit_event(audit)
            return self._envelope(
                do=do, ok=False,
                error_code=(outcome.error or DesktopErrorCode.BACKEND_ERROR),
                guidance=outcome.detail, started=started, base=base,
                payload={"applied": False, "needs_confirmation": False,
                         "risk_class": risk_class, "hid_idle_ms": idle_ms},
            )

        post_window = backend.get_window(int(options["window_id"]))
        if post_window is None:
            post_sha = window_gone_fingerprint(window.window_id)
            post_nodes: tuple = ()
            post_target_node = None
        else:
            post_view = backend.ax_snapshot(post_window, MAX_AX_DEPTH, AX_NODE_LIMIT_DEFAULT)
            post_nodes = post_view.nodes if post_view.available else ()
            post_target_node = next(
                (n for n in post_nodes if n.ax_ref == target_identity.get("ax_ref")), None
            ) if target_identity["kind"] == "ax_ref" else None
            post_sha = world_fingerprint(
                post_window, post_nodes, frontmost_before, include_value=True,
                target_node=post_target_node,
            )
        foreground_after = next(
            (w.bundle_id for w in backend.list_windows() if w.is_foreground), None
        )
        # M1：point 通道与 irreversible 永不进会话放行（免令牌路径不得弱化）
        if risk_class == "act" and not channel_token_required:
            self._gate.mark_approved(session_id, bundle, do)
        audit.update(
            {"applied": True, "post_sha256": post_sha, "foreground_after": foreground_after,
             "error_code": None}
        )
        self._audit_event(audit)
        payload: dict[str, Any] = {
            "applied": True,
            "dry_run": False,
            "needs_confirmation": False,
            "risk_class": risk_class,
            "target_identity": target_identity,
            "pre_sha256": world,
            "post_sha256": post_sha,
            "world_version": fresh_world,
            "hid_idle_ms": idle_ms,
            "foreground_before": frontmost_before,
            "foreground_after": foreground_after,
            "force_used": force_used,
        }
        if outcome.verified is not None:
            payload["verified"] = outcome.verified
        if risk_note:
            payload["risk_note"] = risk_note
        return self._envelope(
            do=do, ok=True, error_code=None, guidance=None, started=started,
            base=base, payload=payload,
        )

    @staticmethod
    def _deliver(do: str, options: dict[str, Any], backend: Any, window: WindowInfo):
        target = options.get("target")
        if not isinstance(target, dict):  # pragma: no cover - 入口已校验（press_key 无 target 除外）
            if do == "press_key":
                target = {}
            else:
                from llm_loop.desktop.models import ActOutcome

                return ActOutcome(
                    ok=False, error=DesktopErrorCode.BACKEND_ERROR, detail="target 缺失（入口校验被绕过）"
                )
        if do == "click":
            if "ax_ref" in target:
                return backend.act_press(window, str(target["ax_ref"]))
            point = target["point"]
            return backend.act_click_point(float(point["x"]), float(point["y"]))
        if do == "type":
            return backend.act_set_value(window, str(target["ax_ref"]), str(options["text"]))
        if do == "press_key":
            status, canonical, flags = parse_keycombo(str(options.get("keys") or ""))
            if status != "ok":  # pragma: no cover - 入口已校验
                from llm_loop.desktop.models import ActOutcome

                return ActOutcome(ok=False, error=DesktopErrorCode.KEY_NOT_ALLOWED, detail=canonical)
            from llm_loop.desktop.operate import KEY_KEYCODES

            return backend.act_key(KEY_KEYCODES[canonical.rsplit("+", 1)[-1]], flags)
        if do == "scroll":
            return backend.act_scroll(window, int(options["scroll_signed_lines"]))
        from llm_loop.desktop.models import ActOutcome

        return ActOutcome(ok=False, error=DesktopErrorCode.BACKEND_ERROR, detail=f"未知动作: {do}")
