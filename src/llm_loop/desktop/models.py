"""M3 desktop read-only perception data model (DESIGN-20261027 §5.3 / §7.3).

Pure-Python dataclasses + error-code enum + serialization helpers shared by the
macOS backend and the ``desktop_perceive`` tool layer.  Importing this module
never loads macOS frameworks; backend implementations keep every ctypes load
lazy so the whole package imports safely on non-darwin platforms.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

# ── 契约常量（§5.3 / M3 委派契约）─────────────────────────────────────────
DEFAULT_AX_DEPTH = 3
MAX_AX_DEPTH = 6
MIN_AX_DEPTH = 0
AX_NODE_LIMIT_DEFAULT = 1500
CAPTURE_SIZE_TOLERANCE_PX = 2.0  # |px - pt*scale| 阈值（U19）
WINDOW_BIND_TOLERANCE_PT = 2.0  # D4 绑定 bounds 容差

AX_ERROR_API_DISABLED = -25211  # kAXErrorAPIDisabled（AX 未授权的确定性错误）
AX_ERROR_CANNOT_COMPLETE = -25204  # kAXErrorCannotComplete（目标 app 无响应/超时）
AX_ERROR_ATTRIBUTE_UNSUPPORTED = -25205
AX_ERROR_NO_VALUE = -25212


class DesktopErrorCode(StrEnum):
    """确定性回执错误码（不带栈、不抛异常；§5.5 + M3 委派补充 U14）。"""

    UNSUPPORTED_PLATFORM = "unsupported_platform"
    NO_GUI_SESSION = "no_gui_session"
    SCREEN_LOCKED = "screen_locked"
    AX_UNAVAILABLE = "ax_unavailable"
    CAPTURE_UNAVAILABLE = "capture_unavailable"
    CAPTURE_TIMEOUT = "capture_timeout"
    WINDOW_NOT_FOUND = "window_not_found"
    WINDOW_AMBIGUOUS = "window_ambiguous"
    PRIVACY_BLOCKED = "privacy_blocked"
    APP_NOT_ALLOWED = "app_not_allowed"
    BACKEND_ERROR = "backend_error"
    # ── M4 desktop_operate（DESIGN-20261027 §5.4/§5.5/§6.2/§6.4/D5-D9）──
    WINDOW_UNBOUND = "window_unbound"  # D4：绑定期内目标/窗口身份不再命中
    FOREGROUND_CHANGED = "foreground_changed"  # U16/U20：world 漂移，令牌作废
    USER_PRESENT = "user_present"  # D7/U15：HID idle < 60s，默认拒 mutate
    KEY_NOT_ALLOWED = "key_not_allowed"  # U5/B3：按键黑名单/闭合键集外
    COORDINATE_OUT_OF_BOUNDS = "coordinate_out_of_bounds"  # §7.3.2：点越界
    DRY_RUN_REQUIRED = "dry_run_required"  # §6.2：act 首次必须 dry_run
    CONFIRM_TOKEN_INVALID = "confirm_token_invalid"  # T6：未知/不可解析令牌
    CONFIRM_TOKEN_REPLAYED = "confirm_token_replayed"  # U17/T6：一次性令牌重放
    CONFIRM_TOKEN_MISMATCH = "confirm_token_mismatch"  # U16：令牌绑定不符
    WRITES_DISABLED = "writes_disabled"  # T8：写能力开关默认关
    FORCE_CREDENTIAL_MISSING = "force_credential_missing"  # D7：force 缺一次性凭据
    FORCE_CREDENTIAL_INVALID = "force_credential_invalid"  # D7：凭据不匹配/已消耗
    WEB_TARGET_NOT_ALLOWED = "web_target_not_allowed"  # 路线 A：网页层走 browser_operate
    TYPE_TEXT_TOO_LONG = "type_text_too_long"  # §5.5：>2000 字符
    TYPE_ARGS_INVALID = "type_args_invalid"  # §5.5：type 参数非法
    # ── R1 修复轮（M2/M3/S1/S6）──
    INVALID_ARGS = "invalid_args"  # S6：入口参数形状非法，统一 JSON 信封回执
    # ── B-1 续读分页（DESIGN-20261104 §6.1）──
    # 三码分开是刻意的：游标坏（调用方拼错）、树变了（世界漂移）、额度耗尽
    # 对调用方是三种完全不同的处置，合并成一个码会逼它去猜。
    CURSOR_INVALID = "cursor_invalid"
    CURSOR_STALE = "cursor_stale"
    PAGE_BUDGET_EXHAUSTED = "page_budget_exhausted"
    REVIEW_REQUIRED = "review_required"  # M2：发布/提交/支付类目标须宿主发表闸，本工具 fail-closed 拒绝
    EXEC_MODE_BLOCKED = "exec_mode_blocked"  # M3：宿主 EXEC_MODE=blocked/readonly 拒绝真实投递（dry_run 不受限）
    # ── R2 修复轮（P2-3）──
    CONFIRM_TOKEN_EXPIRED = "confirm_token_expired"  # T6/P2-3：一次性令牌超 TTL 未兑换，按过期拒绝
    # ── R3 修复轮（P0 寻址链路）──
    AX_REF_NOT_FOUND = "ax_ref_not_found"  # R3：act-time ax_ref 解析失败与窗口解绑分口径（原并入 window_unbound，掩盖真因）


# AX 错误码 → (确定性错误码, 人类可读 reason)。-25211 是权限类（给修复指引）；
# 其余（-25204 等）是通道类（app 无响应/超时），确定性失败但指引不同。
_AX_ERROR_MAP: dict[int, tuple[DesktopErrorCode, str]] = {
    AX_ERROR_API_DISABLED: (
        DesktopErrorCode.AX_UNAVAILABLE,
        "AX API 未授权（kAXErrorAPIDisabled -25211）",
    ),
    AX_ERROR_CANNOT_COMPLETE: (
        DesktopErrorCode.AX_UNAVAILABLE,
        "AX 查询无法完成（kAXErrorCannotComplete -25204；目标应用无响应或不支持 AX）",
    ),
    AX_ERROR_ATTRIBUTE_UNSUPPORTED: (
        DesktopErrorCode.AX_UNAVAILABLE,
        "AX 属性不受支持（kAXErrorAttributeUnsupported -25205）",
    ),
    AX_ERROR_NO_VALUE: (
        DesktopErrorCode.AX_UNAVAILABLE,
        "AX 属性当前无值（kAXErrorNoValue -25212）",
    ),
}


def ax_error_to_code(err: int) -> DesktopErrorCode:
    """AX 错误码 → 确定性错误码（未知码归 backend_error）。"""
    mapped = _AX_ERROR_MAP.get(int(err))
    return mapped[0] if mapped else DesktopErrorCode.BACKEND_ERROR


def ax_error_reason(err: int) -> str:
    mapped = _AX_ERROR_MAP.get(int(err))
    return mapped[1] if mapped else f"AX 调用返回错误码 {int(err)}"


def clamp_depth(raw: Any) -> tuple[int, bool]:
    """depth 裁剪到 0..6；返回 (生效深度, 是否被裁剪)。"""
    try:
        depth = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_AX_DEPTH, True
    if depth < MIN_AX_DEPTH:
        return MIN_AX_DEPTH, True
    if depth > MAX_AX_DEPTH:
        return MAX_AX_DEPTH, True
    return depth, False


# ── 几何（对外唯一单位：点；截图另回像素 + scale）──────────────────────────


@dataclass(frozen=True)
class Pt:
    x: float
    y: float


@dataclass(frozen=True)
class Size:
    w: float
    h: float


@dataclass(frozen=True)
class BoundsPt:
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class DisplayInfo:
    id: int
    is_main: bool
    scale: float
    bounds_pt: BoundsPt


@dataclass(frozen=True)
class AppInfo:
    bundle_id: str | None
    name: str
    pid: int | None
    is_foreground: bool
    is_hidden: bool
    allowed: bool = True


@dataclass(frozen=True)
class WindowInfo:
    """CGWindowList 窗口行（L0）。

    ``is_foreground`` 是 CG 序位置推断（front→back 首个 layer==0 且在屏窗口），
    **非 app 焦点**：仅作窗口清单展示属性（R5 口径声明）。投递前台门控判据是
    后台 ``frontmost_app_bundle()``（lsappinfo front+list 按 ASN 匹配），勿用
    本字段——真机实测 CG 序可与 app 焦点不一致（见 M4 dev report R5）。
    """

    window_id: int
    pid: int
    app: str
    bundle_id: str | None
    title: str | None
    title_available: bool
    title_redacted: bool
    bounds_pt: BoundsPt
    layer: int
    on_screen: bool
    is_foreground: bool


@dataclass(frozen=True)
class AxNode:
    ax_ref: str
    role: str | None
    subrole: str | None
    title: str | None
    value: str | None
    focused: bool
    pos_pt: Pt | None
    size_pt: Size | None
    # FR-03（DESIGN-20261104 §6.3）：AXEditable 读取通道。None = 未知/该角色无此属性，
    # 绝不用 role 反推冒充已读。不进入 world 指纹（ax_fingerprint_nodes 只取
    # ax_ref|role|title），也不进入节点行渲染（_NODE_FIELDS 显式白名单），
    # 因此对既有负载零增量。
    editable: bool | None = None
    # FR-05（§6.5）：AXEnabled 读取通道。None = 未知/该角色无此属性。
    # 谓词求值把 None 当"不成立"（见 waiting.evaluate）——把读不到当 True
    # 会让调用方在真不可用时继续点。同样不进指纹、不进节点行渲染。
    enabled: bool | None = None


@dataclass(frozen=True)
class ImageInfo:
    ref: str
    path: str
    sha256: str
    width: int
    height: int
    scale: float
    bounds_pt: BoundsPt
    captured_at: str
    bytes: int


@dataclass(frozen=True)
class PermissionSnapshot:
    ax_trusted: bool
    screen_capture_granted: bool
    ax_error: int | None = None


@dataclass(frozen=True)
class SessionSnapshot:
    gui_available: bool
    console_user: str | None
    screen_locked: bool | None  # 探针失败/无会话 → None（未知），非 False（断言未锁）


@dataclass(frozen=True)
class PlatformInfo:
    os: str
    version: str


@dataclass(frozen=True)
class CaptureOutcome:
    image: ImageInfo | None
    error: DesktopErrorCode | None
    detail: str | None = None
    degraded: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ActOutcome:
    """M4 写动作投递结果（确定性，不带栈）。

    ok=True 表示动作已真实投递（AX err==0 或 CGEvent 已 post）；
    ok=False 时 error 给出确定性错误码，detail 给不含栈的原因。
    """

    ok: bool
    error: DesktopErrorCode | None = None
    detail: str | None = None
    ax_error: int | None = None
    verified: bool | None = None  # type 动作写入后回读校验结果（None=不适用）


@dataclass(frozen=True)
class AxCandidate:
    ax_index: int
    title: str | None
    bounds_pt: BoundsPt


@dataclass(frozen=True)
class AxView:
    """L1 结果视图：available=False 时 failure 说明缺哪层（不整单失败）。"""

    available: bool
    failure: str | None = None  # "ax_unavailable"|"window_ambiguous"|"ax_window_unbound"
    ax_error: int | None = None
    root_role: str | None = None
    nodes: tuple[AxNode, ...] = field(default_factory=tuple)
    truncated: bool = False
    candidates: tuple[AxCandidate, ...] = field(default_factory=tuple)
    # D4 绑定依据："title_exact"|"title_relaxed"|"bounds_only"（None=未绑定）。
    # 记录它是因为 title_relaxed 意味着"按前缀相容认定同一窗口"，调用方应看到降级标注。
    binding: str | None = None


def jsonable(obj: Any) -> Any:
    """dataclass → JSON 可序列化结构（递归）。"""
    return asdict(obj)


# ── 后端抽象（macOS 实现见 backend_macos.py；测试注入 fake）────────────────


@runtime_checkable
class DesktopBackend(Protocol):
    """desktop_perceive 的只读后端合同。实现必须只读、无网络、无 shell。"""

    supported: bool

    def platform_info(self) -> PlatformInfo: ...
    def session_snapshot(self) -> SessionSnapshot: ...
    def permission_snapshot(self) -> PermissionSnapshot: ...
    def capability_snapshot(self) -> dict[str, bool]: ...
    def list_displays(self) -> list[DisplayInfo]: ...
    def process_info(self) -> dict[str, Any]: ...
    def list_apps(self) -> list[AppInfo]: ...
    def list_windows(self, include_offscreen: bool = False) -> list[WindowInfo]: ...
    def get_window(self, window_id: int) -> WindowInfo | None: ...
    def ax_snapshot(self, window: WindowInfo, depth: int, node_limit: int) -> AxView: ...
    def capture_window(self, window: WindowInfo) -> CaptureOutcome: ...

