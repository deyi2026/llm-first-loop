"""macOS TCC/session self-checks via ctypes (M3 desktop, D0 report §5).

The three probes here are the "ax_status 自检" substrate:

- ``CGPreflightScreenCaptureAccess()`` — the ONLY trustworthy screen-capture
  grant check; ``screencapture`` exits 0 with a black image when ungranted
  (D0 report §5.4), so "command succeeded" must never be trusted.
- ``AXIsProcessTrusted()`` — plain variant only; the ``WithOptions`` prompt
  variant is deliberately NOT used (no permission dialogs from sensing).
- ``CGSessionCopyCurrentDictionary()`` — console user / on-console / locked.

Every function degrades to a safe default on unexpected failure instead of
raising: a probe that cannot run is reported as "not granted"/"no session",
never as success.
"""

from __future__ import annotations

import ctypes
import platform as _platform

from llm_loop.desktop.macos_cf import (
    CFTypeRef,
    cf_dict_get,
    cf_release,
    cf_to_bool,
    cf_to_str,
    load_framework,
    make_cfstr,
)
from llm_loop.desktop.models import (
    PermissionSnapshot,
    PlatformInfo,
    SessionSnapshot,
)

_CG = "CoreGraphics"
_ASF = "ApplicationServices"


def _cg() -> ctypes.CDLL:
    lib = load_framework(_CG)
    lib.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
    lib.CGSessionCopyCurrentDictionary.restype = CFTypeRef
    return lib


def _asf() -> ctypes.CDLL:
    lib = load_framework(_ASF)
    lib.AXIsProcessTrusted.restype = ctypes.c_bool
    lib.AXUIElementCreateSystemWideElement.restype = CFTypeRef
    lib.AXUIElementCopyAttributeValue.argtypes = [
        CFTypeRef,
        CFTypeRef,
        ctypes.POINTER(CFTypeRef),
    ]
    lib.AXUIElementCopyAttributeValue.restype = ctypes.c_int32
    return lib


def screen_capture_granted() -> bool:
    """屏幕录制授权预检（无授权时 screencapture 产黑图，禁止凭 rc 判断）。"""
    try:
        return bool(_cg().CGPreflightScreenCaptureAccess())
    except Exception:  # noqa: BLE001 - probe failure must read as "not granted"
        return False


def ax_trusted() -> bool:
    """辅助功能（AX）授权检查；绝不使用 AXIsProcessTrustedWithOptions 弹窗变体。"""
    try:
        return bool(_asf().AXIsProcessTrusted())
    except Exception:  # noqa: BLE001
        return False


def ax_error_probe() -> int | None:
    """真实 AX 读探针：systemwide 元素读 AXFocusedApplication 的错误码。

    未授权时确定性返回 -25211（kAXErrorAPIDisabled）——这就是 status 回执里
    ``permissions.ax_error`` 的实测来源；探针自身异常返回 None（不猜）。
    """
    try:
        lib = _asf()
        sw = lib.AXUIElementCreateSystemWideElement()
        if not sw:
            return None
        attr = make_cfstr("AXFocusedApplication")
        try:
            out = CFTypeRef()
            err = int(lib.AXUIElementCopyAttributeValue(sw, attr, ctypes.byref(out)))
            return err if err != 0 else None
        finally:
            cf_release(attr)
    except Exception:  # noqa: BLE001 - probe failure must stay None, not a lie
        return None


def permission_snapshot() -> PermissionSnapshot:
    # ax_error 永远来自真实探针（AXUIElementCopyAttributeValue 的实测返回值）；
    # 未授权时该调用确定性返回 -25211，探针自身异常才是 None——不预写常量冒充测量
    return PermissionSnapshot(
        ax_trusted=ax_trusted(),
        screen_capture_granted=screen_capture_granted(),
        ax_error=ax_error_probe(),
    )


def session_snapshot() -> SessionSnapshot:
    """CGSession 探针：console 用户 / 是否在图形会话 / 是否锁屏。

    screen_locked 契约为 bool|null：探针失败/无会话时给 None（"未知"），
    不给 False（那会变成"确定没锁屏"的断言）。
    """
    try:
        lib = _cg()
        session = lib.CGSessionCopyCurrentDictionary()
    except Exception:  # noqa: BLE001 - 无会话/框架异常一律按无 GUI 处理（locked=未知）
        return SessionSnapshot(gui_available=False, console_user=None, screen_locked=None)
    if not session:
        return SessionSnapshot(gui_available=False, console_user=None, screen_locked=None)
    try:
        # 键名以 2026-10-27 sandbox 实测为准（CGSessionCopyCurrentDictionary 全量 dump）：
        # 实际键带 "Key" 后缀（kCGSSessionOnConsoleKey / kCGSSessionUserNameKey /
        # kCGSessionLoginDoneKey）；CGSSessionScreenIsLocked 仅在锁屏时出现。
        user_ref = cf_dict_get(session, "kCGSSessionUserNameKey")
        on_console_ref = cf_dict_get(session, "kCGSSessionOnConsoleKey")
        login_done_ref = cf_dict_get(session, "kCGSessionLoginDoneKey")
        locked_ref = cf_dict_get(session, "CGSSessionScreenIsLocked")
        on_console = cf_to_bool(on_console_ref)
        login_done = cf_to_bool(login_done_ref)
        locked = cf_to_bool(locked_ref)
        gui_available = on_console is True or login_done is True
        return SessionSnapshot(
            gui_available=bool(gui_available),
            console_user=cf_to_str(user_ref),
            screen_locked=(True if locked is True else False if locked is False else None),
        )
    finally:
        cf_release(session)


def platform_info() -> PlatformInfo:
    return PlatformInfo(os=_platform.system().lower(), version=_platform.mac_ver()[0] or "")

