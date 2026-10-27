"""L0 window inventory via CGWindowListCopyWindowInfo (ctypes, 点坐标).

D0 report §1.7: this channel works without TCC grants.  The one honesty rule
that matters here: without Screen Recording permission ``kCGWindowName`` comes
back as an empty string for EVERY window — the converter must surface that as
``title_available=False`` and must never substitute the owner/app name as a
title.  All geometry stays in points (D3): CG bounds are points.
"""

from __future__ import annotations

import ctypes

from llm_loop.desktop.macos_cf import (
    CFTypeRef,
    CGRect,
    cf_array_count,
    cf_array_item,
    cf_dict_get,
    cf_release,
    cf_to_bool,
    cf_to_float,
    cf_to_int,
    cf_to_str,
    load_framework,
)
from llm_loop.desktop.models import BoundsPt, DisplayInfo, WindowInfo

K_CG_WINDOW_NUMBER = "kCGWindowNumber"
K_CG_WINDOW_OWNER_NAME = "kCGWindowOwnerName"
K_CG_WINDOW_NAME = "kCGWindowName"
K_CG_WINDOW_LAYER = "kCGWindowLayer"
K_CG_WINDOW_BOUNDS = "kCGWindowBounds"
K_CG_WINDOW_OWNER_PID = "kCGWindowOwnerPID"
K_CG_WINDOW_IS_ONSCREEN = "kCGWindowIsOnscreen"

# kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
OPTION_ONSCREEN_ONLY = 1 | 16
# kCGWindowListExcludeDesktopElements only（include_offscreen=True：全窗口清单）
OPTION_ALL = 0 | 16

K_CG_NULL_WINDOW_ID = 0

_PROTO_READY = False


def _cg() -> ctypes.CDLL:
    global _PROTO_READY
    lib = load_framework("CoreGraphics")
    if not _PROTO_READY:
        lib.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        lib.CGWindowListCopyWindowInfo.restype = CFTypeRef
        lib.CGGetActiveDisplayList.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        lib.CGGetActiveDisplayList.restype = ctypes.c_int32
        lib.CGMainDisplayID.restype = ctypes.c_uint32
        lib.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        lib.CGDisplayBounds.restype = CGRect
        lib.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
        lib.CGDisplayPixelsWide.restype = ctypes.c_ulong
        lib.CGDisplayPixelsHigh.argtypes = [ctypes.c_uint32]
        lib.CGDisplayPixelsHigh.restype = ctypes.c_ulong
        lib.CGDisplayCopyDisplayMode.argtypes = [ctypes.c_uint32]
        lib.CGDisplayCopyDisplayMode.restype = CFTypeRef
        lib.CGDisplayModeGetPixelWidth.argtypes = [CFTypeRef]
        lib.CGDisplayModeGetPixelWidth.restype = ctypes.c_ulong
        lib.CGDisplayModeRelease.argtypes = [CFTypeRef]
        _PROTO_READY = True
    return lib


def _display_scale(lib: ctypes.CDLL, display_id: int, bounds_width_pt: float) -> float:
    """scale = 当前模式物理像素宽 / 点宽。

    实测（2026-10-27，macOS 26 sandbox 内）：CGDisplayPixelsWide 返回的是点数
    （1512），会算出假 scale=1.0；当前模式的 CGDisplayModeGetPixelWidth 才给出
    真物理像素（3024 → scale=2.0，与 F22/F23 的截图证据一致）。模式查询失败时
    依次回退 PixelsWide / 1.0，并在报告中注明该环境差异。
    """
    if bounds_width_pt <= 0:
        return 1.0
    try:
        mode = lib.CGDisplayCopyDisplayMode(ctypes.c_uint32(display_id))
        if mode:
            try:
                pixel_width = int(lib.CGDisplayModeGetPixelWidth(ctypes.c_void_p(mode)))
                if pixel_width > 0:
                    return round(pixel_width / bounds_width_pt, 2)
            finally:
                lib.CGDisplayModeRelease(ctypes.c_void_p(mode))
    except Exception:  # noqa: BLE001 - 模式查询失败按回退口径
        pass
    try:
        pixels_wide = int(lib.CGDisplayPixelsWide(ctypes.c_uint32(display_id)))
        if pixels_wide > 0:
            return round(pixels_wide / bounds_width_pt, 2)
    except Exception:  # noqa: BLE001
        pass
    return 1.0


def _bounds_from_cf(dict_ref: int) -> BoundsPt | None:
    if not dict_ref:
        return None
    x = cf_to_float(cf_dict_get(dict_ref, "X"))
    y = cf_to_float(cf_dict_get(dict_ref, "Y"))
    w = cf_to_float(cf_dict_get(dict_ref, "Width"))
    h = cf_to_float(cf_dict_get(dict_ref, "Height"))
    if None in (x, y, w, h):
        return None
    return BoundsPt(x=float(x), y=float(y), w=float(w), h=float(h))  # type: ignore[arg-type]


def list_raw_windows(include_offscreen: bool = False) -> list[dict]:
    """CGWindowList 原始行（front→back 顺序；键与探针脚本一致，全只读）。"""
    opts = OPTION_ALL if include_offscreen else OPTION_ONSCREEN_ONLY
    arr = _cg().CGWindowListCopyWindowInfo(ctypes.c_uint32(opts), K_CG_NULL_WINDOW_ID)
    if not arr:
        return []
    rows: list[dict] = []
    try:
        for i in range(cf_array_count(arr)):
            d = cf_array_item(arr, i)
            if not d:
                continue
            name_ref = cf_dict_get(d, K_CG_WINDOW_NAME)
            onscreen = cf_dict_get(d, K_CG_WINDOW_IS_ONSCREEN)
            onscreen_flag: bool | None = cf_to_bool(onscreen)
            bounds = _bounds_from_cf(cf_dict_get(d, K_CG_WINDOW_BOUNDS))
            rows.append(
                {
                    "id": cf_to_int(cf_dict_get(d, K_CG_WINDOW_NUMBER)),
                    "owner": cf_to_str(cf_dict_get(d, K_CG_WINDOW_OWNER_NAME)),
                    "name": cf_to_str(name_ref),
                    "layer": cf_to_int(cf_dict_get(d, K_CG_WINDOW_LAYER)),
                    "bounds": {
                        "x": bounds.x,
                        "y": bounds.y,
                        "w": bounds.w,
                        "h": bounds.h,
                    }
                    if bounds
                    else None,
                    "pid": cf_to_int(cf_dict_get(d, K_CG_WINDOW_OWNER_PID)),
                    "on_screen": onscreen_flag,
                }
            )
        return rows
    finally:
        cf_release(arr)


def window_infos_from_raw(
    rows: list[dict],
    pid_to_bundle: dict[int, str],
    *,
    on_screen_default: bool,
) -> list[WindowInfo]:
    """原始行 → WindowInfo（纯函数；title 诚实规则 + 前台窗口判定在此）。

    前台判定：front→back 序里第一个 layer==0 且在屏的窗口（唯一置位）。
    """
    infos: list[WindowInfo] = []
    foreground_seen = False
    for row in rows:
        layer = int(row.get("layer") or 0)
        on_screen = row.get("on_screen")
        on_screen_bool = on_screen_default if on_screen is None else bool(on_screen)
        name = row.get("name")
        title_available = isinstance(name, str) and bool(name)
        is_fg = False
        if not foreground_seen and layer == 0 and on_screen_bool:
            is_fg = True
            foreground_seen = True
        pid = int(row.get("pid") or 0)
        bounds = row.get("bounds") or {}
        infos.append(
            WindowInfo(
                window_id=int(row.get("id") or 0),
                pid=pid,
                app=str(row.get("owner") or ""),
                bundle_id=pid_to_bundle.get(pid),
                # 无屏幕录制授权 → kCGWindowName 恒为空串 → title=None（不冒充）
                title=(str(name) if title_available else None),
                title_available=title_available,
                title_redacted=False,
                bounds_pt=BoundsPt(
                    x=float(bounds.get("x") or 0.0),
                    y=float(bounds.get("y") or 0.0),
                    w=float(bounds.get("w") or 0.0),
                    h=float(bounds.get("h") or 0.0),
                ),
                layer=layer,
                on_screen=on_screen_bool,
                is_foreground=is_fg,
            )
        )
    return infos


def list_displays() -> list[DisplayInfo]:
    """活动显示器清单（bounds=点；scale=物理像素/点，U19 坐标合同的来源）。"""
    lib = _cg()
    max_displays = 32
    ids = (ctypes.c_uint32 * max_displays)()
    count = ctypes.c_uint32(0)
    err = lib.CGGetActiveDisplayList(max_displays, ids, ctypes.byref(count))
    if err != 0:
        return []
    main_id = int(lib.CGMainDisplayID())
    displays: list[DisplayInfo] = []
    for i in range(int(count.value)):
        did = int(ids[i])
        rect = lib.CGDisplayBounds(ctypes.c_uint32(did))
        width_pt = float(rect.size.width)
        scale = _display_scale(lib, did, width_pt)
        displays.append(
            DisplayInfo(
                id=did,
                is_main=(did == main_id),
                scale=scale,
                bounds_pt=BoundsPt(
                    x=float(rect.origin.x),
                    y=float(rect.origin.y),
                    w=width_pt,
                    h=float(rect.size.height),
                ),
            )
        )
    return displays


def display_scale_for_bounds(displays: list[DisplayInfo], bounds: BoundsPt) -> float | None:
    """窗口中心所在显示器的 scale；找不到（离屏坐标）→ None（调用方回退主屏）。"""
    cx = bounds.x + bounds.w / 2.0
    cy = bounds.y + bounds.h / 2.0
    for display in displays:
        b = display.bounds_pt
        if b.x <= cx <= b.x + b.w and b.y <= cy <= b.y + b.h:
            return display.scale
    main = [d for d in displays if d.is_main]
    return main[0].scale if main else None

