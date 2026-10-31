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
→ [apply: D7 HID idle user-present refusal FIRST (user present by default;
force needs the one-time credential — validated here, consumed only at
delivery, S2) → writes_enabled switch (default OFF, T8) → EXEC_MODE
blocked/readonly refusal (M3) → §6.2 token/session gate (point channel NEVER
session-exempt, M1; tokens carry a 10-min TTL and expired redemption is
refused, P2-3) → D4 world re-bind (R5: the target window's app must BE the
frontmost app — lsappinfo caliber; frontmost probe failure fails closed;
CGWindowList order is NOT app focus) + focus drift breaks the world
fingerprint, P2-1) → U18 AX self-probe → real delivery (force credential
consumed only here, S2) → post fingerprint + session approval (point channel
excluded)].
Order note (P2-4/R2): D7 precedes the writes switch / EXEC_MODE — the human
presence gate is the outermost human-safety refusal; when the writes switch is
off the user_present guidance says so explicitly (a force credential alone
cannot reach delivery while writes are disabled).

Receipts (§5.4): risk_class / pre_sha256 / post_sha256 / target_identity /
applied / needs_confirmation / privacy_blocked (+ dry_run, confirm_token,
world_version, hid_idle_ms, foreground_before/after, verified).
foreground_before/after = frontmost APP bundle id (lsappinfo caliber, R5) —
not the CG-order foreground window.

Audit (§6.4, append-only JSONL via make_jsonl_audit_sink): one row per
terminal outcome, refusals included. No delete/rewrite surface exists.

Non-darwin → unsupported_platform (same as desktop_perceive).
"""

from __future__ import annotations

import json
import platform as _platform
import secrets as _secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
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
    CONFIRM_TOKEN_TTL_S,
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


@dataclass
class _ActFlow:
    """_dispatch 流水状态（R4 纯重构引入）：只承载原 _dispatch 的局部变量流转，
    无任何逻辑/副作用；各关卡函数经它读写同一批值，语句与顺序保持拆分前原样。
    """

    do: str
    options: dict[str, Any]
    backend: Any
    base: dict[str, Any]
    started: float
    window: Any = None
    audit: dict[str, Any] = field(default_factory=dict)
    frontmost_before: Any = None
    ax_view: Any = None
    nodes: Any = ()
    browser: bool = False
    target_identity: dict[str, Any] = field(default_factory=dict)
    keys: str = ""
    risk_class: str = ""
    world: str = ""
    channel_token_required: bool = False
    action_fp: str = ""
    risk_note: str | None = None
    idle_ms: Any = None
    force_used: bool = False
    session_id: str = ""
    token_record: Any = None
    fresh_window: Any = None
    fresh_world: str = ""


class DesktopOperateTool:
    name = "desktop_operate"
    description = (
        "桌面窄操作（macOS，M4/D5-D9）。do ∈ {click,type,press_key,scroll}；window_id 必填"
        "（来自 desktop_perceive windows 回执）；target={ax_ref}（snapshot 回执的索引路径）或"
        " {point:{x,y}}（单位=点；press_key 可省略 target=作用于绑定窗口焦点）。"
        "dry_run 默认 true（只回执不投递，并签发一次性 confirm_token）；apply 需 dry_run 后的"
        " confirm_token（令牌 10 分钟内有效，过期按 confirm_token_expired 拒绝）。"
        "同 app 同动作类型在 session 内放行——注意该免令牌放行路径"
        "**不重做 world 比对**（§6.2 字面允许）：窗口内结构漂移可能换靶，故坐标 point 目标"
        "不享受该放行（每次都要令牌+world 比对）。不可逆启发式命中（关闭按钮/删除/发布/"
        "支付/浏览器 Enter 等）永远单步每次都要新 token。发布/提交/支付类目标一律"
        " review_required 拒绝（§6.3：须走宿主发表闸，本工具 token 不放行）。"
        "浏览器窗口内：网页内容区域（AXWebArea）的 point 点击、滚轮与网页焦点按键一律拒绝"
        " web_target_not_allowed → browser_operate（路线 A）；无法证明在网页区外的浏览器"
        " point/press_key/scroll 按不可逆处理（每次都要新令牌）。apply 前台判据=前台 app"
        "（lsappinfo 口径，R5）：目标窗口所属 bundle_id 必须等于当前前台 app 的"
        " bundle_id，取不到前台信息一律 foreground_changed 拒绝（fail-closed）；"
        "回执/审计的 foreground_before/after 即前台 app 的 bundle_id"
        "（非 CG 窗口序口径）。act 白名单硬编码"
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
        # P2-7（R2）：审计写入失败计数（best-effort 语义不变，但不再完全静默——
        # 计数附进回执 audit_write_failed；无持久性信号仍登记 residual）
        self._audit_failures = 0

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
        if self._audit_failures:
            # P2-7（R2）：审计 best-effort——失败不改工具语义，但把进程内累计
            # 计数附进回执（不再完全静默；无持久性信号仍登记 residual）。
            receipt["audit_write_failed"] = self._audit_failures
        if base:
            receipt.update(base)
        if payload:
            receipt.update(payload)
        return self._result(ok, receipt)

    def _audit_event(self, row: dict[str, Any]) -> None:
        """§6.4 append-only 审计行（拒绝/干跑/投递全记；写失败不改回执语义）。

        P2-7（R2）：审计写入仍是 best-effort（异常不影响工具结果），但失败
        计数进 ``self._audit_failures`` 并经 ``_envelope`` 附进回执
        （``audit_write_failed``）——不再完全静默。无持久性失败信号
        （进程内计数随重启丢失）登记为 residual。
        """
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
        try:
            self._audit(full)
        except Exception:  # noqa: BLE001 - 审计 best-effort：失败计数，不影响工具语义
            self._audit_failures += 1

    def _refuse(
        self, flow: _ActFlow, error: DesktopErrorCode, guidance: str, **extra: Any
    ) -> ToolResult:
        """门控拒绝统一出口（原 _dispatch 内 refuse 闭包，R4 拆出；语义逐字不变：
        先落审计行再回拒绝回执；PRIVACY_BLOCKED 附 privacy_blocked=true）。"""
        flow.audit.update(
            {"error_code": error.value, **{k: v for k, v in extra.items()}}
        )
        self._audit_event(flow.audit)
        payload: dict[str, Any] = {"applied": False, "needs_confirmation": False}
        if error == DesktopErrorCode.PRIVACY_BLOCKED:
            payload["privacy_blocked"] = True
        return self._envelope(
            do=flow.do, ok=False, error_code=error, guidance=guidance,
            started=flow.started, base=flow.base, payload=payload,
        )

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

    # ── 门控与投递（R4：_dispatch 为短调度器，关卡拆至独立函数，顺序不变）──
    def _dispatch(
        self,
        do: str,
        options: dict[str, Any],
        backend: Any,
        base: dict[str, Any],
        started: float,
    ) -> ToolResult:
        """短调度器：解析入参 → 逐关分派 → 组装回执。

        R4 纯重构：原 576 行单体按关注点拆为下列关卡函数，语句、门控顺序、
        错误码/文案与审计时机逐字保持；共享状态经 _ActFlow 流转（无逻辑）。
        """
        flow = _ActFlow(
            do=do, options=options, backend=backend, base=base, started=started
        )
        refused = self._bind_window(flow)
        if refused is not None:
            return refused
        refused = self._gate_app_allowance(flow)
        if refused is not None:
            return refused
        self._scan_window_world(flow)
        refused = self._resolve_target(flow)
        if refused is not None:
            return refused
        refused = self._gate_review_web(flow)
        if refused is not None:
            return refused
        refused = self._gate_key_policy(flow)
        if refused is not None:
            return refused
        self._plan_risk_and_binding(flow)
        if bool(options.get("dry_run")):
            return self._dry_run_receipt(flow)
        return self._apply(flow)

    def _bind_window(self, flow: _ActFlow) -> ToolResult | None:
        """type 长度上限与窗口绑定（S5：早期拒绝也写审计行；成功则建 audit 行底）。"""
        do, options, backend = flow.do, flow.options, flow.backend
        base, started = flow.base, flow.started
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
        flow.window = window
        flow.audit = audit
        return None

    def _gate_app_allowance(self, flow: _ActFlow) -> ToolResult | None:
        """app 级三闸：D8 隐私核心名单 → D6/T3 act 白名单 → S10 see_allowlist 对齐。"""
        bundle = flow.window.bundle_id
        # D8：核心隐私名单（优先级最高；不投递、不读树）
        if self._privacy.is_sensitive(bundle):
            return self._refuse(
                flow,
                DesktopErrorCode.PRIVACY_BLOCKED,
                f"目标应用属于隐私核心名单（bundle_id={bundle}）；按 D8 拒绝操作，无降级路径。",
            )
        # D6/T3：act 白名单（终端/IDE 只读）
        actable, deny_kind = self._act_allowlist.is_actable(bundle)
        if not actable:
            if deny_kind == "terminal_readonly":
                return self._refuse(
                    flow,
                    DesktopErrorCode.APP_NOT_ALLOWED,
                    f"终端/IDE 应用为只读面（bundle_id={bundle}）。{GUIDANCE_TERMINAL_READONLY}",
                )
            return self._refuse(
                flow,
                DesktopErrorCode.APP_NOT_ALLOWED,
                f"目标应用不在 act 白名单（bundle_id={bundle}；核心名单硬编码"
                " Finder/Safari/Chrome/Preview，配置只能追加，终端/IDE 永不放开）。",
            )
        # S10：see_allowlist（perceive 可见范围）对 act 对齐——perceive 隐藏的 app 不可 act。
        # 默认空 = 全部允许（零回归）；与 M3/U14 同为 app_not_allowed（可见性是配置层语义）。
        if not self._see_allowlist.is_allowed(bundle):
            return self._refuse(
                flow,
                DesktopErrorCode.APP_NOT_ALLOWED,
                f"目标应用不在 desktop.see_allowlist 可见范围（bundle_id={bundle}，U14 对齐）："
                "perceive 隐藏的 app 不可 act；如需操作请先把该 app 加入"
                " LFL_DESKTOP_SEE_ALLOWLIST。",
            )
        return None

    def _scan_window_world(self, flow: _ActFlow) -> None:
        """只读世界扫描：前台 app（R5：lsappinfo 口径）、AX 快照、浏览器判定。

        R5 口径变化：frontmost_before 不再取 CG 窗口序的 is_foreground 窗口
        （CG 序 ≠ app 焦点，真机实测 Chrome 可排在 Preview 前），改取后台
        frontmost_app_bundle()（lsappinfo front+list 按 ASN 归一匹配）。探测
        失败 → None（dry_run 不门控前台；apply 侧 fail-closed，见
        _gate_world_rebind）。本函数因此不再扫全窗口清单（旧实现仅为取前台）。
        """
        backend, window = flow.backend, flow.window
        frontmost_before = backend.frontmost_app_bundle()
        # S9：快照节点上限与 desktop_perceive 对齐（AX_NODE_LIMIT_DEFAULT=1500），
        # 否则 perceive 回执里的深位 ax_ref 在本工具侧解析不到 → ax_ref_not_found
        # （R3：与窗口解绑 window_unbound 分口径，便于定位「节点不在」vs「窗口不在」）。
        ax_view = backend.ax_snapshot(window, MAX_AX_DEPTH, AX_NODE_LIMIT_DEFAULT)
        nodes = ax_view.nodes if ax_view.available else ()
        browser = is_browser_bundle(window.bundle_id)
        flow.frontmost_before = frontmost_before
        flow.ax_view = ax_view
        flow.nodes = nodes
        flow.browser = browser
    def _resolve_target(self, flow: _ActFlow) -> ToolResult | None:
        """目标解析与路由边界（act-time exact addressing 的第一半；只读）。"""
        target = flow.options.get("target")
        if isinstance(target, dict) and "ax_ref" in target:
            return self._resolve_ax_ref_target(flow, target)
        if isinstance(target, dict) and "point" in target:
            return self._resolve_point_target(flow, target)
        flow.audit["target_identity"] = flow.target_identity = {
            "kind": "focused", "window_id": flow.window.window_id
        }
        return None

    def _resolve_ax_ref_target(
        self, flow: _ActFlow, target: dict[str, Any]
    ) -> ToolResult | None:
        """ax_ref 通道：exact 重解析 → 路线 A web 边界 → N4 密码框红线。"""
        audit, ax_view, nodes = flow.audit, flow.ax_view, flow.nodes
        ax_ref = str(target["ax_ref"]).strip()
        if not ax_view.available:
            return self._refuse(
                flow,
                DesktopErrorCode.AX_UNAVAILABLE,
                f"AX 树不可用（{ax_view.failure}），无法解析 ax_ref。{GUIDANCE_AX}",
            )
        node_map = {n.ax_ref: n for n in nodes}
        node = node_map.get(ax_ref)
        if node is None:
            return self._refuse(
                flow,
                DesktopErrorCode.AX_REF_NOT_FOUND,
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
            return self._refuse(
                flow, DesktopErrorCode.WEB_TARGET_NOT_ALLOWED, GUIDANCE_WEB_TARGET,
            )
        if (node.role or "").lower() == "axsecuretextfield" or (
            node.subrole or ""
        ).lower() == "axsecuretextfield":
            return self._refuse(
                flow,
                DesktopErrorCode.PRIVACY_BLOCKED,
                "目标是密码型输入框（AXSecureTextField）；按 N4 红线拒绝键入，无降级路径。",
            )
        flow.target_identity = target_identity
        return None

    def _resolve_point_target(
        self, flow: _ActFlow, target: dict[str, Any]
    ) -> ToolResult | None:
        """point 通道：窗口 bounds 内判定 → M1 AXWebArea 命中（fail-closed）。"""
        window, audit = flow.window, flow.audit
        ax_view, nodes, browser = flow.ax_view, flow.nodes, flow.browser
        point = target["point"]
        px, py = float(point["x"]), float(point["y"])
        bounds = window.bounds_pt
        within = (
            bounds.x <= px < bounds.x + bounds.w and bounds.y <= py < bounds.y + bounds.h
        )
        if not within:
            return self._refuse(
                flow,
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
            return self._refuse(
                flow,
                DesktopErrorCode.WEB_TARGET_NOT_ALLOWED,
                f"point({px:.1f},{py:.1f}) 落在浏览器窗口网页内容区域（{why}）。"
                f"{GUIDANCE_WEB_TARGET}",
            )
        flow.target_identity = target_identity
        return None
    def _gate_review_web(self, flow: _ActFlow) -> ToolResult | None:
        """M2 发布/提交/支付 fail-closed + M1 浏览器 scroll/press_key web 边界。"""
        do, window, nodes, browser = flow.do, flow.window, flow.nodes, flow.browser
        target_identity = flow.target_identity
        # M2：发布/提交/支付类目标 fail-closed 拒绝（宿主发表闸缺失 ⇒ 不自行放行）。
        # ax_ref 通道用目标自身标题；point/focused/scroll 无法证明目标身份，退而用
        # 窗口标题（宁可误拒：该类目标是 §6.2/§6.3 的显式 MUST）。
        _review_texts: tuple[str | None, ...]
        if target_identity["kind"] == "ax_ref":
            _review_texts = (target_identity.get("title"), target_identity.get("subrole"))
        else:
            _review_texts = (window.title,)
        if hits_review_markers(*_review_texts):
            return self._refuse(
                flow, DesktopErrorCode.REVIEW_REQUIRED, GUIDANCE_REVIEW_REQUIRED,
                risk_class="irreversible",
            )
        # M1：浏览器窗口内 scroll（滚轮投递到 app 进程，默认作用于网页视口）与
        # press_key（作用于窗口焦点，网页焦点通常 AX 不可见）同样要过 web 边界。
        if browser and do == "scroll" and has_web_area(nodes):
            return self._refuse(
                flow,
                DesktopErrorCode.WEB_TARGET_NOT_ALLOWED,
                "浏览器窗口存在 AXWebArea：滚轮事件投递到 app 进程将作用于网页视口。"
                f"{GUIDANCE_WEB_TARGET}",
            )
        if browser and do == "press_key":
            focused_ref = focused_ax_ref(nodes)
            if focused_ref is not None and is_web_subtree(focused_ref, nodes):
                return self._refuse(
                    flow,
                    DesktopErrorCode.WEB_TARGET_NOT_ALLOWED,
                    f"窗口焦点（ax_ref={focused_ref}）位于浏览器网页内容层。{GUIDANCE_WEB_TARGET}",
                )
        return None

    def _gate_key_policy(self, flow: _ActFlow) -> ToolResult | None:
        """per-do 参数策略（B3 黑名单 / IME 缺口 / scroll 规格）。"""
        do, options = flow.do, flow.options
        keys = str(options.get("keys") or "")
        if do == "press_key":
            # P2-5（R2）：只做校验拒绝，不再把 flags 存进 options——该键从未被
            # 消费（_deliver 侧重解析），属死状态，已删除。
            status, detail, _ = parse_keycombo(keys)
            if status != "ok":
                return self._refuse(flow, DesktopErrorCode.KEY_NOT_ALLOWED, detail)
        if do == "scroll":
            status, detail, signed = parse_scroll(keys)
            if status != "ok":
                return self._refuse(flow, DesktopErrorCode.KEY_NOT_ALLOWED, detail)
            options["scroll_signed_lines"] = signed
        flow.keys = keys
        return None
    def _plan_risk_and_binding(self, flow: _ActFlow) -> None:
        """风险分级（§6.2 启发式 + M1 通道覆写）与世界/令牌绑定计算。"""
        do, options, window = flow.do, flow.options, flow.window
        bundle = window.bundle_id
        nodes, frontmost_before = flow.nodes, flow.frontmost_before
        target_identity, keys, audit = flow.target_identity, flow.keys, flow.audit
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
            risk_class, browser=flow.browser, do=do, target_kind=target_identity["kind"]
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
        flow.risk_class = risk_class
        flow.world = world
        flow.channel_token_required = channel_token_required
        flow.action_fp = action_fp
        flow.risk_note = risk_note
    def _dry_run_receipt(self, flow: _ActFlow) -> ToolResult:
        """dry_run：不投递，签发一次性令牌（§5.4/§6.3；前台探测失败不拦 dry_run）。"""
        do, window = flow.do, flow.window
        base, started, audit = flow.base, flow.started, flow.audit
        target_identity = flow.target_identity
        risk_class, world, action_fp = flow.risk_class, flow.world, flow.action_fp
        frontmost_before, risk_note = flow.frontmost_before, flow.risk_note
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
            # R5：前台口径 = 前台 app bundle（lsappinfo）；探测失败为 None
            "foreground_before": frontmost_before,
        }
        if risk_note:
            dry_payload["risk_note"] = risk_note
        return self._envelope(
            do=do, ok=True, error_code=None, guidance=None, started=started,
            base=base, payload=dry_payload,
        )
    def _apply(self, flow: _ActFlow) -> ToolResult:
        """apply 真实投递链调度（每一关失败都拒绝且不投递；关卡顺序不可变：
        D7 人在场/force 凭据 → 写开关 → EXEC_MODE → 会话/令牌 → D4 世界重绑
        （R5 前台 app 口径）→ U18 AX 探针 → 投递与回执）。"""
        flow.audit["dry_run"] = False
        refused = self._gate_hid_user_present(flow)
        if refused is not None:
            return refused
        if flow.force_used:
            refused = self._gate_force_credential(flow)
            if refused is not None:
                return refused
        refused = self._gate_writes_switch(flow)
        if refused is not None:
            return refused
        refused = self._gate_exec_mode(flow)
        if refused is not None:
            return refused
        refused = self._gate_session_token(flow)
        if refused is not None:
            return refused
        refused = self._gate_world_rebind(flow)
        if refused is not None:
            return refused
        refused = self._gate_ax_probe(flow)
        if refused is not None:
            return refused
        return self._deliver_and_receipt(flow)

    def _gate_hid_user_present(self, flow: _ActFlow) -> ToolResult | None:
        """D7 用户在场闸（最外层人类安全闸；P2-4/R2：先于写开关/EXEC_MODE）。"""
        do, options, backend = flow.do, flow.options, flow.backend
        base, started, audit = flow.base, flow.started, flow.audit
        idle_ms = backend.hid_idle_ms()
        audit["hid_idle_ms"] = idle_ms
        user_present = idle_ms is None or int(idle_ms) < USER_PRESENT_WINDOW_MS
        force_used = False
        if user_present:
            if not bool(options.get("force")):
                audit["error_code"] = DesktopErrorCode.USER_PRESENT.value
                self._audit_event(audit)
                # P2-4（R2）：apply 门控实际顺序为 D7 → writes_enabled → EXEC_MODE
                # （人在场是最外层人类安全闸）。写开关未开时 force 凭据也放行不到
                # 投递——提示语如实说明，不再单指 force 凭据。
                guidance = (
                    f"用户在场（HID idle={idle_ms if idle_ms is not None else '探针不可用，按在场处理'}ms"
                    f" < {USER_PRESENT_WINDOW_MS}ms，D7）：默认拒绝 mutate；"
                    "可稍后重试或携带一次性 force 凭据。"
                )
                if not self._writes_enabled:
                    guidance += (
                        "注意：当前写能力总开关未开启（LFL_DESKTOP_OPERATE_ENABLED 默认关，"
                        "T8），即使携带 force 凭据，apply 仍会被 writes_disabled 拒绝——"
                        "需用户显式开启写开关后才可真实投递。"
                    )
                guidance += GUIDANCE_FORCE
                return self._envelope(
                    do=do, ok=False, error_code=DesktopErrorCode.USER_PRESENT,
                    guidance=guidance,
                    started=started, base=base,
                    payload={"applied": False, "needs_confirmation": False,
                             "hid_idle_ms": idle_ms},
                )
            force_used = True
        flow.idle_ms = idle_ms
        flow.force_used = force_used
        return None

    def _gate_force_credential(self, flow: _ActFlow) -> ToolResult | None:
        """D7/S3 force 一次性凭据校验（仅 user_present+force 路径；S2 校验≠消耗）。"""
        do, options, audit = flow.do, flow.options, flow.audit
        base, started, idle_ms = flow.base, flow.started, flow.idle_ms
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
        return None
    def _gate_writes_switch(self, flow: _ActFlow) -> ToolResult | None:
        """写能力总开关（T8：默认关；先于令牌校验，避免烧毁令牌）。"""
        do, audit, base, started, idle_ms = (
            flow.do, flow.audit, flow.base, flow.started, flow.idle_ms,
        )
        if not self._writes_enabled:
            audit["error_code"] = DesktopErrorCode.WRITES_DISABLED.value
            self._audit_event(audit)
            return self._envelope(
                do=do, ok=False, error_code=DesktopErrorCode.WRITES_DISABLED,
                guidance=GUIDANCE_WRITES_DISABLED, started=started, base=base,
                payload={"applied": False, "needs_confirmation": False, "hid_idle_ms": idle_ms},
            )
        return None

    def _gate_exec_mode(self, flow: _ActFlow) -> ToolResult | None:
        """M3：宿主 EXEC_MODE 分级（blocked/readonly 拒绝；allowlist 需显式列出）。"""
        do, audit, base, started, idle_ms = (
            flow.do, flow.audit, flow.base, flow.started, flow.idle_ms,
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
        return None
    def _gate_session_token(self, flow: _ActFlow) -> ToolResult | None:
        """§6.2 会话门 + T6 令牌校验（M1：point 通道永不享受会话免令牌放行）。"""
        do, options, window = flow.do, flow.options, flow.window
        bundle = window.bundle_id
        audit, base, started = flow.audit, flow.base, flow.started
        risk_class, idle_ms, action_fp = flow.risk_class, flow.idle_ms, flow.action_fp
        channel_token_required = flow.channel_token_required
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
                "expired": DesktopErrorCode.CONFIRM_TOKEN_EXPIRED,  # P2-3（R2）
            }.get(status)
            if token_error is not None:
                audit["error_code"] = token_error.value
                self._audit_event(audit)
                guidance_map = {
                    DesktopErrorCode.CONFIRM_TOKEN_INVALID: "confirm_token 未知或不可解析（T6）。",
                    DesktopErrorCode.CONFIRM_TOKEN_REPLAYED: "confirm_token 已使用过（U17/T6：一次性，重放拒绝且已记审计）。",
                    DesktopErrorCode.CONFIRM_TOKEN_MISMATCH: "confirm_token 绑定不符（window_id/do/目标与签发时不一致，U16）；令牌已作废，需重新 dry_run。",
                    DesktopErrorCode.CONFIRM_TOKEN_EXPIRED: (
                        f"confirm_token 已过期（TTL {CONFIRM_TOKEN_TTL_S:.0f}s，P2-3）；"
                        "令牌已作废，需重新 dry_run 获取新令牌。"
                    ),
                }
                return self._envelope(
                    do=do, ok=False, error_code=token_error,
                    guidance=guidance_map[token_error], started=started, base=base,
                    payload={"applied": False, "needs_confirmation": True,
                             "risk_class": risk_class, "hid_idle_ms": idle_ms},
                )
        flow.session_id = session_id
        flow.token_record = token_record
        return None
    def _gate_world_rebind(self, flow: _ActFlow) -> ToolResult | None:
        """D4：apply 时世界重绑（R5：窗口所属 app 必须是前台 app；token 路径还
        要求 world 未漂移）。前台口径 = lsappinfo（front ASN → list 记录的
        bundle_id）；探测失败/无匹配 → None → fail-closed 拒绝，不当成通过。"""
        do, options, backend, audit = flow.do, flow.options, flow.backend, flow.audit
        base, started = flow.base, flow.started
        risk_class, idle_ms = flow.risk_class, flow.idle_ms
        frontmost_before, token_record = flow.frontmost_before, flow.token_record
        target_identity = flow.target_identity
        fresh_window = backend.get_window(int(options["window_id"]))
        frontmost_bundle = backend.frontmost_app_bundle()
        if (
            fresh_window is None
            or frontmost_bundle is None
            or fresh_window.bundle_id != frontmost_bundle
        ):
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
        # R5：apply 时刻前台归属 = 上面前台门控的同一探测结果（app 口径）
        fresh_frontmost = frontmost_bundle
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
        flow.fresh_window = fresh_window
        flow.fresh_world = fresh_world
        return None
    def _gate_ax_probe(self, flow: _ActFlow) -> ToolResult | None:
        """U18 同构自检：投递前 AX 探针（授权位有假阴性，探针才作数）。"""
        do, backend, audit = flow.do, flow.backend, flow.audit
        base, started = flow.base, flow.started
        risk_class, idle_ms = flow.risk_class, flow.idle_ms
        probe = backend.ax_probe(flow.fresh_window.pid)
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
        return None

    def _deliver_and_receipt(self, flow: _ActFlow) -> ToolResult:
        """真实投递 + post 指纹 + 会话批准 + 成功回执（S2：force 凭据此刻才消耗）。"""
        do, options, backend = flow.do, flow.options, flow.backend
        window, audit = flow.window, flow.audit
        base, started = flow.base, flow.started
        session_id, bundle = flow.session_id, flow.window.bundle_id
        target_identity = flow.target_identity
        risk_class, world, risk_note = flow.risk_class, flow.world, flow.risk_note
        fresh_window, fresh_world = flow.fresh_window, flow.fresh_world
        idle_ms, frontmost_before = flow.idle_ms, flow.frontmost_before
        force_used = flow.force_used
        channel_token_required = flow.channel_token_required
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
        # R5：前台口径 = 前台 app bundle（lsappinfo）。post 观测失败 → None（如实
        # 报告），不把已投递的动作误报成 backend_error——前台门控在投递前已完成。
        foreground_after = backend.frontmost_app_bundle()
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
