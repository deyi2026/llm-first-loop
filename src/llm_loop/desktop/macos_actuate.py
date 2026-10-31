"""M4 actuation: AX actions (primary) + CGEvent fallback channels (narrow).

A-level channel facts that shaped this module (2026-10-31 probe log §11.7):

- ``AXPress`` on a native AXCloseButton: delivered, err=0, window 1→0 (PROVEN).
- ``AXSetAttributeValue(kAXValue)`` on AXTextArea: write + readback identical
  (PROVEN).  This is the ONLY typing path M4 exposes — see next point.
- CGEvent keyboard letters: delivered but POLLUTED by the active input method
  (com.apple.inputmethod.SCIM pinyin-ABC splits "asd" into "a␣s␣d"; pure
  unicode events produce nothing).  Therefore M4 deliberately does NOT offer
  letter/character CGEvent typing: ``press_key`` accepts a closed set of
  non-IME-polluted named keys only (Enter/Escape/arrows/…).  For the same
  reason there is no CGEvent "type" fallback at all — AX set-value or refuse.

Element addressing reuses the M3 ``ax_ref`` index-path contract (path from
the APP root: first index = window index in AXWindows, then AXChildren
indexes), so a target id from a ``desktop_perceive(action=snapshot)`` receipt
resolves to the same element here.  Resolution is act-time exact addressing
(§6.1 T5): re-resolved from a live tree, never trusted from the request text.

Ownership: ``resolve_element_by_axref`` retains every intermediate element
and releases it once the next level is retained, and the caller owns (and
must ``release()``) the returned element — no dangling refs, no leaks.
"""

from __future__ import annotations

import contextlib
import ctypes

from llm_loop.desktop.macos_ax import (
    MacAxElement,
    app_element,
    ax_read_attr,
    element_bounds,
    match_ax_windows_ex,
)
from llm_loop.desktop.macos_cf import (
    CFTypeRef,
    CGPoint,
    cf_array_count,
    cf_array_item,
    cf_release,
    cf_retain,
    cf_to_str,
    load_framework,
    make_cfstr,
)
from llm_loop.desktop.models import (
    ActOutcome,
    AxNode,
    BoundsPt,
    DesktopErrorCode,
    WindowInfo,
    ax_error_reason,
)

_ACT_READY = False


def _asf() -> ctypes.CDLL:
    global _ACT_READY
    lib = load_framework("ApplicationServices")
    if not _ACT_READY:
        lib.AXUIElementPerformAction.argtypes = [CFTypeRef, CFTypeRef]
        lib.AXUIElementPerformAction.restype = ctypes.c_int32
        lib.AXUIElementSetAttributeValue.argtypes = [
            CFTypeRef,
            CFTypeRef,
            CFTypeRef,
        ]
        lib.AXUIElementSetAttributeValue.restype = ctypes.c_int32
        _ACT_READY = True
    return lib


def _cg() -> ctypes.CDLL:
    lib = load_framework("CoreGraphics")
    lib.CGEventCreateMouseEvent.argtypes = [
        CFTypeRef,
        ctypes.c_uint32,
        CGPoint,
        ctypes.c_uint32,
    ]
    lib.CGEventCreateMouseEvent.restype = CFTypeRef
    lib.CGEventPost.argtypes = [ctypes.c_uint32, CFTypeRef]
    lib.CGEventPost.restype = None
    lib.CGEventPostToPid.argtypes = [ctypes.c_int32, CFTypeRef]
    lib.CGEventPostToPid.restype = None
    lib.CGEventCreateScrollWheelEvent.argtypes = [
        CFTypeRef,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_int32,
    ]
    lib.CGEventCreateScrollWheelEvent.restype = CFTypeRef
    lib.CGEventCreateKeyboardEvent.argtypes = [CFTypeRef, ctypes.c_uint32, ctypes.c_bool]
    lib.CGEventCreateKeyboardEvent.restype = CFTypeRef
    lib.CGEventSetFlags.argtypes = [CFTypeRef, ctypes.c_uint64]
    lib.CGEventSetFlags.restype = None
    return lib


# CGEvent 常量（无 pyobjc，数值按 CGEventTypes.h 固定）
K_CGEVENT_TAP_HID = 0  # kCGHIDEventTap：与真实输入同层投递
K_CGEVENT_LEFT_MOUSE_DOWN = 1
K_CGEVENT_LEFT_MOUSE_UP = 2
K_CGSCROLL_EVENT_UNIT_LINE = 1
K_CGEVENT_FLAG_MASK_CONTROL = 0x1_0000
K_CGEVENT_FLAG_MASK_SHIFT = 0x2_0000
K_CGEVENT_FLAG_MASK_ALTERNATE = 0x8_0000


def _parse_ax_ref(ax_ref: str) -> list[int] | None:
    """ax_ref 索引路径（"0.2.1"）→ 索引列表；格式非法 → None。"""
    parts = str(ax_ref or "").strip().split(".")
    if not parts or any(not part.isdigit() for part in parts):
        return None
    return [int(part) for part in parts]


def _ax_window_candidates(app_ref: int) -> tuple[list[MacAxElement], int]:
    """读 app 的 AXWindows；返回 (retain 后的窗口元素列表, AX err)。

    S7（R1）：构造中途抛异常时，已 retain 的元素先释放再传播——不静默泄漏。
    """
    err, value = ax_read_attr(app_ref, "AXWindows")
    if err != 0 or not value:
        return [], err
    elements: list[MacAxElement] = []
    try:
        count = cf_array_count(value)
        for i in range(count):
            elements.append(MacAxElement(cf_retain(cf_array_item(value, i))))
        return elements, 0
    except BaseException:
        for el in elements:
            with contextlib.suppress(Exception):
                el.release()
        raise
    finally:
        cf_release(value)


def resolve_window_element(window: WindowInfo) -> tuple[MacAxElement | None, str | None]:
    """D4 匹配（复用 M3 match_ax_windows_ex）→ 唯一命中的窗口元素（调用方释放）。

    返回 (element, failure)；failure ∈ {"ax_unavailable","ax_window_unbound",
    "window_ambiguous"}，与 M3 AxView.failure 同口径。
    """
    app = app_element(window.pid)
    if app is None:
        return None, "ax_unavailable"
    try:
        elements, err = _ax_window_candidates(app.ref)
    finally:
        app.release()  # AXWindows 已读出并逐个 retain，app 元素即可释放
    try:
        if err != 0:
            return None, "ax_unavailable"
        if not elements:
            return None, "ax_window_unbound"
        candidates: list[tuple[int, str | None, BoundsPt]] = []
        for ax_index, el in enumerate(elements):
            bounds = element_bounds(el)
            if bounds is None:
                continue
            title = el.attr("AXTitle")
            candidates.append(
                (ax_index, title if isinstance(title, str) else None, bounds)
            )
        hits, _ = match_ax_windows_ex(window, candidates)
        if not hits:
            return None, "ax_window_unbound"
        if len(hits) > 1:
            return None, "window_ambiguous"
        bound = elements[hits[0]]
        cf_retain(bound.ref)  # 调用方接管；下方循环对全部元素（含 bound）release
        return bound, None
    finally:
        for el in elements:
            el.release()


def resolve_element_by_axref(window: WindowInfo, ax_ref: str) -> tuple[MacAxElement | None, str | None]:
    """act-time exact addressing：按 ax_ref 索引路径解析到活元素（调用方释放）。"""
    path = _parse_ax_ref(ax_ref)
    if not path:
        return None, "ax_ref_invalid"
    el, failure = resolve_window_element(window)
    if el is None:
        return None, failure
    try:
        for index in path[1:]:
            children = el.attr("AXChildren")
            if not isinstance(children, list) or index >= len(children):
                el.release()  # S7（R1）：早退分支同样释放当前持有元素，不泄漏
                return None, "ax_ref_not_found"
            child = children[index]  # attr() 返回的子元素已被 retain（所有权移交）
            el.release()  # 上一级用完即放
            el = child
        return el, None
    except Exception:  # noqa: BLE001 - 解析失败按未命中，不猜
        with contextlib.suppress(Exception):
            el.release()
        return None, "ax_ref_not_found"


def ax_press(el: MacAxElement) -> int:
    """AXUIElementPerformAction(el, "AXPress") → AX err。"""
    lib = _asf()
    action = make_cfstr("AXPress")
    try:
        return int(lib.AXUIElementPerformAction(ctypes.c_void_p(el.ref), action))
    finally:
        cf_release(action)


def ax_set_value(el: MacAxElement, text: str) -> int:
    """AXUIElementSetAttributeValue(el, "AXValue", CFString) → AX err（已实测通道）。"""
    lib = _asf()
    attr = make_cfstr("AXValue")
    value = make_cfstr(text)
    try:
        return int(
            lib.AXUIElementSetAttributeValue(ctypes.c_void_p(el.ref), attr, ctypes.c_void_p(value))
        )
    finally:
        cf_release(attr)
        cf_release(value)


def ax_read_value_string(el: MacAxElement) -> str | None:
    err, value_ref = ax_read_attr(el.ref, "AXValue")
    if err != 0 or not value_ref:
        return None
    try:
        return cf_to_str(value_ref)
    finally:
        cf_release(value_ref)


def cg_post_click(x_pt: float, y_pt: float) -> None:
    """全局点（单位=点）左键点击：HID tap 层 down+up。

    S4（R1）：CGEventCreateMouseEvent 返回空事件时不投递（与 cg_post_key 对齐），
    只释放已创建的事件句柄。
    """
    lib = _cg()
    where = CGPoint(float(x_pt), float(y_pt))
    down = lib.CGEventCreateMouseEvent(None, K_CGEVENT_LEFT_MOUSE_DOWN, where, 0)
    if down:
        lib.CGEventPost(K_CGEVENT_TAP_HID, down)
    up = lib.CGEventCreateMouseEvent(None, K_CGEVENT_LEFT_MOUSE_UP, where, 0)
    if up:
        lib.CGEventPost(K_CGEVENT_TAP_HID, up)
    for event in (down, up):
        if event:
            cf_release(event)


def cg_post_scroll_to_pid(pid: int, lines: int) -> None:
    """滚轮事件定向投递到目标进程（不挪动用户光标）。lines 正=向上、负=向下。"""
    lib = _cg()
    event = lib.CGEventCreateScrollWheelEvent(
        None, K_CGSCROLL_EVENT_UNIT_LINE, 1, ctypes.c_int32(int(lines))
    )
    if not event:
        raise OSError("CGEventCreateScrollWheelEvent 返回空事件")
    try:
        lib.CGEventPostToPid(ctypes.c_int32(int(pid)), event)
    finally:
        cf_release(event)


def cg_post_key(keycode: int, flags: int) -> None:
    """命名键（闭合键集、非字母）keydown+keyup；flags 为 CGEventFlagMask 组合。"""
    lib = _cg()
    down = lib.CGEventCreateKeyboardEvent(None, ctypes.c_uint32(keycode), True)
    if down:
        lib.CGEventSetFlags(down, ctypes.c_uint64(flags))
        lib.CGEventPost(K_CGEVENT_TAP_HID, down)
    up = lib.CGEventCreateKeyboardEvent(None, ctypes.c_uint32(keycode), False)
    if up:
        lib.CGEventSetFlags(up, ctypes.c_uint64(flags))
        lib.CGEventPost(K_CGEVENT_TAP_HID, up)
    for event in (down, up):
        if event:
            cf_release(event)


def act_outcome_from_ax_err(err: int, what: str) -> ActOutcome:
    """AX err → 确定性 ActOutcome（未知码按 backend_error，带原始原因文本）。"""
    if err == 0:
        return ActOutcome(ok=True)
    reason = ax_error_reason(err)
    return ActOutcome(
        ok=False,
        error=DesktopErrorCode.AX_UNAVAILABLE,
        detail=f"{what} 未投递成功：{reason}",
        ax_error=err,
    )


def ax_fingerprint_nodes(nodes: tuple[AxNode, ...]) -> str:
    """节点指纹原料：ax_ref|role|title 序列（不含 value——type 写入会改 value）。"""
    return ";".join(f"{n.ax_ref}|{n.role or ''}|{n.title or ''}" for n in nodes)
