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

